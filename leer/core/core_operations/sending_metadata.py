from leer.core.core_operations.sending_assets import send_headers, send_blocks


def send_tip_info(node_info, send, storage_space, rtx, our_tip_hash=None ):
  our_height = storage_space.blockchain.current_height(rtx=rtx)
  our_tip_hash = our_tip_hash if our_tip_hash else storage_space.blockchain.current_tip(rtx=rtx)
  our_prev_hash = storage_space.headers_storage.get(our_tip_hash, rtx=rtx).prev
  our_td = storage_space.headers_storage.get(our_tip_hash, rtx=rtx).total_difficulty

  send({"action":"take tip info", "height":our_height, "tip":our_tip_hash, "prev_hash":our_prev_hash, "total_difficulty":our_td, "id":uuid4(), "node": node_info["node"] })
  node_info["sent_tip"]=our_tip_hash
  node_info["last_send"] = time()

def notify_all_nodes_about_new_tip(nodes, send, storage_space, rtx, _except=[], _payload_except=[]):
  '''
    _except: nodes which should not be notified about new tip
    _payload_except: nodes which should be notified about tip, but header and block will not be sent
  '''
  for node_index in nodes:
    node = nodes[node_index]
    if node_index in _except:
      continue
    if "height" in node:
      our_height = storage_space.blockchain.current_height(rtx=rtx)
      our_tip = storage_space.blockchain.current_tip(rtx=rtx)
      if node["height"]==our_height-1:
        serialized_header = storage_space.headers_storage.get(our_tip, rtx=rtx).serialize()
        serialized_block = storage_space.blocks_storage.get(our_tip, rtx=rtx).serialize(rtx=rtx, rich_block_format=True)
        send_headers(send, [serialized_header], [our_tip], node["node"])
        send_blocks(send, [serialized_block], [our_tip], node["node"])
    send_tip_info(node_info=node, send=send, rtx=rtx)

def send_find_common_root(from_header, node, send):
  send(
    {"action":"find common root", "serialized_header": from_header.serialize(), 
     "id":str(uuid4()), 
     "node": node })

