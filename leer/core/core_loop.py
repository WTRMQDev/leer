from leer.core.chains.headers_manager import HeadersManager
from leer.core.chains.blockchain import Blockchain
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.storage.blocks_storage import BlocksStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.utxo_index_storage import UTXOIndex
from leer.core.storage.mempool_tx import MempoolTx
from leer.core.storage.key_manager import KeyManagerClass
from leer.core.primitives.block import Block
from leer.core.primitives.header import Header
from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Address
from leer.core.lubbadubdub.transaction import Transaction
import base64
from leer.core.utils import DOSException
from leer.core.primitives.transaction_sceleton import TransactionSceleton
from time import sleep, time
from uuid import uuid4

from leer.core.storage.storage_space import StorageSpace
from leer.core.storage.default_paths import base_dir as default_base_dir, calc_paths

from leer.syncer import Syncer
from leer.core.parameters.constants import serialized_genesis_block

from secp256k1_zkp import PrivateKey

import logging
from functools import partial
logger = logging.getLogger("core_loop")

storage_space = StorageSpace()

def init_blockchain():
  '''
    If blockchain is empty this function will set genesis.
  '''
  genesis = Block(storage_space = storage_space)
  genesis.deserialize(serialized_genesis_block)
  storage_space.headers_manager.set_genesis(genesis.header)
  if not storage_space.blockchain.current_height>=0:
    storage_space.headers_manager.context_validation(genesis.header.hash)
    genesis.non_context_verify()
    storage_space.blockchain.add_block(genesis)
  else:
    storage_space.headers_manager.best_tip = (storage_space.blockchain.current_tip, storage_space.blockchain.current_height )
    logger.info("Best header tip from blockchain state %d"%storage_space.headers_manager.best_tip[1])
    #greedy search
    current_tip = storage_space.headers_manager.best_tip[0]
    while True:
      try:
        header = storage_space.headers_storage[current_tip]
      except KeyError:
        break
      new_current_tip=current_tip
      if len(header.descendants):
        for d in header.descendants:
          dh = storage_space.headers_storage[d]
          if not dh.invalid:
            new_current_tip = d
            break
      if not new_current_tip == current_tip:
        current_tip=new_current_tip
      else:
        break
    storage_space.headers_manager.best_tip = (current_tip, storage_space.headers_storage[current_tip].height)
    logger.info("Best header tip after greedy search %d"%storage_space.headers_manager.best_tip[1])


def init_storage_space(config):
  _paths = {}
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
      
  hs = HeadersStorage(storage_space, _paths["headers_storage_path"])
  hm = HeadersManager(storage_space)
  bs = BlocksStorage(storage_space, _paths["blocks_storage_path"])
  es = ExcessesStorage(storage_space, _paths["excesses_storage_path"])
  ts = TXOsStorage(storage_space, _paths["txo_storage_path"])
  bc = Blockchain(storage_space)
  mptx = MempoolTx(storage_space)
  utxoi = UTXOIndex(storage_space, _paths["utxo_index_path"])
  km = KeyManagerClass(path = _paths["key_manager_path"])
  mptx.set_key_manager(km)
  init_blockchain()

  

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


