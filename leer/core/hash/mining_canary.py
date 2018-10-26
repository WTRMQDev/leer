from secp256k1_zkp import PrivateKey
from hashlib import sha256

def mining_canary_hash(_bytes):
    m = sha256()
    m.update(_bytes)
    p = PrivateKey(privkey=m.digest(), raw=True)
    m2 = sha256()
    m2.update(p.pubkey.serialize()[1:])
    return m2.digest()
