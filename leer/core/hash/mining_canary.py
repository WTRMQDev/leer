from secp256k1_zkp import PrivateKey
from hashlib import sha256

def partial_hash(_bytes):
    assert len(_bytes)>16
    seed1 = _bytes[:-16]
    m1 = sha256()
    m1.update(seed1)
    return m1.digest()

def mining_canary_hash(_bytes):
    seed2 = partial_hash(_bytes)
    m2 = sha256()
    m2.update(seed2+_bytes[-16:])    
    p = PrivateKey(privkey=m2.digest(), raw=True)
    m3 = sha256()
    m3.update(p.pubkey.serialize()[1:])
    return m3.digest()
