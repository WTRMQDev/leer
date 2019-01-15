from leer.core.chains.headers_manager import HeadersManager
from leer.core.chains.blockchain import Blockchain
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.storage.blocks_storage import BlocksStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.utxo_index_storage import UTXOIndex
from leer.core.storage.mempool_tx import MempoolTx
#from leer.core.storage.key_manager import KeyManagerClass
from leer.core.primitives.block import Block
from leer.core.primitives.header import Header
from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Address
from leer.core.lubbadubdub.transaction import Transaction
import base64
from leer.core.utils import DOSException
from leer.core.primitives.transaction_skeleton import TransactionSkeleton
from time import sleep, time
from uuid import uuid4

from leer.core.storage.storage_space import StorageSpace
from leer.core.storage.default_paths import base_dir as default_base_dir, calc_paths

from leer.syncer import Syncer
from leer.core.parameters.constants import serialized_genesis_block

from secp256k1_zkp import PrivateKey

import logging
from functools import partial
from ipaddress import ip_address

logger = logging.getLogger("core_loop")

storage_space = None

def init_blockchain(wtx):
  '''
    If blockchain is empty this function will set genesis.
  '''
  genesis = Block(storage_space = storage_space)
  genesis.deserialize(serialized_genesis_block)
  storage_space.headers_manager.set_genesis(genesis.header, wtx=wtx)
  if storage_space.blockchain.current_height(rtx=wtx)<0:
    storage_space.headers_manager.context_validation(genesis.header.hash, rtx=wtx)
    genesis.non_context_verify(rtx=wtx)
    storage_space.blockchain.add_block(genesis, wtx=wtx)
  else:
    storage_space.headers_manager.best_tip = (storage_space.blockchain.current_tip(rtx=wtx), storage_space.blockchain.current_height(rtx=wtx) )
    logger.info("Best header tip from blockchain state %d"%storage_space.headers_manager.best_tip[1])
    #greedy search
    current_tip = storage_space.headers_manager.best_tip[0]
    while True:
      try:
        header = storage_space.headers_storage.get(current_tip, rtx=wtx)
      except KeyError:
        break
      new_current_tip=current_tip
      if len(header.descendants):
        for d in header.descendants:
          dh = storage_space.headers_storage.get(d, rtx=wtx)
          if not dh.invalid:
            new_current_tip = d
            break
      if not new_current_tip == current_tip:
        current_tip=new_current_tip
      else:
        break
    storage_space.headers_manager.best_tip = (current_tip, storage_space.headers_storage.get(current_tip, rtx=wtx).height)
    logger.info("Best header tip after greedy search %d"%storage_space.headers_manager.best_tip[1])


def validate_state(storage_space, rtx):
  '''
    Since writes to different storages (excesses, blocks, txos etc) 
    are not transactional for now, it is possible that previous halt was
    in between of writes. In this case state is (irreversibly) screwed. 
    Cheking it here.
  '''
  if storage_space.blockchain.current_height(rtx=rtx)<1:
    return
  tip = storage_space.blockchain.current_tip(rtx=rtx)
  header = storage_space.headers_storage.get(tip, rtx=rtx)
  last_block_merkles = header.merkles
  state_merkles = [storage_space.txos_storage.confirmed.get_commitment_root(rtx=rtx), \
                   storage_space.txos_storage.confirmed.get_txo_root(rtx=rtx), \
                   storage_space.excesses_storage.get_root(rtx=rtx)]
  try:
    assert last_block_merkles == state_merkles
  except Exception as e:
    logger.error("State is screwed: state merkles are not coinside with last applyed block merkles. Consider full resync.\n %s\n %s\n Block num: %d"%(last_block_merkles, state_merkles, header.height))
    raise e
  

