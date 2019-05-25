from enum import Enum
from uuid import uuid4
from time import time
from functools import partial

from leer.core.utils import DOSException
from leer.core.primitives.header import Header

from leer.core.core_operations.sending_metadata import send_tip_info, send_find_common_root
from leer.core.core_operations.sending_requests import send_next_headers_request

def process_tip_info(message, node_info, rtx, core):
  # another node (referenced as counter-Node below) asks us for our best tip and also provides us information about his
  if ('common_root' in node_info) and ('worst_nonmutual' in node_info['common_root']):
    return #Ignore new tips while detect common_root
  node = message["node"]
  height = message["height"]
  tip_hash = message["tip"]
  prev_hash = message["prev_hash"]
  total_difficulty = message["total_difficulty"]
  our_tip_hash = core.storage_space.blockchain.current_tip(rtx=rtx)

  if (not "sent_tip" in node_info) or \
     (not node_info["sent_tip"]==our_tip_hash) or \
     (not "last_send" in node_info) or \
     (time() - node_info["last_send"]>300):
    send_tip_info(node_info=node_info, our_tip_hash=our_tip_hash,\
                  rtx=rtx, core=core)
  node_info.update({"node":node, "height":height, "tip_hash":tip_hash, 
                    "prev_hash":prev_hash, "total_difficulty":total_difficulty, 
                    "last_update":time()})
  if (height > core.storage_space.blockchain.current_height(rtx=rtx)) and (total_difficulty > core.storage_space.headers_storage.get(our_tip_hash, rtx=rtx).total_difficulty):
    #Now there are two options: better headers are unknown or headers are known, but blocks are unknown or bad
    if not core.storage_space.headers_storage.has(tip_hash, rtx=rtx):
      send_find_common_root(core.storage_space.headers_storage.get(our_tip_hash, rtx=rtx), node, send = core.send_to_network)
      #TODO check prev hash first
    else: #header is known
      header = core.storage_space.headers_storage.get(tip_hash, rtx=rtx)
      #TODO do we need to check for connection to genesis?
      common_root =  core.storage_space.headers_manager.find_bifurcation_point(tip_hash, our_tip_hash, rtx=rtx)
      if header.invalid:
        return #Nothing interesting, counter-node is on wrong chain
      if core.storage_space.blocks_storage.has(tip_hash, rtx=rtx):
        if core.storage_space.blocks_storage.get(tip_hash, rtx=rtx).invalid:
          return #Nothing interesting, counter-node is on wrong chain
      #download blocks
      blocks_to_download = []
      for _block_hash in core.storage_space.headers_manager.get_subchain(common_root, tip_hash, rtx=rtx):
        if not core.storage_space.blocks_storage.has(_block_hash, rtx=rtx):
          blocks_to_download.append(_block_hash)
        else:
          core.storage_space.blocks_storage.is_block_downloaded(_block_hash, rtx=rtx)
        if len(blocks_to_download)*32>40000: #Too big for one message
          break
      if len(blocks_to_download):
        core.send_to_network({"action":"give blocks",  
            "block_hashes": b"".join(blocks_to_download),
            'num': len(blocks_to_download), "id":str(uuid4()), "node":message["node"] })

class HEADERSTATE(Enum):
  UNKNOWN = 0
  INFORK = 1
  MAINCHAIN = 2
  ISOLATED = 3
  def to_bytes(self, num_bytes, endianness):
    return (self.value).to_bytes(num_bytes, endianness)

def process_find_common_root(message, node_info, rtx, core):
  #node_info is ignored, added to unify process_metadata function sugnature
  try:
    serialized_header = message["serialized_header"]
    header = Header()
    header.deserialize_raw(serialized_header)
  except:
    raise DOSException()
  result = []
  for pointer in [header.hash]+header.popow.pointers:
    if not core.storage_space.headers_storage.has(pointer, rtx=rtx):
      result.append(HEADERSTATE.UNKNOWN)
      continue
    ph = core.storage_space.headers_storage.get(pointer, rtx=rtx)
    if not ph.connected_to_genesis:
      result.append(HEADERSTATE.ISOLATED)
      continue
    if core.storage_space.headers_manager.find_ancestor_with_height(core.storage_space.blockchain.current_tip(rtx=rtx), ph.height, rtx=rtx) == pointer:
      result.append(HEADERSTATE.MAINCHAIN)
      continue
    result.append(HEADERSTATE.INFORK)

  core.send_to_subprocess(message['sender'], \
     {"action":"find common root response", "header_hash":header.hash,
      "flags_num": len(result), 
      "known_headers": b"".join([i.to_bytes(1,"big") for i in result]), 
      "id":message['id'], "node": message["node"] })


def process_find_common_root_response(message, node_info, rtx, core):
  header_hash = message["header_hash"]
  result = [int(i) for i in message["known_headers"]]
  try:
    header = core.storage_space.headers_storage.get(header_hash, rtx=rtx)
  except KeyError:
    raise DOSException()
  root_found = False
  if not "common_root" in node_info:
    node_info["common_root"]={}
  for index, pointer in enumerate([header.hash]+header.popow.pointers):
    if HEADERSTATE(result[index]) in [HEADERSTATE.MAINCHAIN]:
        node_info["common_root"]["best_mutual"]=pointer
        best_mutual_height = core.storage_space.headers_storage.get(node_info["common_root"]["best_mutual"], rtx=rtx).height
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
  if not root_found:
    h1,h2 = core.storage_space.headers_storage.get(node_info["common_root"]["worst_nonmutual"], rtx=rtx).height,\
            core.storage_space.headers_storage.get(node_info["common_root"]["best_mutual"], rtx=rtx).height
    if h1==h2+1:
      root_found = True
      node_info["common_root"].pop("try_num", None)
      node_info["common_root"]["root"] = node_info["common_root"]["best_mutual"]
    else:
      if not "try_num" in node_info["common_root"]:
        node_info["common_root"]["try_num"]=0
      node_info["common_root"]["try_num"]+=1
      send_find_common_root(core.storage_space.headers_storage.get(node_info["common_root"]["worst_nonmutual"], rtx=rtx), message['node'],\
                          send = core.send_to_network )
      if node_info["common_root"]["try_num"]>5:
        pass #TODO we shoould try common root not from worst_nonmutual but at the middle between worst_nonmutual and best_mutual (binary search)
  try:
    height, total_difficulty = node_info['height'],node_info['total_difficulty']
  except KeyError:
    return
  if root_found:
    node_info["common_root"].pop("worst_nonmutual", None)
    node_info["common_root"].pop("best_mutual", None)
    common_root_height = core.storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height
    if (height > core.storage_space.headers_manager.best_header_height) and (total_difficulty > core.storage_space.headers_manager.best_header_total_difficulty(rtx=rtx)):
      headers_chain_advance = core.config.get("synchronisation", {}).get("headers_chain_advance", 256)
      request_num = min(headers_chain_advance, height-common_root_height)
      send_next_headers_request(node_info["common_root"]["root"], 
                                request_num,
                                message["node"], send = core.send_to_network )
      if height-common_root_height>request_num:
        our_tip = core.storage_space.headers_storage.get(core.storage_space.blockchain.current_tip(rtx=rtx), rtx=rtx)
        if our_tip.hash != node_info["common_root"]["root"]: #It's indeed reorg
            node_info["common_root"]["long_reorganization"]= core.storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height+request_num

metadata_handlers = {"take tip info":process_tip_info, 
                     "find common root":process_find_common_root, 
                     "find common root response":process_find_common_root_response}