def core_loop(syncer, config):
  message_queue = syncer.queues['Blockchain']
  init_storage_space(config)


  nodes = {}
  set_ask_for_blocks_hook(storage_space.blockchain, message_queue)
  set_ask_for_txouts_hook(storage_space.blocks_storage, message_queue)
  requests = {}
  message_queue.put({"action":"give nodes list reminder"})

  def send_message(destination, message):
    if not 'id' in message:
      message['id'] = uuid4()
    if not 'sender' in message:
      message['sender'] = "Blockchain"
    syncer.queues[destination].put(message)

  def send_to_nm(message):
    send_message("NetworkManager", message)
  

  logger.debug("Start of core loop")
  while True:
    sleep(0.05)
    put_back_messages = []
    while not message_queue.empty():
      message = message_queue.get()
      if 'time' in message and message['time']>time(): # delay this message
        put_back_messages.append(message)
        continue
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
          process_new_headers(message)
        if message["action"] == "take the blocks":
          initial_tip = storage_space.blockchain.current_tip
          process_new_blocks(message)
          after_tip = storage_space.blockchain.current_tip
          if not after_tip==initial_tip:
            notify_all_nodes_about_new_tip(nodes, send_to_nm)          
        if message["action"] == "take the txos":
          process_new_txos(message)
        if message["action"] == "give blocks":
          process_blocks_request(message, send_message)
        if message["action"] == "give next headers":
          process_next_headers_request(message, send_message)
        if message["action"] == "give txos":
          process_txos_request(message, send_message)
        if message["action"] == "find common root":
          process_find_common_root(message, send_message)
        if message["action"] == "find common root response":
          process_find_common_root_reponse(message, nodes[message["node"]], send_message)
        if message["action"] == "give TBM transaction":
          process_tbm_tx_request(message, send_message)
        if message["action"] == "take TBM transaction":
          process_tbm_tx(message, send_to_nm, nodes)
        if message["action"] == "give tip height":
          send_message(message["sender"], {"id": message["id"], "result": storage_space.blockchain.current_height})
      
        if message["action"] == "take tip info":
          if not message["node"] in nodes:
            nodes[message["node"]]={'node':message["node"]}
          process_tip_info(message, nodes[message["node"]], send=send_to_nm)
      except DOSException as e:
        logger.info("DOS Exception %s"%str(e))
        #raise e #TODO send to NM
      except Exception as e:
        raise e

      if message["action"] == "give block template":
        block = storage_space.mempool_tx.give_block_template()
        ser_head = block.header.serialize()
        send_message(message["sender"], {"id": message["id"], "result":ser_head})
      if message["action"] == "take solved block template":
        try:
          initial_tip = storage_space.blockchain.current_tip
          header = Header()
          header.deserialize(message["solved template"])
          solved_block = storage_space.mempool_tx.get_block_by_header_solution(header)
          storage_space.headers_manager.add_header(solved_block.header)
          storage_space.headers_manager.context_validation(solved_block.header.hash)
          solved_block.non_context_verify()
          storage_space.blockchain.add_block(solved_block)
          send_message(message["sender"], {"id": message["id"], "result": "Accepted"})
          after_tip = storage_space.blockchain.current_tip
          if not after_tip==initial_tip:
            notify_all_nodes_about_new_tip(nodes, send_to_nm)
        except Exception as e:
          raise e
          send_message(message["sender"], {"id": message["id"], "error": str(e)})

      if message["action"] == "get confirmed balance stats":
        if storage_space.mempool_tx.key_manager:
          stats = storage_space.mempool_tx.key_manager.get_confirmed_balance_stats( 
                     storage_space.utxo_index,
                     storage_space.txos_storage,
                     storage_space.blockchain.current_height)
          send_message(message["sender"], {"id": message["id"], "result":stats})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "get confirmed balance list":
        if storage_space.mempool_tx.key_manager:
          _list = storage_space.mempool_tx.key_manager.get_confirmed_balance_list( 
                     storage_space.utxo_index,
                     storage_space.txos_storage,
                     storage_space.blockchain.current_height)
          send_message(message["sender"], {"id": message["id"], "result":_list})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "give new address":
        if storage_space.mempool_tx.key_manager:
          texted_address = storage_space.mempool_tx.key_manager.new_address().to_text()
          send_message(message["sender"], {"id": message["id"], "result": texted_address})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "give private key":
        if storage_space.mempool_tx.key_manager:
          km = storage_space.mempool_tx.key_manager
          a=Address()
          a.from_text(message["address"])
          serialized_pk = km.priv_by_address(a).serialize()
          send_message(message["sender"], {"id": message["id"], "result": serialized_pk})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "take private key":
        if storage_space.mempool_tx.key_manager:
          km = storage_space.mempool_tx.key_manager
          pk=PrivateKey()
          pk.deserialize(message['privkey'])
          km.add_privkey(pk)
          send_message(message["sender"], {"id": message["id"], "result": "imported"})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      if message["action"] == "give synchronization status":
        our_height = storage_space.blockchain.current_height
        best_known_header = storage_space.headers_manager.best_header_height
        try:
          best_advertised_height = max([nodes[node]["height"] for node in nodes if "height" in nodes[node]])
        except:
          best_advertised_height = None
        send_message(message["sender"], {"id": message["id"], 
                                         "result": {'height': our_height, 
                                                    'best_known_header': best_known_header,
                                                    'best_advertised_height': best_advertised_height}})


      if message["action"] == "send to address":
        value  = int(message["value"])
        taddress = message["address"]
        a = Address()
        a.from_text(taddress)
        if storage_space.mempool_tx.key_manager:
          _list = storage_space.mempool_tx.key_manager.get_confirmed_balance_list( 
                     storage_space.utxo_index,
                     storage_space.txos_storage,
                     storage_space.blockchain.current_height)
          list_to_spend = []
          summ = 0 
          for address in _list:
            for texted_index in _list[address]:
              if summ>value:
                continue
              if isinstance(_list[address][texted_index], int):
                _index = base64.b64decode(texted_index.encode())
                utxo = storage_space.txos_storage.confirmed[_index]
                if not utxo.lock_height<=storage_space.blockchain.current_height:
                    continue
                list_to_spend.append(utxo)
                summ+=_list[address][texted_index]
          if summ <value:
            send_message(message["sender"], {"id": message["id"], "error": "Not enough matured coins"})
          tx = Transaction(txos_storage = storage_space.txos_storage, key_manager = storage_space.mempool_tx.key_manager)
          for utxo in list_to_spend:
            tx.push_input(utxo)
          tx.add_destination( (a, value) )
          tx.generate()
          tx.verify()
          storage_space.mempool_tx.add_tx(tx)
          tx_scel = TransactionSceleton(tx=tx)
          notify_all_nodes_about_tx(tx_scel.serialize(rich_format=True, max_size=40000), nodes, send_to_nm, _except=[], mode=1)
          send_message(message["sender"], {"id": message["id"], "result":"generated"})
        else:
          send_message(message["sender"], {"id": message["id"], "error": "No registered key manager"})

      #message from core_loop
      if message["action"] == "check txouts download status":
        txos = message["txos_hashes"]
        to_be_downloaded = []
        for txo in txos:
          if not storage_space.txos_storage.known(txo):
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
        for block_hash in block_hashes:
          if block_hash in storage_space.blocks_storage:
            continue #We are good, block already downloaded          
          if not block_hash in storage_space.blockchain.awaited_blocks:
            continue #For some reason we dont need this block anymore
          to_be_downloaded.append(block_hash)
          if storage_space.headers_storage[block_hash].height<lowest_height:
            lowest_height = storage_space.headers_storage[block_hash].height
        already_asked_nodes = message["already_asked_nodes"]
        asked = False
        for node_params in nodes:
          node = nodes[node_params]
          if node in already_asked_nodes:
            continue
          if node["height"] < lowest_height:
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


    for _message in put_back_messages:
      message_queue.put(_message)

    try:
      check_sync_status(nodes, send_to_nm)
    except Exception as e:
      logger.error(e)