def init_storage_space(config):
  global storage_space
  _path = config["location"]["basedir"]
  storage_space=StorageSpace(_path)
  '''_paths = {}
  _paths["txo_storage_path"], _paths[ "txo_storage_path"], _paths[ "excesses_storage_path"],\
  _paths[ "headers_storage_path"], _paths[ "blocks_storage_path"], _paths[ "wallet_path"],\
  _paths[ "key_manager_path"], _paths[ "utxo_index_path"] = calc_paths(default_base_dir)
  if "location" in config:
    if "basedir" in config["location"]:
      basedir = config["location"]["basedir"]
      _paths["txo_storage_path"], _paths[ "txo_storage_path"],\
      _paths[ "excesses_storage_path"], _paths[ "headers_storage_path"],\
      _paths[ "blocks_storage_path"], _paths[ "wallet_path"],\
      _paths[ "key_manager_path"], _paths[ "utxo_index_path"] = calc_paths(basedir)
    for _path in _paths:
      if _path in config["location"]:
        _paths[_path] = config["location"][_path]
  ''' 
  with storage_space.env.begin(write=True) as wtx:
    hs = HeadersStorage(storage_space, wtx=wtx)
    hm = HeadersManager(storage_space)
    bs = BlocksStorage(storage_space, wtx=wtx)
    es = ExcessesStorage(storage_space, wtx=wtx)
    ts = TXOsStorage(storage_space, wtx=wtx)
    bc = Blockchain(storage_space)
    mptx = MempoolTx(storage_space)
    utxoi = UTXOIndex(storage_space, wtx=wtx)
    #km = KeyManagerClass(path = _paths["key_manager_path"]) #TODO km should be initialised in wallet process
    #mptx.set_key_manager(km)
    init_blockchain(wtx=wtx)
    validate_state(storage_space, rtx=wtx)
  

def set_ask_for_blocks_hook(blockchain, message_queue):
  def f(block_hashes):
    if not isinstance(block_hashes, list):
      block_hashes=[block_hashes] #There is only one block
    new_message = {"action": "check blocks download status", "block_hashes":block_hashes,
                         "already_asked_nodes": [], "id": str(uuid4()),
                         "time": -1 }
    message_queue.put(new_message)
  
  blockchain.ask_for_blocks_hook = f

def set_ask_for_txouts_hook(block_storage, message_queue):
  def f(txouts):
    new_message = {"action": "check txouts download status", "txos_hashes": txouts,
                         "already_asked_nodes": [], "id": str(uuid4()),
                         "time": -1 }
    message_queue.put(new_message)
  
  block_storage.ask_for_txouts_hook = f

def is_ip_port_array(x):
  res = True
  for _ in x:
    try:
      address, port = ip_address(_[0]), int(_[1])
    except:
      res=False
      break
  return res


def set_notify_wallet_hook(blockchain, wallet_message_queue):
    def notify_wallet(reason, *args):
      message={'sender':"Blockchain"}
      #no id: notification
      if reason == "apply":
        message['action'] = "process new block"
        message['tx'] = args[0].serialize()
        message['height'] = args[1]      
      elif reason == "rollback":
        message['action'] = "process rollback"
        message['rollback_object'] = args[0].serialize()
        message['block_height'] = args[1]
      else:
        pass
      wallet_message_queue.put(message)
    storage_space.blockchain.notify_wallet = notify_wallet 

