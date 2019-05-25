from functools import partial
from leer.core.core_operations.sending_assets import send_headers, send_blocks, send_txos

def arrlen(array):
  return sum([len(el) for el in array])

def process_blocks_request(message, rtx, core):
  num = message["num"]
  _hashes = message["block_hashes"]
  _hashes = [_hashes[i*32:(i+1)*32] for i in range(num)]
  serialized_blocks = []
  blocks_hashes = [] 
  for _hash in _hashes:
    if not core.storage_space.blocks_storage.has(_hash, rtx=rtx):
      continue
    try:
      serialized_block = core.storage_space.blocks_storage.get(_hash, rtx=rtx).serialize(rtx=rtx, rich_block_format=True)
    except KeyError:
      #Some outputs were pruned
      serialized_block = core.storage_space.blocks_storage.get(_hash, rtx=rtx).serialize(rtx=rtx, rich_block_format=False)
    if arrlen(serialized_blocks)+len(serialized_block)<60000:
      serialized_blocks.append(serialized_block)
      blocks_hashes.append(_hash)
    else:
        send_blocks(partial(core.send_to_subprocess, message['sender']), \
                     blocks = serialized_blocks, \
                     hashes = blocks_hashes, \
                     node = message["node"], \
                     _id=message['id'])
        serialized_blocks=[serialized_block]
        blocks_hashes = [_hash]
  send_blocks(partial(core.send_to_subprocess, message['sender']), \
              blocks = serialized_blocks, \
              hashes = blocks_hashes, \
              node = message["node"], \
              _id=message['id'])


def process_next_headers_request(message, rtx, core):
  from_hash = message["from"]
  num = message["num"]
  num = 1024 if num>1024 else num
  try:
    header = core.storage_space.headers_storage.get(from_hash, rtx=rtx)
  except KeyError:
    return #unknown hash
  current_tip  = core.storage_space.blockchain.current_tip(rtx=rtx)
  current_height  = core.storage_space.blockchain.current_height(rtx=rtx)
  if not core.storage_space.headers_manager.find_ancestor_with_height(current_tip, header.height, rtx=rtx) == from_hash:
    return
    ''' Counter-node is not in our main chain. 
        We will not feed it (actually we just are not sure what we should send here)
    '''
  last_to_send_height = header.height+num
  last_to_send_height = current_height if last_to_send_height>current_height else last_to_send_height
  last_to_send = core.storage_space.headers_manager.find_ancestor_with_height(current_tip, last_to_send_height, rtx=rtx)
  headers_hashes = core.storage_space.headers_manager.get_subchain(from_hash, last_to_send, rtx=rtx)

  serialized_headers = []
  out_headers_hashes = []
  for _hash in headers_hashes:
    if not core.storage_space.headers_storage.has(_hash, rtx=rtx):
      continue
    serialized_header = core.storage_space.headers_storage.get(_hash, rtx=rtx).serialize()
    if arrlen(serialized_headers)+len(serialized_header)<60000:
      serialized_headers.append(serialized_header)
      out_headers_hashes.append(_hash)
    else:
      send_headers(partial(core.send_to_subprocess, message['sender']), \
                   headers = serialized_headers, \
                   hashes = out_headers_hashes,\
                   node = message["node"], \
                   _id=message['id'])
      serialized_headers=[serialized_header]
      out_headers_hashes = [_hash]
  send_headers(partial(core.send_to_subprocess, message['sender']), \
                   headers = serialized_headers,\
                   hashes = out_headers_hashes,\
                   node = message["node"], \
                   _id=message['id'])

def process_txos_request(message, rtx, core):
  num = message["num"]
  _hashes = message["txos_hashes"]
  _hashes = [bytes(_hashes[i*65:(i+1)*65]) for i in range(num)]
  serialized_txos = []
  txos_hashes = []
  for _hash in _hashes:
    try:
      serialized_txo = core.storage_space.txos_storage.find_serialized(_hash, rtx=rtx)
    except KeyError:
      continue
    len_txos_hashes = 65*len(serialized_txos)
    len_txos_lens = 2*len(serialized_txos)
    if arrlen(serialized_txos)+len(serialized_txo)+len_txos_hashes+len_txos_lens<64000:
      serialized_txos.append(serialized_txo)
      txos_hashes.append(_hash)
    else:
      send_txos(partial(core.send_to_subprocess, message['sender']), \
                   txos = serialized_txos,\
                   hashes = txos_hashes,\
                   node = message["node"], \
                   _id=message['id'])
      serialized_txos=[serialized_txo]
      txos_hashes = [_hash]
  send_txos(partial(core.send_to_subprocess, message['sender']), \
                   txos = serialized_txos,\
                   hashes = txos_hashes,\
                   node = message["node"], \
                   _id=message['id'])

def  process_tbm_tx_request(message, rtx, core):
  tx_skel = core.storage_space.mempool_tx.give_tx_skeleton()
  tx = core.storage_space.mempool_tx.give_tx()
  serialized_tx_skel = tx_skel.serialize(rich_format=True, max_size=60000, rtx=rtx, full_tx=tx)
  core.send_to_subprocess(message['sender'], \
     {"action":"take TBM transaction", "tx_skel": serialized_tx_skel, "mode": 0,
      "id":message['id'], 'node': message["node"] })


request_handlers = {"give TBM transaction": process_tbm_tx_request,\
                    "give txos": process_txos_request, \
                    "give next headers": process_next_headers_request,\
                    "give blocks": process_blocks_request
                   }

