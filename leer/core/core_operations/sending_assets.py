from uuid import uuid4
from leer.core.utils import ObliviousDictionary
upload_cache = ObliviousDictionary(sink_delay=600) #tracks what we already sent in recent past to our peers

def send_assets(asset_type, send, serialized_assets, assets_hashes, node, _id=None):
  if not _id:
    _id=str(uuid4())
  assets, hashes = [],[]
  for i, h in enumerate(assets_hashes):
    if (node, asset_type, h) in upload_cache:
      continue
    else:
      assets.append(serialized_assets[i])
      hashes.append(h)
      upload_cache[(node, asset_type, h)] = True
  all_assets  = b"".join(assets)
  all_hashes  = b"".join(hashes)
  all_lengths = b"".join([len(a).to_bytes(2,"big") for a in assets])
  #Note hashes and lengths will be ignored by NetworkManager for headers and blocks
  if len(all_assets):
    send({"action":"take the %s"%asset_type,\
          "num": len(assets),\
          asset_type: all_assets,\
          "%s_hashes"%asset_type : all_hashes,\
          "%s_lengths"%asset_type : all_lengths,\
          "id":_id, "node": node})

def send_headers(send, headers, hashes, node, _id=None):
  send_assets("headers", send, headers, hashes, node, _id)

def send_blocks(send, blocks, hashes, node, _id=None):
  send_assets("blocks", send, blocks, hashes,  node, _id)

def send_txos(send, txos, hashes, node, _id=None):
  send_assets("txos", send, txos, hashes,  node, _id)

def notify_all_nodes_about_tx(tx_skel, core, _except=[], mode=1):
  #TODO we should not notify about tx with low relay fee
  for node_index in core.nodes:
    if node_index in _except:
      continue
    node = core.nodes[node_index]
    core.send_to_network({"action":"take TBM transaction", "tx_skel": tx_skel, "mode": mode,
      "id":str(uuid4()), 'node': node["node"] })