def core_loop(syncer, config):
  message_queue = syncer.queues['Blockchain']
  init_storage_space(config)    

  nodes = {}
  set_ask_for_blocks_hook(storage_space.blockchain, message_queue)
  set_ask_for_txouts_hook(storage_space.blocks_storage, message_queue)
  if config['wallet']:
    set_notify_wallet_hook(storage_space.blockchain, syncer.queues['Wallet'])
  requests = {}
  message_queue.put({"action":"give nodes list reminder"})

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
    if not 'id' in message:
      message['id'] = uuid4()
    if not 'sender' in message:
      message['sender'] = "Blockchain"
    syncer.queues[destination].put(message)

  def send_to_nm(message):
    send_message("NetworkManager", message)

  notification_cache = {}
  def notify(key, value, timestamp=None):
    if (key in notification_cache) and (notification_cache[key]['value'] == value) and (time()-notification_cache[key]['timestamp'])<5:
      return #Do not spam notifications with the same values
    message = {}
    message['id'] = uuid4()
    message['sender'] = "Blockchain"
    if not timestamp:
      timestamp = time()
    message['time'] = timestamp
    message['action']="set"
    message['key']=key
    message['value']=value
    syncer.queues["Notifications"].put(message)
    notification_cache[key] = {'value':value, 'timestamp':timestamp}

  logger.debug("Start of core loop")
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
         (('action' in message) and message['action']=="take nodes list") or \
         (('result' in message) and is_ip_port_array(message['result'])):
        logger.debug("Processing message %s"%message)
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
            process_new_headers(message, nodes[message["node"]], send_message, wtx, notify=partial(notify, "best header"))
          notify("best header", storage_space.headers_manager.best_header_height)         
        if message["action"] == "take the blocks":
          notify("core workload", "processing new blocks")
          with storage_space.env.begin(write=True) as wtx:
            initial_tip = storage_space.blockchain.current_tip(rtx=wtx)
            process_new_blocks(message, notify=partial(notify, "blockchain height"), wtx=wtx)
            after_tip = storage_space.blockchain.current_tip(rtx=wtx)
            notify("blockchain height", storage_space.blockchain.current_height(rtx=wtx))         
            if not after_tip==initial_tip:
              notify_all_nodes_about_new_tip(nodes, send_to_nm, rtx=wtx) 
            look_forward(nodes, send_to_nm, rtx=wtx)       
        if message["action"] == "take the txos":
          notify("core workload", "processing new txos")
          with storage_space.env.begin(write=True) as wtx:
            process_new_txos(message, wtx=wtx)
            #After downloading new txos some blocs may become downloaded
            notify("blockchain height", storage_space.blockchain.current_height(rtx=wtx)) 
            look_forward(nodes, send_to_nm, rtx=wtx)          
        if message["action"] == "give blocks":
          notify("core workload", "giving blocks")
          with storage_space.env.begin(write=False) as rtx:
            process_blocks_request(message, send_message, rtx=rtx)
        if message["action"] == "give next headers":
          notify("core workload", "giving headers")
          with storage_space.env.begin(write=False) as rtx:
            process_next_headers_request(message, send_message, rtx=rtx)
        if message["action"] == "give txos":
          notify("core workload", "giving txos")
          with storage_space.env.begin(write=False) as rtx:
            process_txos_request(message, send_message, rtx=rtx)
        if message["action"] == "find common root":
          with storage_space.env.begin(write=False) as rtx:
            process_find_common_root(message, send_message, rtx)
        if message["action"] == "find common root response":
          with storage_space.env.begin(write=False) as rtx:
            process_find_common_root_reponse(message, nodes[message["node"]], send_message, rtx=rtx)
        if message["action"] == "give TBM transaction":
          notify("core workload", "giving mempool tx")
          with storage_space.env.begin(write=False) as rtx:
            process_tbm_tx_request(message, send_message, rtx)
        if message["action"] == "take TBM transaction":
          notify("core workload", "processing mempool tx")
          with storage_space.env.begin(write=False) as rtx:
            process_tbm_tx(message, send_to_nm, nodes, rtx=rtx)
        if message["action"] == "give tip height":
          with storage_space.env.begin(write=False) as rtx:
            _ch=storage_space.blockchain.current_height(rtx=rtx)
            send_message(message["sender"], {"id": message["id"], "result": _ch})
          notify("blockchain height", _ch)      
        if message["action"] == "take tip info":
          if not message["node"] in nodes:
            nodes[message["node"]]={'node':message["node"]}
          with storage_space.env.begin(write=False) as rtx:
            process_tip_info(message, nodes[message["node"]], rtx=rtx, send=send_to_nm)
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
          address = get_new_address()
          with storage_space.env.begin(write=True) as wtx:
            block = storage_space.mempool_tx.give_block_template(address, wtx=wtx)
          ser_head = block.header.serialize()
          send_message(message["sender"], {"id": message["id"], "result":ser_head})
        except Exception as e:
          send_message(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
          self.logger.error("Can not generate block `%s`"%(str(e)), exc_info=True)
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
              notify_all_nodes_about_new_tip(nodes, send_to_nm, rtx=wtx)
          send_message(message["sender"], {"id": message["id"], "result": "Accepted"})
          notify("best header", best_known_header)
          notify("blockchain height", our_height)
        except Exception as e:
          logger.error("Wrong block solution %s"%str(e))
          send_message(message["sender"], {"id": message["id"], "error": str(e)})

      '''if message["action"] == "get confirmed balance stats": #TODO Move to wallet
        notify("core workload", "retrieving balance")
        if storage_space.mempool_tx.key_manager:
          stats = storage_space.mempool_tx.key_manager.get_confirmed_balance_stats( 
                     storage_space.utxo_index,
                     storage_space.txos_storage,
                     storage_space.blockchain.current_height)
          send_message(message["sender"], {"id": message["id"], "result":stats})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "get confirmed balance list": #TODO Move to wallet
        notify("core workload", "retrieving balance")
        if storage_space.mempool_tx.key_manager:
          _list = storage_space.mempool_tx.key_manager.get_confirmed_balance_list( 
                     storage_space.utxo_index,
                     storage_space.txos_storage,
                     storage_space.blockchain.current_height)
          send_message(message["sender"], {"id": message["id"], "result":_list})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "give new address": #TODO Move to wallet
        notify("core workload", "retrieving new address")
        if storage_space.mempool_tx.key_manager:
          texted_address = storage_space.mempool_tx.key_manager.new_address().to_text()
          send_message(message["sender"], {"id": message["id"], "result": texted_address})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "give private key": #TODO Move to wallet
        if storage_space.mempool_tx.key_manager:
          km = storage_space.mempool_tx.key_manager
          a=Address()
          a.from_text(message["address"])
          serialized_pk = km.priv_by_address(a).serialize()
          send_message(message["sender"], {"id": message["id"], "result": serialized_pk})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "take private key": #TODO Move to wallet
        if storage_space.mempool_tx.key_manager:
          km = storage_space.mempool_tx.key_manager
          pk=PrivateKey()
          pk.deserialize(message['privkey'])
          km.add_privkey(pk)
          send_message(message["sender"], {"id": message["id"], "result": "imported"})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})'''

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


      if message["action"] == "generate tx by tx template": #TODO Move to wallet
        notify("core workload", "generating transactions")
        response = {"id": message["id"]}
        try:
          tx_template = message["tx_template"]
          #Deserialization        
          destination_address, change_address = Address(), Address()
          destination_address.deserialize_raw(tx_template['address'])
          change_address.deserialize_raw(tx_template['change address'])
          tx_template['address'], tx_template['change address'] = destination_address, change_address
          for pub in tx_template['priv_by_pub']:
            tx_template['priv_by_pub'][pub] =  PrivateKey(tx_template['priv_by_pub'][pub], raw=True)
        except Exception as e:
          response['result'] = 'error'
          response['error'] = str(e)
          logger.error("Problem in tx_template: %s"%str(e))
        try: #Tx generation
          with storage_space.env.begin(write=True) as rtx:
            tx = Transaction(txos_storage = storage_space.txos_storage, excesses_storage = storage_space.excesses_storage)
            for utxo_index in tx_template['utxos']:
              utxo = storage_space.txos_storage.confirmed.get(utxo_index, rtx=rtx)
              tx.push_input(utxo)
            tx.add_destination( (tx_template["address"], tx_template["value"]) )
            tx.generate_new(priv_data=tx_template, rtx=rtx,
                        change_address = tx_template['change address'],
                        relay_fee_per_kb=storage_space.mempool_tx.fee_policy_checker.relay_fee_per_kb)
            tx.verify(rtx=rtx)
            storage_space.mempool_tx.add_tx(tx, rtx=rtx)
            tx_skel = TransactionSkeleton(tx=tx)
            notify_all_nodes_about_tx(tx_skel.serialize(rich_format=True, max_size=40000), nodes, send_to_nm, _except=[], mode=1)
          response['result']="generated"
        except Exception as e:
          response['result'] = 'error'
          response['error'] = str(e)
          logger.error("Cannot generate tx by template: %s"%str(e))
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
                         "time": int(time()+300) }
          asked = True
          put_back_messages.append(new_message)
          break
        if not asked: #We already asked all applicable nodes
          message["time"]=int(time())+3600
          message["already_asked_nodes"] = []
          put_back_messages.append(message) # we will try to ask again in an hour

      #message from core_loop
      if message["action"] == "check blocks download status":
        #TODO download many blocks at once
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
            if storage_space.headers_storage.get(block_hash, rtx=rtx).height<lowest_height:
              lowest_height = storage_space.headers_storage.get(block_hash, rtx=rtx).height
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
                         "time": int(time()+300) }
          asked = True
          put_back_messages.append(new_message)
          break
        if not asked: #We already asked all applicable nodes
          message["time"]=int(time())+3600
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
        send_to_nm({"action":"give nodes list", "sender":"Blockchain", "id":_id})
        requests[_id] = "give nodes list"
        put_back_messages.append({"action": "give nodes list reminder", "time":int(time())+3} )

      if message["action"] == "stop":
        logger.info("Core loop stops")
        return

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




