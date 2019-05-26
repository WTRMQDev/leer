from leer.core.chains.headers_manager import HeadersManager
from leer.core.chains.blockchain import Blockchain
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.storage.blocks_storage import BlocksStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.utxo_index_storage import UTXOIndex
from leer.core.storage.mempool_tx import MempoolTx
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

from leer.syncer import Syncer
from leer.core.parameters.constants import serialized_genesis_block

from secp256k1_zkp import PrivateKey

import logging
from functools import partial
from ipaddress import ip_address

logger = logging.getLogger("core_loop")


from os.path import *

config = {
            'location': {
                         'basedir': join(expanduser("~"), ".leertest4_nopow2"),
                         'wallet': join(expanduser("~"), ".leertestwallet4")
                       },
           'wallet' : True  }




def init_blockchain(rtx):
  '''
    If blockchain is empty this function will set genesis.
  '''
  genesis = Block(storage_space = storage_space)
  genesis.deserialize(serialized_genesis_block)
  storage_space.headers_manager.set_genesis(genesis.header, wtx=rtx)
  storage_space.headers_manager.best_tip = (storage_space.blockchain.current_tip(rtx=rtx), storage_space.blockchain.current_height(rtx=rtx) )
  logger.info("Best header tip from blockchain state %d"%storage_space.headers_manager.best_tip[1])
  #greedy search
  current_tip = storage_space.headers_manager.best_tip[0]
  while True:
      try:
        header = storage_space.headers_storage.get(current_tip, rtx=rtx)
      except KeyError:
        break
      new_current_tip=current_tip
      if len(header.descendants):
        for d in header.descendants:
          dh = storage_space.headers_storage.get(d, rtx=rtx)
          if not dh.invalid:
            new_current_tip = d
            break
      if not new_current_tip == current_tip:
        current_tip=new_current_tip
      else:
        break
  storage_space.headers_manager.best_tip = (current_tip, storage_space.headers_storage.get(current_tip, rtx=rtx).height)
  logger.info("Best header tip after greedy search %d"%storage_space.headers_manager.best_tip[1])


_path = config["location"]["basedir"]
storage_space=StorageSpace(_path)
rtx = storage_space.env.begin(write=True)
hs = HeadersStorage(storage_space, wtx=rtx)
hm = HeadersManager(storage_space)
bs = BlocksStorage(storage_space, wtx=rtx)
es = ExcessesStorage(storage_space, wtx=rtx)
ts = TXOsStorage(storage_space, wtx=rtx)
bc = Blockchain(storage_space)
#mptx = MempoolTx(storage_space)
utxoi = UTXOIndex(storage_space, wtx=rtx)
init_blockchain(rtx)

def detect_fork_length(header):
  desc = header.descendants
  while len(desc):
    next_desc = []
    for d in desc:
      h=hs.get(d, rtx)
      for d2 in h.descendants:
        next_desc.append(d2)
    if len(next_desc):
      desc=next_desc
    else:
      break
  best=hs.get(list(desc[0]), rtx)
  return best.height-header.height
    

print("Start analysis")

current_header_height = 0
headers = hs.get_headers_hashes_at_height(current_header_height, rtx=rtx)
finish = False
while True:
  for h in headers:
    h=hs.get(h, rtx)
    try:
      if not bc.is_block_in_main_chain(h.hash, rtx):
        fork_len = detect_fork_length(h)
        validity = "invalid(%s)"%h.reason if h.invalid else "valid"
        print("Fork with length %d detected at height %d; %s"%(fork_len, h.height, validity))
      else:
        next_header_hash = h.hash
    except:
      print("Analysis is finished at height %d"%h.height)
      finish = True
  if finish:
    break
  try:
    next_header = hs.get(next_header_hash, rtx)
    headers = next_header.descendants
    assert len(headers)
    if not h.height%250:
      print("Analysis has reached %d height"%h.height)
  except Exception as e:
    print("Analysis is finished at height %d"%h.height)
    break

print("Ok")


