from secp256k1_zkp import PrivateKey
from hashlib import sha256

def partial_hash(_bytes):
    assert len(_bytes)>16
    seed1 = _bytes[:-16]
    m1 = sha256()
    m1.update(seed1)
    return m1.digest()

def mining_canary_hash_part(_bytes):
    m2 = sha256()
    m2.update(_bytes)    
    p = PrivateKey(privkey=m2.digest(), raw=True)
    m3 = sha256()
    m3.update(p.pubkey.serialize()[1:])
    return m3.digest()

def mining_canary_hash(_bytes):
    ph = partial_hash(_bytes)
    return mining_canary_hash_part(ph)

