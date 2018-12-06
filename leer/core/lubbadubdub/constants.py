from secp256k1_zkp import GeneratorOnCurve
from hashlib import sha256

seed = "Leer is experimental cryptocurrency implementing LubbaDubDub technology"
def generator_from_string_seed(seed):
  m=sha256()
  m.update(seed.encode())
  bytes_seed = m.digest()
  g = GeneratorOnCurve()
  g._from_seed(bytes_seed)
  g.initialise_bulletproof_generators(128)
  return g

default_generator = generator_from_string_seed(seed)
default_generator_ser=default_generator.serialize()

generators = { default_generator_ser: default_generator}

GLOBAL_TEST = {'utxo set': True, 
'key manager': True,
'lock_height checking':True, 'block_version checking': True, 'inputs index': True,
'skip combined excesses':True, 'skip additional excesses':False, 'spend from mempool':True}
