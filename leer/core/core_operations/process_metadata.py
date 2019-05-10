from leer.core.core_operations.sending_metadata import send_tip_info, send_find_common_root
from leer.core.core_operations.sending_requests import send_next_headers_request

def process_tip_info(message, node_info, send, storage_space, rtx):
  # another node (referenced as counter-Node below) asks us for our best tip and also provides us information about his
  if ('common_root' in node_info) and ('worst_nonmutual' in node_info['common_root']):
    return #Ignore new tips while detect common_root
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
    send_tip_info(node_info=node_info, send = send, our_tip_hash=our_tip_hash,\
                  storage_space=storage_space, rtx=rtx)
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

UNKNOWN, INFORK, MAINCHAIN, ISOLATED = 0, 1, 2, 3

def process_find_common_root(message, send_message, storage_space, rtx):
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


def process_find_common_root_response(message, node_info, send_message, storage_space, rtx):
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
    if result[index] in [MAINCHAIN]:
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
  try:
    height, total_difficulty = node_info['height'],node_info['total_difficulty']
  except KeyError:
    return
  logger.info((height, storage_space.headers_manager.best_header_height, total_difficulty , storage_space.headers_manager.best_header_total_difficulty(rtx=rtx)))
  if root_found:
    node_info["common_root"].pop("worst_nonmutual", None)
    node_info["common_root"].pop("best_mutual", None)
    common_root_height = storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height
    if (height > storage_space.headers_manager.best_header_height) and (total_difficulty > storage_space.headers_manager.best_header_total_difficulty(rtx=rtx)):
      request_num = min(256, height-common_root_height)
      send_next_headers_request(node_info["common_root"]["root"], 
                                request_num,
                                message["node"], send = partial(send_message, "NetworkManager") )
      if height-common_root_height>request_num:
        our_tip = storage_space.headers_storage.get(storage_space.blockchain.current_tip(rtx=rtx), rtx=rtx)
        if our_tip.hash != node_info["common_root"]["root"]: #It's indeed reorg
            node_info["common_root"]["long_reorganization"]= storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=rtx).height+request_num