def process_new_headers(message, node_info, send_message, wtx, notify=None):
  dupplication_header_dos = False #TODO grammatical typo?
  try:
    serialized_headers = message["headers"]
    num = message["num"]
    header = None
    for i in range(num):
      header = Header()
      serialized_headers = header.deserialize_raw(serialized_headers)
      if not storage_space.headers_storage.has(header.hash, rtx=wtx):
        storage_space.headers_manager.add_header(header, wtx=wtx)
        if notify and not i%20:
          notify(storage_space.headers_manager.best_header_height)
      else:
        dupplication_header_dos = True
      if ("common_root" in node_info) and ("long_reorganization" in node_info["common_root"]):
        logger.info("node_info ")
        logger.info(node_info)
        logger.info(header)
        logger.info(header.height)
        if ("common_root" in node_info) and ("long_reorganization" in node_info["common_root"]) and \
           node_info["common_root"]["long_reorganization"]==header.height:
           request_num = min(256, node_info["height"]-storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=wtx).height) 
           logger.info(request_num)
           send_next_headers_request(header.hash, 
                                request_num,
                                message["node"], send = partial(send_message, "NetworkManager") )
           if node_info["height"]-header.height>request_num:
             node_info["common_root"]["long_reorganization"] = header.height+request_num
           else:
             node_info["common_root"].pop("long_reorganization", None) 
    storage_space.blockchain.update(wtx=wtx, reason="downloaded new headers")
  except Exception as e:
    raise e
    raise DOSException() #TODO add info

