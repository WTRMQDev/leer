from uuid import uuid4
from time import time

def check_blocks_download_status(message, rtx, core):
        block_hashes = message["block_hashes"]
        to_be_downloaded = []
        lowest_height=1e10
        for block_hash in block_hashes:
          if core.storage_space.blocks_storage.has(block_hash, rtx=rtx):
              continue #We are good, block already downloaded          
          if not block_hash in core.storage_space.blockchain.awaited_blocks:
              continue #For some reason we don't need this block anymore
          to_be_downloaded.append(block_hash)
          block_height = core.storage_space.headers_storage.get(block_hash, rtx=rtx).height
          if block_height<lowest_height:
              lowest_height = block_height
        if not len(to_be_downloaded):
          return None
        already_asked_nodes = message["already_asked_nodes"]
        asked = False
        for node_params in core.nodes:
          node = core.nodes[node_params]
          if node in already_asked_nodes:
            continue
          if (not "height" in node) or node["height"] < lowest_height:
            continue
          already_asked_nodes += [node]
          core.send_to_network({"action":"give blocks",  "block_hashes": bytes(b"".join(block_hashes)), 'num': len(block_hashes), "id":str(uuid4()), "node":node_params })
          new_message = {"action": "check blocks download status", "block_hashes":to_be_downloaded,
                         "already_asked_nodes": already_asked_nodes, "id": str(uuid4()),
                         "time": int(time()+30) }
          asked = True
          return new_message
        if not asked: #We already asked all applicable nodes
          message["time"]=int(time())+600
          message["already_asked_nodes"] = []
          return message # we will try to ask again in an hour

def check_txouts_download_status(message, rtx, core):
        txos = message["txos_hashes"]
        to_be_downloaded = []
        for txo in txos:
            if not core.storage_space.txos_storage.known(txo, rtx=rtx):
              to_be_downloaded.append(txo)
        if not to_be_downloaded:
          return None #We are good, txouts are already downloaded
        already_asked_nodes = message["already_asked_nodes"]
        asked = False
        for node_params in core.nodes:
          node = core.nodes[node_params]
          if node in already_asked_nodes:
            continue
          already_asked_nodes += [node]
          core.send_to_network({"action":"give txos",
                                               "txos_hashes": b"".join(to_be_downloaded), 
                                               "num": len(to_be_downloaded), 
                                               "id":str(uuid4()), "node":node_params })
          new_message = {"action": "check txouts download status", "txos_hashes":to_be_downloaded,
                         "already_asked_nodes": already_asked_nodes, "id": str(uuid4()),
                         "time": int(time()+30) }
          asked = True
          return new_message
        if not asked: #We already asked all applicable nodes
          message["time"]=int(time())+600
          message["already_asked_nodes"] = []
          return message # we will try to ask again in an hour

download_status_checks = {"check txouts download status":check_txouts_download_status, "check blocks download status":check_blocks_download_status}