def process_new_headers(message):
  dupplication_header_dos = False
  try:
    serialized_headers = message["headers"]
    num = message["num"]
    for i in range(num):
      header = Header()
      serialized_headers = header.deserialize_raw(serialized_headers)
      if header.hash in storage_space.headers_storage:
        dupplication_header_dos=True
        continue
      storage_space.headers_manager.add_header(header)
    storage_space.blockchain.update(reason="downloaded new headers")
  except Exception as e:
    raise e

def process_new_blocks(message):
  try:
    serialized_blocks = message["blocks"]
    num = message["num"]
    for i in range(num):
      block = Block(storage_space=storage_space)
      serialized_blocks = block.deserialize_raw(serialized_blocks)
      storage_space.blockchain.add_block(block, no_update=True)
    storage_space.blockchain.update(reason="downloaded new blocks")
  except Exception as e:
    raise e #XXX "DoS messages should be returned"

def process_new_txos(message):
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
    storage_space.blockchain.update(reason="downloaded new txos")
  except Exception as e:
    raise e #XXX "DoS messages should be returned"

def process_blocks_request(message, send_message):
  num = message["num"]
  _hashes = message["block_hashes"]
  _hashes = [_hashes[i*32:(i+1)*32] for i in range(num)]
  serialized_blocks = b""
  blocks_num=0
  for _hash in _hashes:
    if not _hash in storage_space.blocks_storage:
      continue
    try:
      serialized_block = storage_space.blocks_storage[_hash].serialize(rich_block_format=True)
    except KeyError:
      #Some outputs were pruned
      serialized_block = storage_space.blocks_storage[_hash].serialize(rich_block_format=False)
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

