from leer.core.chains.headers_manager import HeadersManager
from leer.core.chains.blockchain import Blockchain
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.storage.blocks_storage import BlocksStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.utxo_index_storage import UTXOIndex
from leer.core.storage.mempool_tx import MempoolTx
from leer.core.primitives.block import Block
from leer.core.primitives.header import Header
from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Address
from leer.core.lubbadubdub.transaction import Transaction
from leer.core.hash.progpow import seed_hash as progpow_seed_hash
from leer.core.core_operations.sending_assets import notify_all_nodes_about_tx
from leer.core.core_operations.receiving_assets import process_new_headers, process_new_blocks, process_new_txos, process_tbm_tx
from leer.core.core_operations.sending_metadata import send_tip_info, notify_all_nodes_about_new_tip, send_find_common_root
from leer.core.core_operations.process_metadata import process_tip_info, process_find_common_root, process_find_common_root_response
from leer.core.core_operations.notifications import set_notify_wallet_hook, set_value_to_queue
from leer.core.core_operations.sending_requests import send_next_headers_request
from leer.core.core_operations.process_requests import process_blocks_request, process_next_headers_request, process_txos_request, process_tbm_tx_request
from leer.core.core_operations.handle_mining import assert_mining_conditions
from leer.core.core_operations.blockchain_initialization import init_blockchain, validate_state, set_ask_for_blocks_hook, set_ask_for_txouts_hook
from leer.core.core_operations.core_context import CoreContext
import base64
from leer.core.utils import DOSException, ObliviousDictionary
from leer.core.primitives.transaction_skeleton import TransactionSkeleton
from time import sleep, time
from uuid import uuid4

from leer.core.storage.storage_space import StorageSpace

from leer.syncer import Syncer
from leer.core.parameters.constants import serialized_genesis_block

from secp256k1_zkp import PrivateKey