def process_new_blocks(message, wtx, notify=None):
  try:
    serialized_blocks = message["blocks"]
    num = message["num"]
    prev_not = time()
    for i in range(num):
      block = Block(storage_space=storage_space)
      serialized_blocks = block.deserialize_raw(serialized_blocks)
      storage_space.blockchain.add_block(block, wtx=wtx, no_update=True)
      if notify:
        if time()-prev_not>15:
          storage_space.blockchain.update(wtx=wtx, reason="downloaded new blocks")
          notify(storage_space.blockchain.current_height(rtx=wtx))
          prev_not = time()
    storage_space.blockchain.update(wtx=wtx, reason="downloaded new blocks")
  except Exception as e:
    raise DOSException() #TODO add info

def process_new_txos(message, wtx):
  try:
    serialized_utxos = bytes(message["txos"])
    txos_hashes = bytes(message["txos_hashes"])
    num = message["num"]
    #txos_hashes = [txos_hashes[i*65:(i+1)*65)] for i in range(0,num)]
    txos_lengths = message["txos_lengths"]
    #TODO we should use txos_hashes and txos_lengths to proccess only unknown txos
    for i in range(num):
      utxo = IOput()
      serialized_utxos = utxo.deserialize_raw(serialized_utxos)
      storage_space.txos_storage.mempool[utxo.serialized_index]=utxo
    storage_space.blockchain.update(wtx=wtx, reason="downloaded new txos")
  except Exception as e:
    raise DOSException() #TODO add info

def process_blocks_request(message, send_message, rtx):
  num = message["num"]
  _hashes = message["block_hashes"]
  _hashes = [_hashes[i*32:(i+1)*32] for i in range(num)]
  serialized_blocks = b""
  blocks_num=0
  for _hash in _hashes:
    if not storage_space.blocks_storage.has(_hash, rtx=rtx):
      continue
    try:
      serialized_block = storage_space.blocks_storage.get(_hash, rtx=rtx).serialize(rtx=rtx, rich_block_format=True)
    except KeyError:
      #Some outputs were pruned
      serialized_block = storage_space.blocks_storage.get(_hash, rtx=rtx).serialize(rtx=rtx, rich_block_format=False)
    if len(serialized_blocks)+len(serialized_block)<60000:
      serialized_blocks+=serialized_block
      blocks_num +=1
    else:
        send_message(message['sender'], {"action":"take the blocks", "num":blocks_num, 
                                              "blocks":serialized_blocks, "id":message['id'],
                                              "node":message["node"]})
        serialized_blocks=serialized_block
        blocks_num =1
  send_message(message['sender'], {"action":"take the blocks", "num":blocks_num, 
                                              "blocks":serialized_blocks, "id":message['id'],
                                              "node":message["node"]})