def process_next_headers_request(message, send_message):
  from_hash = message["from"]
  num = message["num"]
  num = 1024 if num>1024 else num
  try:
    header = storage_space.headers_storage[from_hash]
  except KeyError:
    return #unknown hash
  current_tip  = storage_space.blockchain.current_tip
  current_height  = storage_space.blockchain.current_height
  if not storage_space.headers_manager.find_ancestor_with_height(current_tip, header.height) == from_hash:
    return
    ''' Counter-node is not in our main chain. 
        We will not feed it (actually we just not sure what we should send here)
    '''
  last_to_send_height = header.height+num
  last_to_send_height = current_height if last_to_send_height>current_height else last_to_send_height
  last_to_send = storage_space.headers_manager.find_ancestor_with_height(current_tip, last_to_send_height)
  headers_hashes = storage_space.headers_manager.get_subchain(from_hash, last_to_send)

  serialized_headers = b""
  headers_num=0
  for _hash in headers_hashes:
    if not _hash in storage_space.headers_storage:
      continue
    serialized_header = storage_space.headers_storage[_hash].serialize()
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

def process_txos_request(message, send_message):
  num = message["num"]
  _hashes = message["txos_hashes"]
  _hashes = [bytes(_hashes[i*65:(i+1)*65]) for i in range(num)]
  serialized_txos = b""
  txos_num=0
  txos_hashes = b""
  txos_lengths = b""
  for _hash in _hashes:
    try:
      serialized_txo = storage_space.txos_storage.find_serialized(_hash)
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

def send_tip_info(node_info, send, our_tip_hash=None ):
  our_height = storage_space.blockchain.current_height
  our_tip_hash = our_tip_hash if our_tip_hash else storage_space.blockchain.current_tip
  our_prev_hash = storage_space.headers_storage[our_tip_hash].prev
  our_td = storage_space.headers_storage[our_tip_hash].total_difficulty

  send({"action":"take tip info", "height":our_height, "tip":our_tip_hash, "prev_hash":our_prev_hash, "total_difficulty":our_td, "id":uuid4(), "node": node_info["node"] })
  node_info["sent_tip"]=our_tip_hash
  node_info["last_send"] = time()

def process_tip_info(message, node_info, send):
  # another node (referenced as counter-Node below) asks us for our best tip and also provide us information about his
  node = message["node"]
  height = message["height"]
  tip_hash = message["tip"]
  prev_hash = message["prev_hash"]
  total_difficulty = message["total_difficulty"]

  our_tip_hash = storage_space.blockchain.current_tip

  if (not "sent_tip" in node_info) or (not node_info["sent_tip"]==our_tip_hash):
    send_tip_info(node_info=node_info, send = send, our_tip_hash=our_tip_hash)
  node_info.update({"node":node, "height":height, "tip_hash":tip_hash, 
                    "prev_hash":prev_hash, "total_difficulty":total_difficulty, 
                    "last_update":time()})
  if (height > storage_space.blockchain.current_height) and (total_difficulty > storage_space.headers_storage[our_tip_hash].total_difficulty):
    #Now there are two options: better headers are unknown or headers are known, but blocks are unknown or bad
    if (not tip_hash in storage_space.headers_storage):
      send_find_common_root(storage_space.headers_storage[our_tip_hash], node, send = send)
      #TODO check prev hash first
    else: #header is known
      header = storage_space.headers_storage[tip_hash]
      #TODO do we need to check for connection to genesis?
      common_root =  storage_space.headers_manager.find_bifurcation_point(tip_hash, our_tip_hash)
      if header.invalid:
        return #Nothing interesting, counter-node is on wrong chain
      if tip_hash in storage_space.blocks_storage:
        if storage_space.blocks_storage[tip_hash].invalid:
          return #Nothing interesting, counter-node is on wrong chain
      #download blocks
      blocks_to_download = []
      print("Here")
      for _block_hash in storage_space.headers_manager.get_subchain(common_root, tip_hash):
        print(_block_hash, _block_hash in storage_space.blocks_storage)
        if not _block_hash in storage_space.blocks_storage:
          blocks_to_download.append(_block_hash)
        else:
          storage_space.blocks_storage.is_block_downloaded(_block_hash)
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

def  process_find_common_root(message, send_message):
  serialized_header = message["serialized_header"]
  header = Header()
  header.deserialize_raw(serialized_header)
  result = []
  for pointer in [header.hash]+header.popow.pointers:
    if not pointer in storage_space.headers_storage:
      result.append(UNKNOWN)
      continue
    ph = storage_space.headers_storage[pointer]
    if not ph.connected_to_genesis:
      result.append(ISOLATED)
      continue
    if storage_space.headers_manager.find_ancestor_with_height(storage_space.blockchain.current_tip, ph.height) == pointer:
      result.append(MAINCHAIN)
      continue
    result.append(INFORK)

  send_message(message['sender'], \
     {"action":"find common root response", "header_hash":header.hash,
      "flags_num": len(result), 
      "known_headers": b"".join([i.to_bytes(1,"big") for i in result]), 
      "id":message['id'], "node": message["node"] })

