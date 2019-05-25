#general imports
import logging
#specific imports from std
from time import sleep, time
from uuid import uuid4
from functools import partial
from ipaddress import ip_address
#imports from 3rd party
from secp256k1_zkp import PrivateKey
#general leer imports
from leer.syncer import Syncer
from leer.core.utils import DOSException
from leer.core.parameters.constants import serialized_genesis_block
#storage space imports
from leer.core.storage.storage_space import StorageSpace
from leer.core.chains.headers_manager import HeadersManager
from leer.core.chains.blockchain import Blockchain
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.storage.blocks_storage import BlocksStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.utxo_index_storage import UTXOIndex
from leer.core.storage.mempool_tx import MempoolTx
#primitives imports
from leer.core.lubbadubdub.address import Address
from leer.core.lubbadubdub.transaction import Transaction
from leer.core.primitives.transaction_skeleton import TransactionSkeleton
#ops imports
from leer.core.core_operations.core_context import CoreContext
from leer.core.core_operations.sending_assets import notify_all_nodes_about_tx
from leer.core.core_operations.receiving_assets import process_new_headers, process_new_blocks, process_new_txos, process_tbm_tx
from leer.core.core_operations.sending_metadata import send_tip_info, notify_all_nodes_about_new_tip, send_find_common_root
from leer.core.core_operations.process_metadata import metadata_handlers
from leer.core.core_operations.notifications import set_notify_wallet_hook, set_value_to_queue
from leer.core.core_operations.downloading import download_status_checks
from leer.core.core_operations.process_requests import request_handlers
from leer.core.core_operations.handle_mining import mining_operations
from leer.core.core_operations.blockchain_initialization import init_blockchain, validate_state, set_ask_for_blocks_hook, set_ask_for_txouts_hook

logger = logging.getLogger("core_loop")

storage_space = None

def init_storage_space(config):
  global storage_space
  _path = config["location"]["basedir"]
  storage_space=StorageSpace(_path)
  with storage_space.env.begin(write=True) as wtx:
    hs = HeadersStorage(storage_space, wtx=wtx)
    hm = HeadersManager(storage_space, do_not_check_pow=config.get('testnet_options', {}).get('do_not_check_pow', False))
    bs = BlocksStorage(storage_space, wtx=wtx)
    es = ExcessesStorage(storage_space, wtx=wtx)
    ts = TXOsStorage(storage_space, wtx=wtx)
    bc = Blockchain(storage_space)
    mptx = MempoolTx(storage_space, config["fee_policy"], config.get("mining", {}))
    utxoi = UTXOIndex(storage_space, wtx=wtx)
    init_blockchain(storage_space, wtx=wtx, logger=logger)
    validate_state(storage_space, rtx=wtx, logger=logger)
  

def is_ip_port_array(x):
  res = True
  for _ in x:
    try:
      address, port = ip_address(_[0]), int(_[1])
    except:
      res=False
      break
  return res