def send_next_headers_request(from_hash, num, node, send):
  send({"action":"give next headers", "num":num, "from":from_hash, 
                                       "id" : str(uuid4()), "node": node  })

def process_next_headers_request(message, send_message, rtx):
  from_hash = message["from"]
  num = message["num"]
  num = 1024 if num>1024 else num
  try:
    header = storage_space.headers_storage.get(from_hash, rtx=rtx)
  except KeyError:
    return #unknown hash
  current_tip  = storage_space.blockchain.current_tip(rtx=rtx)
  current_height  = storage_space.blockchain.current_height(rtx=rtx)
  if not storage_space.headers_manager.find_ancestor_with_height(current_tip, header.height, rtx=rtx) == from_hash:
    return
    ''' Counter-node is not in our main chain. 
        We will not feed it (actually we just are not sure what we should send here)
    '''
  last_to_send_height = header.height+num
  last_to_send_height = current_height if last_to_send_height>current_height else last_to_send_height
  last_to_send = storage_space.headers_manager.find_ancestor_with_height(current_tip, last_to_send_height, rtx=rtx)
  headers_hashes = storage_space.headers_manager.get_subchain(from_hash, last_to_send, rtx=rtx)

  serialized_headers = b""
  headers_num=0
  for _hash in headers_hashes:
    if not storage_space.headers_storage.has(_hash, rtx=rtx):
      continue
    serialized_header = storage_space.headers_storage.get(_hash, rtx=rtx).serialize()
    if len(serialized_headers)+len(serialized_header)<60000:
      serialized_headers+=serialized_header
      headers_num +=1
    else:
      send_message(message['sender'], {"action":"take the headers", "num": headers_num, 
                                            "headers":serialized_headers, "id":message['id'],
                                            "node": message["node"] })
      serialized_headers=serialized_header
      headers_num =1
  if headers_num:
    send_message(message['sender'], {"action":"take the headers", "num": headers_num, 
                                            "headers":serialized_headers, "id":message['id'],
                                            "node": message["node"] })

def process_txos_request(message, send_message, rtx):
  num = message["num"]
  _hashes = message["txos_hashes"]
  _hashes = [bytes(_hashes[i*65:(i+1)*65]) for i in range(num)]
  serialized_txos = b""
  txos_num=0
  txos_hashes = b""
  txos_lengths = b""
  for _hash in _hashes:
    try:
      serialized_txo = storage_space.txos_storage.find_serialized(_hash, rtx=rtx)
    except KeyError:
      continue
    if len(serialized_txos)+len(serialized_txo)<60000:
      serialized_txos+=serialized_txo
      txos_num +=1
      txos_hashes += _hash
      txos_lengths += len(serialized_txo).to_bytes(2,"big")
    else:
      send_message(message['sender'], {"action":"take the txos", 
                                            "num":txos_num, "txos":serialized_txos, 
                                            "txos_hashes": txos_hashes, "txos_lengths": txos_lengths,
                                            "id":message['id'], 'node': message["node"] })
      serialized_txos=serialized_txo
      txos_num =1
  if txos_num:
    send_message(message['sender'], {"action":"take the txos", 
                                            "num":txos_num, "txos":serialized_txos, 
                                            "txos_hashes": txos_hashes, "txos_lengths": txos_lengths,
                                            "id":message['id'], 'node': message["node"] })

def send_tip_info(node_info, send, rtx, our_tip_hash=None ):
  our_height = storage_space.blockchain.current_height(rtx=rtx)
  our_tip_hash = our_tip_hash if our_tip_hash else storage_space.blockchain.current_tip(rtx=rtx)
  our_prev_hash = storage_space.headers_storage.get(our_tip_hash, rtx=rtx).prev
  our_td = storage_space.headers_storage.get(our_tip_hash, rtx=rtx).total_difficulty

  send({"action":"take tip info", "height":our_height, "tip":our_tip_hash, "prev_hash":our_prev_hash, "total_difficulty":our_td, "id":uuid4(), "node": node_info["node"] })
  node_info["sent_tip"]=our_tip_hash
  node_info["last_send"] = time()