import logging
from functools import partial
from ipaddress import ip_address

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
  message_queue = syncer.queues['Blockchain']
  init_storage_space(config)    

  nodes = {}
  requests_cache = {"blocks":[], "txouts":[]}
  set_ask_for_blocks_hook(storage_space.blockchain, requests_cache)
  set_ask_for_txouts_hook(storage_space.blocks_storage, requests_cache)
  if config['wallet']:
    set_notify_wallet_hook(storage_space.blockchain, syncer.queues['Wallet'])
  requests = {}
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

  mining_address = None #Will be initialised at first ask

  def send_message(destination, message):
    logger.debug("Sending message to %s:\t\t %s"%(str(destination), str(message)))
    if not 'id' in message:
      message['id'] = uuid4()
    if not 'sender' in message:
      message['sender'] = "Blockchain"
    syncer.queues[destination].put(message)

  def send_to_nm(message):
    send_message("NetworkManager", message)

  notify = partial(set_value_to_queue, syncer.queues["Notifications"], "Blockchain")

  core_context = CoreContext(storage_space, logger, nodes, notify, send_message)
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
              notify_all_nodes_about_new_tip(nodes, send_to_nm, storage_space=storage_space,\
                                             rtx=wtx, _except=[], _payload_except=[]) 
            look_forward(nodes, send_to_nm, rtx=wtx)       
        if message["action"] == "take the txos":
          notify("core workload", "processing new txos")
          with storage_space.env.begin(write=True) as wtx:
            process_new_txos(message, wtx=wtx, core=core_context)
            #After downloading new txos some blocs may become downloaded
            notify("blockchain height", storage_space.blockchain.current_height(rtx=wtx)) 
            look_forward(nodes, send_to_nm, rtx=wtx)          
        if message["action"] == "give blocks":
          notify("core workload", "giving blocks")
          with storage_space.env.begin(write=False) as rtx:
            process_blocks_request(message, rtx=rtx, core=core_context)
        if message["action"] == "give next headers":
          notify("core workload", "giving headers")
          with storage_space.env.begin(write=False) as rtx:
            process_next_headers_request(message, rtx=rtx, core=core_context)
        if message["action"] == "give txos":
          notify("core workload", "giving txos")
          with storage_space.env.begin(write=False) as rtx:
            process_txos_request(message, rtx=rtx, core=core_context)
        if message["action"] == "find common root":
          with storage_space.env.begin(write=False) as rtx:
            process_find_common_root(message, rtx, core_context)
        if message["action"] == "find common root response":
          with storage_space.env.begin(write=False) as rtx:
            process_find_common_root_response(message, nodes[message["node"]], rtx=rtx, core=core_context)
        if message["action"] == "give TBM transaction":
          notify("core workload", "giving mempool tx")
          with storage_space.env.begin(write=False) as rtx:
            process_tbm_tx_request(message, rtx, core_context)
        if message["action"] == "take TBM transaction":
          notify("core workload", "processing mempool tx")
          with storage_space.env.begin(write=False) as rtx:
            process_tbm_tx(message, rtx=rtx, core=core_context)
        if message["action"] == "give tip height":
          with storage_space.env.begin(write=False) as rtx:
            _ch=storage_space.blockchain.current_height(rtx=rtx)
            send_message(message["sender"], {"id": message["id"], "result": _ch})
          notify("blockchain height", _ch)      
        if message["action"] == "take tip info":
          if not message["node"] in nodes:
            nodes[message["node"]]={'node':message["node"]}
          with storage_space.env.begin(write=False) as rtx:
            process_tip_info(message, nodes[message["node"]], rtx=rtx, core=core_context)
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

      if message["action"] == "give block template":
        notify("core workload", "generating block template")
        try:
          if not mining_address:
            mining_address = get_new_address()
          with storage_space.env.begin(write=True) as wtx:
            assert_mining_conditions(config, nodes, storage_space, rtx=wtx)
            block = storage_space.mempool_tx.give_block_template(mining_address, wtx=wtx)
          ser_head = block.header.serialize()
          send_message(message["sender"], {"id": message["id"], "result":ser_head})
        except Exception as e:
          send_message(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
          logger.error("Can not generate block `%s`"%(str(e)), exc_info=True)
      if message["action"] == "give mining work":
        notify("core workload", "generating block template")
        try:
          if not mining_address:
            mining_address = get_new_address()
          with storage_space.env.begin(write=True) as wtx:
            assert_mining_conditions(config, nodes, storage_space, rtx=wtx)
            partial_header_hash, target, height = storage_space.mempool_tx.give_mining_work(mining_address, wtx=wtx)
          seed_hash = progpow_seed_hash(height)
          send_message(message["sender"], {"id": message["id"], 
              "result":{'partial_hash':partial_header_hash.hex(), 
                        'seed_hash':seed_hash.hex(),
                        'target':target.hex(),
                        'height':height
                       }})
        except Exception as e:
          send_message(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
          logger.error("Can not generate work `%s`"%(str(e)), exc_info=True)
      if message["action"] == "take solved block template":
        notify("core workload", "processing solved block")
        try:
          with storage_space.env.begin(write=True) as wtx:
            initial_tip = storage_space.blockchain.current_tip(rtx=wtx)
            header = Header()
            header.deserialize(message["solved template"])
            solved_block = storage_space.mempool_tx.get_block_by_header_solution(header)
            storage_space.headers_manager.add_header(solved_block.header, wtx=wtx)
            storage_space.headers_manager.context_validation(solved_block.header.hash, rtx=wtx)
            solved_block.non_context_verify(rtx=wtx)
            storage_space.blockchain.add_block(solved_block, wtx=wtx)
            after_tip = storage_space.blockchain.current_tip(rtx=wtx)
            our_height = storage_space.blockchain.current_height(rtx=wtx)
            best_known_header = storage_space.headers_manager.best_header_height
            if not after_tip==initial_tip:
              notify_all_nodes_about_new_tip(nodes, send_to_nm, storage_space=storage_space, rtx=wtx)
          send_message(message["sender"], {"id": message["id"], "result": "Accepted"})
          notify("best header", best_known_header)
          notify("blockchain height", our_height)
        except Exception as e:
          logger.error("Wrong block solution %s"%str(e))
          send_message(message["sender"], {"id": message["id"], "error": str(e), 'result':'error'})
      if message["action"] == "put arbitrary mining work" and is_benchmark:
        if not no_pow:
          raise Exception("`put arbitrary mining work` is only allowed for disabled pow checks")
        notify("core workload", "putting arbitrary mining work")
        message["nonce"] = b"\x00"*8
        message['partial_hash'] = list(storage_space.mempool_tx.work_block_assoc.inner_dict.keys())[-1] 
        message['action'] = "take mining work"
      if message["action"] == "take mining work":
        notify("core workload", "processing mining work")
        try:
          nonce, partial_work = message['nonce'], message['partial_hash']
          mp = storage_space.mempool_tx
          block_template =  mp.work_block_assoc[partial_work]
          block_template.header.nonce = nonce
          solved_block = block_template 
          header = solved_block.header
          with storage_space.env.begin(write=True) as wtx:
            if header.height <= storage_space.blockchain.current_height(rtx=wtx):
              send_message(message["sender"], {"id": message["id"], "result": "Stale"})
              logger.error("Stale work submitted: height %d"%(header.height))
              continue
            initial_tip = storage_space.blockchain.current_tip(rtx=wtx)
            storage_space.headers_manager.add_header(solved_block.header, wtx=wtx)
            storage_space.headers_manager.context_validation(solved_block.header.hash, rtx=wtx)
            solved_block.non_context_verify(rtx=wtx)
            storage_space.blockchain.add_block(solved_block, wtx=wtx)
            after_tip = storage_space.blockchain.current_tip(rtx=wtx)
            our_height = storage_space.blockchain.current_height(rtx=wtx)
            best_known_header = storage_space.headers_manager.best_header_height
            if not after_tip==initial_tip:
              notify_all_nodes_about_new_tip(nodes, send_to_nm, storage_space=storage_space, rtx=wtx)
          send_message(message["sender"], {"id": message["id"], "result": "Accepted"})
          notify("best header", best_known_header)
          notify("blockchain height", our_height)
        except Exception as e:
          logger.error("Wrong submitted work %s"%str(e))
          send_message(message["sender"], {"id": message["id"], "error": str(e), 'result':'error'})
      if message["action"] == "set mining address" and is_benchmark:
        address = Address()
        address.deserialize_raw(message["address"])
        mining_address = address
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
            notify_all_nodes_about_tx(tx_skel.serialize(rich_format=True, max_size=40000), nodes, send_to_nm, _except=[], mode=1)
          response['result']="generated"
        except Exception as e:
          response['result'] = 'error'
          response['error'] = str(e)
          logger.error("Problem in tx: %s"%str(e))
        send_message(message["sender"], response)


      #message from core_loop
      if message["action"] == "check txouts download status":
        txos = message["txos_hashes"]
        to_be_downloaded = []
        with storage_space.env.begin(write=True) as rtx:
          for txo in txos:
            if not storage_space.txos_storage.known(txo, rtx=rtx):
              to_be_downloaded.append(txo)
        if not to_be_downloaded:
          continue #We are good, txouts are already downloaded
        already_asked_nodes = message["already_asked_nodes"]
        asked = False
        for node_params in nodes:
          node = nodes[node_params]
          if node in already_asked_nodes:
            continue
          already_asked_nodes += [node]
          send_to_nm({"action":"give txos",
                                               "txos_hashes": b"".join(to_be_downloaded), 
                                               "num": len(to_be_downloaded), 
                                               "id":str(uuid4()), "node":node_params })
          new_message = {"action": "check txouts download status", "txos_hashes":to_be_downloaded,
                         "already_asked_nodes": already_asked_nodes, "id": str(uuid4()),
                         "time": int(time()+30) }
          asked = True
          put_back_messages.append(new_message)
          break
        if not asked: #We already asked all applicable nodes
          message["time"]=int(time())+600
          message["already_asked_nodes"] = []
          put_back_messages.append(message) # we will try to ask again in an hour

      #message from core_loop
      if message["action"] == "check blocks download status":
        block_hashes = message["block_hashes"]
        to_be_downloaded = []
        lowest_height=1e10
        with storage_space.env.begin(write=True) as rtx:
          for block_hash in block_hashes:
            if storage_space.blocks_storage.has(block_hash, rtx=rtx):
              continue #We are good, block already downloaded          
            if not block_hash in storage_space.blockchain.awaited_blocks:
              continue #For some reason we don't need this block anymore
            to_be_downloaded.append(block_hash)
            block_height = storage_space.headers_storage.get(block_hash, rtx=rtx).height
            if block_height<lowest_height:
              lowest_height = block_height
        if not len(to_be_downloaded):
          continue #We are good, blocks are already downloaded
        already_asked_nodes = message["already_asked_nodes"]
        asked = False
        for node_params in nodes:
          node = nodes[node_params]
          if node in already_asked_nodes:
            continue
          if (not "height" in node) or node["height"] < lowest_height:
            continue
          already_asked_nodes += [node]
          send_to_nm({"action":"give blocks",  "block_hashes": bytes(b"".join(block_hashes)), 'num': len(block_hashes), "id":str(uuid4()), "node":node_params })
          new_message = {"action": "check blocks download status", "block_hashes":to_be_downloaded,
                         "already_asked_nodes": already_asked_nodes, "id": str(uuid4()),
                         "time": int(time()+30) }
          asked = True
          put_back_messages.append(new_message)
          break
        if not asked: #We already asked all applicable nodes
          message["time"]=int(time())+600
          message["already_asked_nodes"] = []
          put_back_messages.append(message) # we will try to ask again in an hour


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
        send_to_nm({"action":"give intrinsic nodes list", "sender":"Blockchain", "id":_id})
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
        check_sync_status(nodes, send_to_nm, rtx=rtx)
      try:
        best_advertised_height = max([nodes[node]["height"] for node in nodes if "height" in nodes[node]])
      except:
          best_advertised_height = None
      notify("best advertised height", best_advertised_height)
    except Exception as e:
      logger.error(e)


def look_forward(nodes, send_to_nm, rtx):
  if storage_space.headers_manager.best_header_height < storage_space.blockchain.current_height(rtx=rtx)+100:
    for node_index in nodes:
      node = nodes[node_index]
      if ('height' in node) and (node['height']>storage_space.headers_manager.best_header_height):
        our_tip_hash = storage_space.blockchain.current_tip(rtx=rtx)
        send_find_common_root(storage_space.headers_storage.get(our_tip_hash,rtx=rtx), node['node'], send = send_to_nm)
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
  
def check_sync_status(nodes, send, rtx):
  for node_index in nodes:
    node = nodes[node_index]
    if ((not "last_update" in node) or node["last_update"]+300<time()) and ((not "last_send" in node) or node["last_send"]+5<time()):
      #logger.info("\n node last_update %d was %.4f sec\n"%(("last_update" in node),   (time()-node["last_update"] if ("last_update" in node) else 0 )))
      send_tip_info(node_info = node, send=send, storage_space=storage_space, rtx=rtx)
