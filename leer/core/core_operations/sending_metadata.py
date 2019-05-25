from uuid import uuid4
from time import time
from leer.core.core_operations.sending_assets import send_headers, send_blocks


def send_tip_info(node_info, rtx, core, our_tip_hash=None ):
  our_height = core.storage_space.blockchain.current_height(rtx=rtx)
  our_tip_hash = our_tip_hash if our_tip_hash else core.storage_space.blockchain.current_tip(rtx=rtx)
  our_prev_hash = core.storage_space.headers_storage.get(our_tip_hash, rtx=rtx).prev
  our_td = core.storage_space.headers_storage.get(our_tip_hash, rtx=rtx).total_difficulty

  core.send_to_network({"action":"take tip info", "height":our_height, "tip":our_tip_hash, "prev_hash":our_prev_hash, "total_difficulty":our_td, "id":uuid4(), "node": node_info["node"] })
  node_info["sent_tip"]=our_tip_hash
  node_info["last_send"] = time()

def notify_all_nodes_about_new_tip(nodes, rtx, core, _except=[], _payload_except=[]):
  '''
    _except: nodes which should not be notified about new tip
    _payload_except: nodes which should be notified about tip, but header and block will not be sent
  '''
  for node_index in nodes:
    node = nodes[node_index]
    if node_index in _except:
      continue
    if "height" in node:
      our_height = core.storage_space.blockchain.current_height(rtx=rtx)
      our_tip = core.storage_space.blockchain.current_tip(rtx=rtx)
      if node["height"]==our_height-1:
        serialized_header = core.storage_space.headers_storage.get(our_tip, rtx=rtx).serialize()
        serialized_block = core.storage_space.blocks_storage.get(our_tip, rtx=rtx).serialize(rtx=rtx, rich_block_format=True)
        send_headers(core.send_to_network, [serialized_header], [our_tip], node["node"])
        send_blocks(core.send_to_network, [serialized_block], [our_tip], node["node"])
    send_tip_info(node_info=node, rtx=rtx, core=core)

def send_find_common_root(from_header, node, send):
  send(
    {"action":"find common root", "serialized_header": from_header.serialize(), 
     "id":str(uuid4()), 
     "node": node })