def core_loop(syncer, config):
  init_storage_space(config)    

  nodes = {}
  requests = {} # requests to other node's subprocesses
  requests_cache = {"blocks":[], "txouts":[]} # requests of assets to other nodes

  set_ask_for_blocks_hook(storage_space.blockchain, requests_cache)
  set_ask_for_txouts_hook(storage_space.blocks_storage, requests_cache)
  if config['wallet']:
    set_notify_wallet_hook(storage_space.blockchain, syncer.queues['Wallet'])

  message_queue = syncer.queues['Blockchain']
  message_queue.put({"action":"give nodes list reminder"})
  message_queue.put({"action":"check requests cache"})

  #set logging
  default_log_level = logging.INFO;
  if "logging" in config:#debug, info, warning, error, critical
    loglevels = { "debug":logging.DEBUG, "info":logging.INFO, "warning":logging.WARNING, "error":logging.ERROR, "critical":logging.CRITICAL}
    if "base" in config["logging"] and config["logging"]["base"] in loglevels:
      logger.setLevel(loglevels[config["logging"]["base"]])
    if "core" in config["logging"] and config["logging"]["core"] in loglevels:
      #its ok to rewrite
      logger.setLevel(loglevels[config["logging"]["core"]])

  is_benchmark = config.get('testnet_options', {}).get('benchmark', False)
  no_pow = config.get('testnet_options', {}).get('do_not_check_pow', False)

  def get_new_address(timeout=2.5): #blocking
    _id = str(uuid4())
    syncer.queues['Wallet'].put({'action':'give new address', 'id':_id, 'sender': "Blockchain"})
    result = None
    start_time=time()
    while True:
      put_back = [] #We wait for specific message, all others will wait for being processed
      while not message_queue.empty():
        message = message_queue.get()
        if (not 'id' in message)  or (not message['id']==_id):
          put_back.append(message)
          continue
        result = message['result']
        break
      for message in put_back:
        message_queue.put(message)
      if result:
        break
      sleep(0.01)
      if time()-start_time>timeout:
        raise Exception("get_new_address timeout: probably wallet has collapsed or not running")      
    if result=='error':
      raise Exception("Can not get_new_address: error on wallet side")      
    address = Address()
    logger.info("Receiving address %s (len %d)"%( result, len(result)))
    address.deserialize_raw(result)
    return address

  def send_message(destination, message):
    logger.debug("Sending message to %s:\t\t %s"%(str(destination), str(message)))
    if not 'id' in message:
      message['id'] = uuid4()
    if not 'sender' in message:
      message['sender'] = "Blockchain"
    syncer.queues[destination].put(message)

  def send_to_network(message):
    send_message("NetworkManager", message)

  notify = partial(set_value_to_queue, syncer.queues["Notifications"], "Blockchain")

  core_context = CoreContext(storage_space, logger, nodes, notify, send_message, get_new_address, config)
  logger.debug("Start of core loop")
  with storage_space.env.begin(write=True) as rtx: #Set basic chain info, so wallet and other services can start work
    notify("blockchain height", storage_space.blockchain.current_height(rtx=rtx))
    notify("best header", storage_space.headers_manager.best_header_height)         
  while True:
    sleep(0.05)
    put_back_messages = []
    notify("core workload", "idle")
    while not message_queue.empty():
      message = message_queue.get()
      if 'time' in message and message['time']>time(): # delay this message
        put_back_messages.append(message)
        continue
      if (('result' in message) and message['result']=="processed") or \
         (('result' in message) and message['result']=="set") or \
         (('action' in message) and message['action']=="give nodes list reminder") or \
         (('action' in message) and message['action']=="check requests cache") or \
         (('action' in message) and message['action']=="take nodes list") or \
         (('result' in message) and is_ip_port_array(message['result'])):
        logger.debug("Processing message %s"%message)
      else:
        if 'action' in message:
          logger.info("Processing message `%s`"%message['action'])
        else:
          logger.info("Processing message %s"%message)  
      if not 'action' in message: #it is response
        if message['id'] in requests: # response is awaited
          if requests[message['id']]=="give nodes list":
            requests.pop(message['id'])
            message_queue.put({"action":"take nodes list", "nodes":message["result"]})
        else:
          pass #Drop
        continue
      try:
        if ("node" in message) and (not message["node"] in nodes):
          nodes[message["node"]]={'node':message["node"]}
        if message["action"] == "take the headers":
          notify("core workload", "processing new headers")
          with storage_space.env.begin(write=True) as wtx:
            process_new_headers(message, nodes[message["node"]], wtx, core_context)
          notify("best header", storage_space.headers_manager.best_header_height)         
        if message["action"] == "take the blocks":
          notify("core workload", "processing new blocks")
          with storage_space.env.begin(write=True) as wtx:
            initial_tip = storage_space.blockchain.current_tip(rtx=wtx)
            process_new_blocks(message, wtx, core_context)
            after_tip = storage_space.blockchain.current_tip(rtx=wtx)
            notify("blockchain height", storage_space.blockchain.current_height(rtx=wtx))         
            if not after_tip==initial_tip:
              notify_all_nodes_about_new_tip(nodes, rtx=wtx, core=core_context, _except=[], _payload_except=[]) 
            look_forward(nodes, send_to_network, rtx=wtx)       
        if message["action"] == "take the txos":
          notify("core workload", "processing new txos")
          with storage_space.env.begin(write=True) as wtx:
            process_new_txos(message, wtx=wtx, core=core_context)
            #After downloading new txos some blocs may become downloaded
            notify("blockchain height", storage_space.blockchain.current_height(rtx=wtx)) 
            look_forward(nodes, send_to_network, rtx=wtx)
        if message["action"] in request_handlers: #blocks, headers, txos and tbm
          notify("core workload", "processing "+message["action"])
          with storage_space.env.begin(write=False) as rtx:
            request_handlers[message["action"]](message, rtx=rtx, core=core_context)                    
        if message["action"] in metadata_handlers: # take tip, find common root [response]
          with storage_space.env.begin(write=False) as rtx:
            metadata_handlers[message["action"]](message, nodes[message["node"]], rtx=rtx, core=core_context)
        if message["action"] == "take TBM transaction":
          notify("core workload", "processing mempool tx")
          with storage_space.env.begin(write=False) as rtx:
            process_tbm_tx(message, rtx=rtx, core=core_context)
        if message["action"] == "give tip height":
          with storage_space.env.begin(write=False) as rtx:
            _ch=storage_space.blockchain.current_height(rtx=rtx)
            send_message(message["sender"], {"id": message["id"], "result": _ch})
          notify("blockchain height", _ch)      
      except DOSException as e:
        logger.info("DOS Exception %s"%str(e))
        #raise e #TODO send to NM
      except Exception as e:
        raise e

      if message["action"] == "give block info":
        notify("core workload", "reading block info")
        try:
          with storage_space.env.begin(write=False) as rtx:
            block_info = compose_block_info(message["block_num"], rtx=rtx)
          send_message(message["sender"], {"id": message["id"], "result":block_info})
        except Exception as e:
          send_message(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
      if message["action"] == "put arbitrary mining work" and is_benchmark:
        if not no_pow:
          raise Exception("`put arbitrary mining work` is only allowed for disabled pow checks")
        notify("core workload", "putting arbitrary mining work")
        message["nonce"] = b"\x00"*8
        message['partial_hash'] = list(storage_space.mempool_tx.work_block_assoc.inner_dict.keys())[-1] 
        message['action'] = "take mining work"
      if message["action"] in mining_operations: #getwork, gbt, submitblock, submitwork
        notify("core workload", "processing" + message["action"])
        with storage_space.env.begin(write=True) as wtx:
          mining_operations[message["action"]](message, wtx, core_context)
      if message["action"] == "set mining address" and is_benchmark:
        address = Address()
        address.deserialize_raw(message["address"])
        core_context.mining_address = address
      if message["action"] == "give synchronization status":
        with storage_space.env.begin(write=False) as rtx:
          our_height = storage_space.blockchain.current_height(rtx=rtx)
        best_known_header = storage_space.headers_manager.best_header_height
        try:
          best_advertised_height = max([nodes[node]["height"] for node in nodes if "height" in nodes[node]])
        except:
          best_advertised_height = None
        send_message(message["sender"], {"id": message["id"], 
                                         "result": {'height': our_height, 
                                                    'best_known_header': best_known_header,
                                                    'best_advertised_height': best_advertised_height}})
        notify("best header", best_known_header)
        notify("blockchain height", our_height)
        notify("best advertised height", best_advertised_height)

      if message["action"] == "add tx to mempool":
        notify("core workload", "processing local transaction")
        response = {"id": message["id"]}
        #deserialization
        try:
          ser_tx = message["tx"]
          tx = Transaction(txos_storage = storage_space.txos_storage, excesses_storage = storage_space.excesses_storage)
          with storage_space.env.begin(write=False) as rtx:            
            tx.deserialize(ser_tx, rtx)
            storage_space.mempool_tx.add_tx(tx, rtx=rtx)
            tx_skel = TransactionSkeleton(tx=tx)
            notify_all_nodes_about_tx(tx_skel.serialize(rich_format=True, max_size=40000), core_context, _except=[], mode=1)
          response['result']="generated"
        except Exception as e:
          response['result'] = 'error'
          response['error'] = str(e)
          logger.error("Problem in tx: %s"%str(e))
        send_message(message["sender"], response)


      #message from core_loop
      if message["action"] in download_status_checks: # txouts and blocks download status checks
        with storage_space.env.begin(write=True) as rtx:
          ret_mes = download_status_checks[message["action"]](message, rtx, core_context)
          if ret_mes:
            put_back_messages.append(ret_mes)
      if message["action"] == "take nodes list":
        for node in message["nodes"]:
          if not node in nodes: #Do not overwrite
            nodes[node]={"node":node}
        disconnected_nodes = []
        for existing_node in nodes:
          if not existing_node in message["nodes"]:
            disconnected_nodes.append(existing_node)
        for dn in disconnected_nodes:
          nodes.pop(dn)
        

      if message["action"] == "give nodes list reminder":
        _id = str(uuid4())
        send_to_network({"action":"give intrinsic nodes list", "sender":"Blockchain", "id":_id})
        requests[_id] = "give nodes list"
        put_back_messages.append({"action": "give nodes list reminder", "time":int(time())+3} )

      if message["action"] == "stop":
        logger.info("Core loop stops")
        return

      if message["action"] == "shutdown":
        initiator = message["sender"]
        logger.info("Shutdown initiated by %s"%initiator)
        for receiver in ['NetworkManager', 'Blockchain', 'RPCManager', 'Notifications', 'Wallet']:
          send_message(receiver, {"action":"stop", "sender":initiator})

      if message["action"] == "check requests cache":
        put_back_messages.append({"action": "check requests cache", "time":int(time())+5} )
        for k in requests_cache:
          if not len(requests_cache[k]):
            continue
          copy = list(set(requests_cache[k]))
          copy = sorted(copy, key= lambda x: requests_cache[k].index(x)) #preserve order of downloaded objects
          if k=="blocks":
            chunk_size=20
            while len(copy):
              request, copy = copy[:chunk_size], copy[chunk_size:]
              new_message = {"action": "check blocks download status", "block_hashes":request,
                            "already_asked_nodes": [], "id": str(uuid4()),
                            "time": -1 }
              message_queue.put(new_message)
            requests_cache[k] = []
          if k=="txouts":
            chunk_size=30
            while len(copy):
              request, copy = copy[:chunk_size], copy[chunk_size:]
              new_message = {"action": "check txouts download status", "txos_hashes": request,
                           "already_asked_nodes": [], "id": str(uuid4()),
                           "time": -1 }
              message_queue.put(new_message)
            requests_cache[k] = []

    for _message in put_back_messages:
      message_queue.put(_message)

    try:
      with storage_space.env.begin(write=True) as rtx:
        check_sync_status(nodes, rtx=rtx, core_context=core_context)
      try:
        best_advertised_height = max([nodes[node]["height"] for node in nodes if "height" in nodes[node]])
      except:
          best_advertised_height = None
      notify("best advertised height", best_advertised_height)
    except Exception as e:
      logger.error(e)


def look_forward(nodes, send_to_network, rtx):
  if storage_space.headers_manager.best_header_height < storage_space.blockchain.current_height(rtx=rtx)+100:
    for node_index in nodes:
      node = nodes[node_index]
      if ('height' in node) and (node['height']>storage_space.headers_manager.best_header_height):
        our_tip_hash = storage_space.blockchain.current_tip(rtx=rtx)
        send_find_common_root(storage_space.headers_storage.get(our_tip_hash,rtx=rtx), node['node'], send = send_to_network)
        break

def compose_block_info(block_num, rtx):
  ct = storage_space.blockchain.current_tip(rtx=rtx)
  ch = storage_space.blockchain.current_height(rtx=rtx)
  if block_num>ch:
    raise Exception("Unknown block")
  target_hash = ct
  if block_num<ch:
    target_hash = storage_space.headers_manager.find_ancestor_with_height(ct, block_num, rtx=rtx)
  block = storage_space.blocks_storage.get(target_hash, rtx=rtx)
  result = {'hash':target_hash.hex()}
  result['target']=float(block.header.target)
  result['supply']=block.header.supply
  result['timestamp']=block.header.timestamp
  result['height'] = block.header.height
  result['inputs']=[]
  result['outputs']=[]
  for i in block.transaction_skeleton.input_indexes:
    index=i.hex()
    address=storage_space.txos_storage.find(i, rtx=rtx).address.to_text()
    result['inputs'].append((index, address))
  for o in block.transaction_skeleton.output_indexes:
    index=o.hex()
    txo = storage_space.txos_storage.find(o, rtx=rtx)
    address=txo.address.to_text()
    lock_height = txo.lock_height
    relay_fee = txo.relay_fee
    version = txo.version
    amount = txo.value
    result['outputs'].append(({"output_id":index, "address":address, "lock_height":lock_height, "relay_fee":relay_fee, "version":version, "amount":amount}))
  return result
  
def check_sync_status(nodes, rtx, core_context):
  for node_index in nodes:
    node = nodes[node_index]
    if ((not "last_update" in node) or node["last_update"]+300<time()) and ((not "last_send" in node) or node["last_send"]+5<time()):
      #logger.info("\n node last_update %d was %.4f sec\n"%(("last_update" in node),   (time()-node["last_update"] if ("last_update" in node) else 0 )))
      send_tip_info(node_info = node, rtx=rtx, core=core_context)
