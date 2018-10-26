from secp256k1_zkp import GeneratorOnCurve

default_generator = GeneratorOnCurve()
default_generator._from_seed(b'\x03\x07\x11'+b'\xfa'*29)
default_generator_ser=default_generator.serialize()

generators = { default_generator_ser: default_generator}

GLOBAL_TEST = {'utxo set': True, 
'key manager': True,
'lock_height checking':True, 'block_version checking': True, 'inputs index': True,
'skip combined excesses':True, 'skip additional excesses':False, 'spend from mempool':True}