def process_tip_info(message, node_info, send, rtx):
  # another node (referenced as counter-Node below) asks us for our best tip and also provides us information about his
  node = message["node"]
  height = message["height"]
  tip_hash = message["tip"]
  prev_hash = message["prev_hash"]
  total_difficulty = message["total_difficulty"]

  our_tip_hash = storage_space.blockchain.current_tip(rtx=rtx)

  if (not "sent_tip" in node_info) or \
     (not node_info["sent_tip"]==our_tip_hash) or \
     (not "last_send" in node_info) or \
     (time() - node_info["last_send"]>300):
    send_tip_info(node_info=node_info, send = send, our_tip_hash=our_tip_hash, rtx=rtx)
  node_info.update({"node":node, "height":height, "tip_hash":tip_hash, 
                    "prev_hash":prev_hash, "total_difficulty":total_difficulty, 
                    "last_update":time()})
  if (height > storage_space.blockchain.current_height(rtx=rtx)) and (total_difficulty > storage_space.headers_storage.get(our_tip_hash, rtx=rtx).total_difficulty):
    #Now there are two options: better headers are unknown or headers are known, but blocks are unknown or bad
    if not storage_space.headers_storage.has(tip_hash, rtx=rtx):
      send_find_common_root(storage_space.headers_storage.get(our_tip_hash, rtx=rtx), node, send = send)
      #TODO check prev hash first
    else: #header is known
      header = storage_space.headers_storage.get(tip_hash, rtx=rtx)
      #TODO do we need to check for connection to genesis?
      common_root =  storage_space.headers_manager.find_bifurcation_point(tip_hash, our_tip_hash, rtx=rtx)
      if header.invalid:
        return #Nothing interesting, counter-node is on wrong chain
      if storage_space.blocks_storage.has(tip_hash, rtx=rtx):
        if storage_space.blocks_storage.get(tip_hash, rtx=rtx).invalid:
          return #Nothing interesting, counter-node is on wrong chain
      #download blocks
      blocks_to_download = []
      for _block_hash in storage_space.headers_manager.get_subchain(common_root, tip_hash, rtx=rtx):
        if not storage_space.blocks_storage.has(_block_hash, rtx=rtx):
          blocks_to_download.append(_block_hash)
        else:
          storage_space.blocks_storage.is_block_downloaded(_block_hash, rtx=rtx)
        if len(blocks_to_download)*32>40000: #Too big for one message
          break
      if len(blocks_to_download):
        send({"action":"give blocks",  
            "block_hashes": b"".join(blocks_to_download),
            'num': len(blocks_to_download), "id":str(uuid4()), "node":message["node"] })
      

def send_find_common_root(from_header, node, send):
  send(
    {"action":"find common root", "serialized_header": from_header.serialize(), 
     "id":str(uuid4()), 
     "node": node })


UNKNOWN, INFORK, MAINCHAIN, ISOLATED = 0, 1, 2, 3

def process_find_common_root(message, send_message, rtx):
  try:
    serialized_header = message["serialized_header"]
    header = Header()
    header.deserialize_raw(serialized_header)
  except:
    raise DOSException()
  result = []
  for pointer in [header.hash]+header.popow.pointers:
    if not storage_space.headers_storage.has(pointer, rtx=rtx):
      result.append(UNKNOWN)
      continue
    ph = storage_space.headers_storage.get(pointer, rtx=rtx)
    if not ph.connected_to_genesis:
      result.append(ISOLATED)
      continue
    if storage_space.headers_manager.find_ancestor_with_height(storage_space.blockchain.current_tip(rtx=rtx), ph.height, rtx=rtx) == pointer:
      result.append(MAINCHAIN)
      continue
    result.append(INFORK)

  send_message(message['sender'], \
     {"action":"find common root response", "header_hash":header.hash,
      "flags_num": len(result), 
      "known_headers": b"".join([i.to_bytes(1,"big") for i in result]), 
      "id":message['id'], "node": message["node"] })

