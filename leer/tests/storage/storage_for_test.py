from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.chains.headers_manager import HeadersManager
from leer.core.storage.blocks_storage import BlocksStorage
from leer.core.chains.blockchain import Blockchain


from leer.core.lubbadubdub.transaction import Transaction
from leer.core.primitives.block import Block
from leer.core.primitives.block import ContextBlock
from leer.core.primitives.block import generate_genesis
from leer.core.storage.mempool_tx import MempoolTx
from leer.core.storage.utxo_index_storage import UTXOIndex

from leer.core.storage.storage_space import StorageSpace
import shutil, time, os

home = os.path.expanduser("~")
base_path = os.path.join(home, ".testleer")


def wipe_test_dirs():
  shutil.rmtree(base_path, True)


def rebuild_test_storage_space(path=base_path):
  global test_storage_space
  if not os.path.exists(path): 
      os.makedirs(path) #TODO catch

  try:
    if test_storage_space:
      del test_storage_space      
  except NameError:
    pass #it's ok: test_storage_space wasn't defined yet

  wipe_test_dirs()
  test_storage_space = StorageSpace(path)
  with test_storage_space.env.begin(write=True) as wtx:
    env = test_storage_space.env
    hs = HeadersStorage(test_storage_space, wtx)
    hm = HeadersManager(test_storage_space, do_not_check_pow=True)
    bs = BlocksStorage(test_storage_space, wtx)
    es = ExcessesStorage(test_storage_space, wtx)
    ts = TXOsStorage(test_storage_space, wtx)
    bc = Blockchain(test_storage_space)
    mptx = MempoolTx(test_storage_space)
    utxoi = UTXOIndex(test_storage_space, wtx)
  def f(smth):
    pass
  bc.ask_for_blocks_hook = f
  bs.ask_for_txouts_hook = f
  return test_storage_space

test_storage_space=rebuild_test_storage_space()

