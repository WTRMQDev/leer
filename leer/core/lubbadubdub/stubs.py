from secp256k1_zkp import PublicKey, PrivateKey
from leer.core.lubbadubdub.constants import GLOBAL_TEST

from leer.core.lubbadubdub.address import Address

'''
#signleton
class KeyManagerClass:
  def __init__(self):
    if not GLOBAL_TEST['key manager']:
      raise NotImplemented
    self.memory={}

  def new_address(self):
    r=PrivateKey()
    self.memory[r.pubkey.serialize()]=r
    return Address().from_private_key(r)

  def priv_by_pub(self, pubkey):
    return self.memory[pubkey.serialize()]

  def priv_by_address(self, address):
    try:
      return self.memory[address.pubkey.serialize()]
    except KeyError:
      return False

  def add_privkey(self, privkey):
    self.memory[privkey.pubkey.serialize()]=privkey

KeyManager=KeyManagerClass()
'''
'''
#signer
KeyManager.add_privkey(PrivateKey(b'%k3\xbe\xb4F\xb1"\x0e\xdd\xad:bC\xae\x98\xbaX\x96dgl\x1f~\xbb\xcdH\x98\x83\xcd&\x9f', raw=True))

#genesis
KeyManager.add_privkey(PrivateKey(b'\xbe\xf2%\x18\xefU\x11\xc3\x86\xe0?.\x8d\xd3\xdf\xb8\xae+\xc2|\x98\x82\xf50\x89>.\xa6\x07\x10\x841', raw=True))
KeyManager.add_privkey(PrivateKey(b'\xbe\xf2%\x18\xefU\x12\xc3\x86\xe0?.\x8d\xd3\xdf\xb8\xae+\xc2|\x98\x82\xf50\x89>.\xa6\x07\x10\x841', raw=True))
KeyManager.add_privkey(PrivateKey(b'\xbe\xf2%\x18\xefU\x13\xc3\x86\xe0?.\x8d\xd3\xdf\xb8\xae+\xc2|\x98\x82\xf50\x89>.\xa6\x07\x10\x841', raw=True))
KeyManager.add_privkey(PrivateKey(b'\xbe\xf2%\x18\xefU\x14\xc3\x86\xe0?.\x8d\xd3\xdf\xb8\xae+\xc2|\x98\x82\xf50\x89>.\xa6\x07\x10\x841', raw=True))

'''
