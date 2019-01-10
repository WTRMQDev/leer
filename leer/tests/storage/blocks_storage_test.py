import shutil, os, time
from secp256k1_zkp import PrivateKey

from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Address
from leer.tests.storage.storage_for_test import TXOsStorage, wipe_test_dirs
from leer.core.storage.blocks_storage import RollBack


import random, os

def test_rollback_obj():
  for i in range(10):
    a=RollBack()
    b=RollBack()
    a.prev_state = os.urandom(random.randint(0,int(65)))
    for i in range(random.randint(0,2000)):
      a.pruned_inputs.append( [[random.randint(0,int(1e8)), b"\x03"*random.randint(0,int(100)), b"\xff"*random.randint(0,int(1000))]]*2 )
      a.pruned_inputs.append( [[0, b"", b""]]*2 )
    a.num_of_added_outputs=3
    a.num_of_added_excesses=0
    assert not len(b.deserialize_raw(a.serialize()))
    assert a.pruned_inputs ==b.pruned_inputs
    assert a.num_of_added_outputs == b.num_of_added_outputs
    assert a.num_of_added_excesses == b.num_of_added_excesses

  print("test_rollback_obj OK")