def process_find_common_root_reponse(message, node_info, send_message):
  header_hash = message["header_hash"]
  result = [int(i) for i in message["known_headers"]]
  header = storage_space.headers_storage[header_hash]
  root_found = False
  if not "common_root" in node_info:
    node_info["common_root"]={}

  for index, pointer in enumerate([header.hash]+header.popow.pointers):
    if result[index] in [MAINCHAIN, INFORK]:
        node_info["common_root"]["best_mutual"]=pointer
        best_mutual_height = storage_space.headers_storage[node_info["common_root"]["best_mutual"]].height
        break
    else:
      node_info["common_root"]["worst_nonmutual"]=pointer
  logger.info("Processing of fcrr")
  logger.info(node_info)
  if (not "worst_nonmutual" in node_info["common_root"]):
    #we are behind
    node_info["common_root"]["root"] = header_hash
    root_found = True
  if (not "best_mutual" in node_info["common_root"]):
    # genesis should allways be mutual
    return
  logger.info(node_info)
  if not root_found:
    h1,h2 = storage_space.headers_storage[node_info["common_root"]["worst_nonmutual"]].height, storage_space.headers_storage[node_info["common_root"]["best_mutual"]].height
    if h1==h2+1:
      root_found = True
      node_info["common_root"]["root"] = node_info["common_root"]["best_mutual"]
    else:
      send_find_common_root(storage_space.headers_storage[node_info["common_root"]["worst_nonmutual"]], message['node'],\
                          send = partial(send_message, "NetworkManager") )
  logger.info(node_info)
  height, total_difficulty = node_info['height'],node_info['total_difficulty']
  logger.info((height, storage_space.headers_manager.best_header_height, total_difficulty , storage_space.headers_manager.best_header_total_difficulty))
  if root_found:
    if (height > storage_space.headers_manager.best_header_height) and (total_difficulty > storage_space.headers_manager.best_header_total_difficulty):
      send_next_headers_request(node_info["common_root"]["root"], 
                                min(256, height-storage_space.headers_storage[node_info["common_root"]["root"]].height),
                                message["node"], send = partial(send_message, "NetworkManager") )



def  process_tbm_tx_request(message, send_message):
  tx_scel = storage_space.mempool_tx.give_tx_sceleton()
  tx = storage_space.mempool_tx.give_tx()
  serialized_tx_scel = tx_scel.serialize(rich_format=True, max_size=60000, full_tx=tx)
  send_message(message['sender'], \
     {"action":"take TBM transaction", "tx_scel": serialized_tx_scel, "mode": 0,
      "id":message['id'], 'node': message["node"] })

def  process_tbm_tx(message, send, nodes):
  try:
    initial_tbm = storage_space.mempool_tx.give_tx()
    tx_scel = TransactionSceleton()
    tx_scel.deserialize_raw(message['tx_scel'], storage_space = storage_space)
    storage_space.mempool_tx.add_tx(tx_scel)
    if not message["mode"]==0: #If 0 it is response to our request
      if (not initial_tbm) or (not str(initial_tbm.serialize())==str(final_tbm.serialize())):
        notify_all_nodes_about_tx(message['tx_scel'], nodes, send, _except=[message["node"]])
  except Exception as e:
    print(e)
    pass

  
def check_sync_status(nodes, send):
  for node_index in nodes:
    node = nodes[node_index]
    if ((not "last_update" in node) or node["last_update"]+300<time()) and ((not "last_send" in node) or node["last_send"]+5<time()):
      #logger.info("\n node last_update %d was %.4f sec\n"%(("last_update" in node),   (time()-node["last_update"] if ("last_update" in node) else 0 )))
      send_tip_info(node_info = node, send=send)


def notify_all_nodes_about_tx(tx_scel, nodes, send, _except=[], mode=1):
  for node_index in nodes:
    if node_index in _except:
      continue
    node = nodes[node_index]
    send({"action":"take TBM transaction", "tx_scel": tx_scel, "mode": mode,
      "id":str(uuid4()), 'node': node["node"] })

def notify_all_nodes_about_new_tip(nodes, send):
  for node_index in nodes:
    node = nodes[node_index]
    send_tip_info(node_info=node, send=send)