def process_find_common_root_reponse(message, node_info, send_message, rtx):
  logger.info("Processing of fcrr")
  header_hash = message["header_hash"]
  result = [int(i) for i in message["known_headers"]]
  try:
    header = storage_space.headers_storage.get(header_hash, rtx=rtx)
  except KeyError:
    raise DOSException()
  root_found = False
  if not "common_root" in node_info:
    node_info["common_root"]={}

  for index, pointer in enumerate([header.hash]+header.popow.pointers):
    if result[index] in [MAINCHAIN, INFORK]:
        node_info["common_root"]["best_mutual"]=pointer
        best_mutual_height = storage_space.headers_storage.get(node_info["common_root"]["best_mutual"], rtx=rtx).height
        break
    else:
      node_info["common_root"]["worst_nonmutual"]=pointer
  if (not "worst_nonmutual" in node_info["common_root"]):
    #we are behind
    node_info["common_root"]["root"] = header_hash
    root_found = True
    node_info["common_root"].pop("try_num", None)
  if (not "best_mutual" in node_info["common_root"]):
    # genesis should always be mutual
    return
  logger.info(node_info)
  if not root_found:
    h1,h2 = storage_space.headers_storage.get(node_info["common_root"]["worst_nonmutual"], rtx=rtx).height,\
            storage_space.headers_storage.get(node_info["common_root"]["best_mutual"], rtx=rtx).height
    if h1==h2+1:
      root_found = True
      node_info["common_root"].pop("try_num", None)
      node_info["common_root"]["root"] = node_info["common_root"]["best_mutual"]
    else:
      if not "try_num" in node_info["common_root"]:
        node_info["common_root"]["try_num"]=0
      node_info["common_root"]["try_num"]+=1
      send_find_common_root(storage_space.headers_storage.get(node_info["common_root"]["worst_nonmutual"], rtx=rtx), message['node'],\
                          send = partial(send_message, "NetworkManager") )
      if node_info["common_root"]["try_num"]>5:
        pass #TODO we shoould try common root not from worst_nonmutual but at the middle between worst_nonmutual and best_mutual (binary search)
  height, total_difficulty = node_info['height'],node_info['total_difficulty']
  logger.info((height, storage_space.headers_manager.best_header_height, total_difficulty , storage_space.headers_manager.best_header_total_difficulty(rtx=rtx)))
  if root_found:
    if (height > storage_space.headers_manager.best_header_height) and (total_difficulty > storage_space.headers_manager.best_header_total_difficulty(rtx=rtx)):
      request_num = min(256, height-storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height)
      send_next_headers_request(node_info["common_root"]["root"], 
                                request_num,
                                message["node"], send = partial(send_message, "NetworkManager") )
      if height-storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height>request_num:
        node_info["common_root"]["long_reorganization"]= storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height+request_num



def  process_tbm_tx_request(message, send_message, rtx):
  tx_skel = storage_space.mempool_tx.give_tx_skeleton()
  tx = storage_space.mempool_tx.give_tx()
  serialized_tx_skel = tx_skel.serialize(rich_format=True, max_size=60000, rtx=rtx, full_tx=tx)
  send_message(message['sender'], \
     {"action":"take TBM transaction", "tx_skel": serialized_tx_skel, "mode": 0,
      "id":message['id'], 'node': message["node"] })

def  process_tbm_tx(message, send, nodes, rtx):
  try:
    initial_tbm = storage_space.mempool_tx.give_tx()
    tx_skel = TransactionSkeleton()
    tx_skel.deserialize_raw(message['tx_skel'], storage_space = storage_space)
    storage_space.mempool_tx.add_tx(tx_skel, rtx=rtx)
    final_tbm = storage_space.mempool_tx.give_tx()
    if not message["mode"]==0: #If 0 it is response to our request
      if (not initial_tbm) or (not str(initial_tbm.serialize())==str(final_tbm.serialize())):
        notify_all_nodes_about_tx(message['tx_skel'], nodes, send, _except=[message["node"]])
  except Exception as e:
    print(e)
    pass


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
      send_tip_info(node_info = node, send=send, rtx=rtx)


def notify_all_nodes_about_tx(tx_skel, nodes, send, _except=[], mode=1):
  #TODO we should not notify about tx with low relay fee
  for node_index in nodes:
    if node_index in _except:
      continue
    node = nodes[node_index]
    send({"action":"take TBM transaction", "tx_skel": tx_skel, "mode": mode,
      "id":str(uuid4()), 'node': node["node"] })

def notify_all_nodes_about_new_tip(nodes, send, rtx):
  for node_index in nodes:
    node = nodes[node_index]
    send_tip_info(node_info=node, send=send, rtx=rtx)

