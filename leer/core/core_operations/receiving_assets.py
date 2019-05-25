from time import time
from functools import partial

from leer.core.utils import DOSException
from leer.core.primitives.block import Block
from leer.core.primitives.header import Header
from leer.core.lubbadubdub.ioput import IOput
from leer.core.primitives.transaction_skeleton import TransactionSkeleton

from leer.core.core_operations.sending_assets import notify_all_nodes_about_tx
from leer.core.core_operations.sending_requests import send_next_headers_request
from leer.core.core_operations.sending_metadata import send_tip_info


def process_new_headers(message, node_info, wtx, core):
  dupplication_header_dos = False #TODO grammatical typo?
  try:
    serialized_headers = message["headers"]
    num = message["num"]
    header = None
    for i in range(num):
      header = Header()
      serialized_headers = header.deserialize_raw(serialized_headers)
      if not core.storage_space.headers_storage.has(header.hash, rtx=wtx):
        core.storage_space.headers_manager.add_header(header, wtx=wtx)
        if not i%20:
          core.notify("best header", core.storage_space.headers_manager.best_header_height)
      else:
        dupplication_header_dos = True
    if ("common_root" in node_info) and ("long_reorganization" in node_info["common_root"]):
        if core.storage_space.headers_manager.get_best_tip()[0] == header.hash:
          #not reorg anymore
          node_info["common_root"].pop("long_reorganization", None)          
          our_tip_hash = core.storage_space.blockchain.current_tip(rtx=wtx)
          core.storage_space.blockchain.update(wtx=wtx, reason="downloaded new headers")
          send_tip_info(node_info=node_info, our_tip_hash=our_tip_hash, rtx=wtx, core=core)
        elif node_info["common_root"]["long_reorganization"]==header.height:
           request_num = min(256, node_info["height"]-core.storage_space.headers_storage.get(node_info["common_root"]["root"], rtx=wtx).height) 
           send_next_headers_request(header.hash,  
                                request_num,
                                message["node"], send = partial(core.send_to_subprocess, "NetworkManager") )
           if node_info["height"]-header.height>request_num:
             node_info["common_root"]["long_reorganization"] = header.height+request_num
           else:
             node_info["common_root"].pop("long_reorganization", None) 
    core.storage_space.blockchain.update(wtx=wtx, reason="downloaded new headers")
  except Exception as e:
    raise DOSException() #TODO add info

def process_new_blocks(message, wtx, core):
  try:
    serialized_blocks = message["blocks"]
    num = message["num"]
    for i in range(num):
      block = Block(storage_space=core.storage_space)
      serialized_blocks = block.deserialize_raw(serialized_blocks)
      core.storage_space.blockchain.add_block(block, wtx=wtx, no_update=True)
      if not i%5:
          core.storage_space.blockchain.update(wtx=wtx, reason="downloaded new blocks")
          core.notify("blockchain height", core.storage_space.blockchain.current_height(rtx=wtx))
    core.storage_space.blockchain.update(wtx=wtx, reason="downloaded new blocks")
    core.notify("blockchain height", core.storage_space.blockchain.current_height(rtx=wtx))
  except Exception as e:
    raise e
    raise DOSException() #TODO add info

def process_new_txos(message, wtx, core):
  try:
    serialized_utxos = bytes(message["txos"])
    txos_hashes = bytes(message["txos_hashes"])
    num = message["num"]
    txos_lengths = message["txos_lengths"]
    txos_hashes = [txos_hashes[i*65:(i+1)*65] for i in range(0,num)]
    txos_lengths = [int.from_bytes(txos_lengths[i*2:(i+1)*2], "big") for i in range(0,num)]
    for i in range(num):
      txo_len, txo_hash = txos_lengths[i], txos_hashes[i]
      if txo_hash in core.storage_space.txos_storage.mempool:
        serialized_utxos = serialized_utxos[txo_len:]
        continue
      utxo = IOput()
      serialized_utxos = utxo.deserialize_raw(serialized_utxos)
      core.storage_space.txos_storage.mempool[utxo.serialized_index]=utxo
    core.storage_space.blockchain.update(wtx=wtx, reason="downloaded new txos")
  except Exception as e:
    raise DOSException() #TODO add info

def process_tbm_tx(message, rtx, core):
  try:
    initial_tbm = core.storage_space.mempool_tx.give_tx()
    tx_skel = TransactionSkeleton()
    tx_skel.deserialize_raw(message['tx_skel'], storage_space = core.storage_space)
    core.storage_space.mempool_tx.add_tx(tx_skel, rtx=rtx)
    final_tbm = core.storage_space.mempool_tx.give_tx()
    if not message["mode"]==0: #If 0 it is response to our request
      if (not initial_tbm) or (not str(initial_tbm.serialize())==str(final_tbm.serialize())):
        notify_all_nodes_about_tx(message['tx_skel'], core, _except=[message["node"]])
  except Exception as e:
    raise DOSException() #TODO add info
