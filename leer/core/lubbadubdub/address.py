from secp256k1_zkp import PublicKey, ALL_FLAGS
from leer.core.lubbadubdub.constants import GLOBAL_TEST
import hashlib, base64

class Excess:
    '''
    Excess is public key with proof that it is public key (signature).
    '''

    def __init__(self, recoverable_signature=None, message=b'', version=0, raw=None):
        self.recoverable_signature = recoverable_signature
        self.message = message
        self.version = version
        if raw:
          self.deserialize_raw(raw)

    @property
    def pubkey(self):
        unrelated = PublicKey(flags=ALL_FLAGS)
        return PublicKey(pubkey=unrelated.ecdsa_recover(self.message, self.recoverable_signature))      
        

    def from_private_key(self, privkey, message=b'', version=None):
        self.message = message if message else self.message
        if version:
          self.version = version
        else: 
         if self.message==b"":
           self.version = 0
         else:
           self.version = 1
        self.recoverable_signature = privkey.ecdsa_sign_recoverable(self.message)
        
        return self

    @property
    def nonrec_signature(self):
        unrelated = PublicKey(flags=ALL_FLAGS)
        return unrelated.ecdsa_recoverable_convert(self.recoverable_signature)

    def verify(self):
        return self.pubkey.ecdsa_verify(self.message, self.nonrec_signature)

    def serialize(self):
        if self.version==0 and len(self.message):
          raise

        unrelated = PublicKey(flags=ALL_FLAGS)
        if self.version==0:
          return unrelated.ecdsa_recoverable_serialize_raw(self.recoverable_signature)
        if self.version==1:
          rec_sig_serialized = unrelated.ecdsa_recoverable_serialize_raw(self.recoverable_signature)
          rec_sig_serialized = (rec_sig_serialized[0] | 128).to_bytes(1,"big") + rec_sig_serialized[1:]
          mes_serialized = len(self.message).to_bytes(2,"big")+self.message
          return rec_sig_serialized+mes_serialized

    def deserialize_raw(self, serialized_data):
        if len(serialized_data)<65:
          raise Exception("Not enough bytes to encode recovery signature")
        rec_sig, serialized_data = serialized_data[:65], serialized_data[65:]
        unrelated = PublicKey(flags=ALL_FLAGS)
        if rec_sig[0] & 128 ==0:
          self.version = 0
          self.message = b""
          self.recoverable_signature = unrelated.ecdsa_recoverable_deserialize_raw(rec_sig)
        if rec_sig[0] & 128 ==128:
          self.version = 1
          rec_sig = (rec_sig[0] - 128).to_bytes(1,"big") + rec_sig[1:]
          self.recoverable_signature = unrelated.ecdsa_recoverable_deserialize_raw(rec_sig)
          if len(serialized_data)<2:
            raise Exception("Not enough bytes to encode message len")
          mlen_ser, serialized_data = serialized_data[:2], serialized_data[2:]
          mlen = int.from_bytes(mlen_ser, 'big')
          if len(serialized_data)<mlen:
            raise Exception("Not enough bytes to encode message") 
          self.message, serialized_data = serialized_data[:mlen], serialized_data[mlen:]
        return serialized_data      

    @property
    def index(self):
      """
        Special index which is used for building excess merkle tree.
        As well as in tree for outputs we both want be able access to summ
        of excesses as summ of points on curve and validate tree. Thus index
        contain public key and hash of serialized excess
      """
      m=hashlib.sha256()
      m.update(self.serialize())
      return self.pubkey.serialize() + m.digest()

class Address(Excess):

    def verify(self):
        return super().verify() and (self.message==b"")


    def from_text(self, serialized):
      _address = Address()
      raw = base64.b64decode(serialized.encode())
      self.deserialize_raw(raw[:-4])
      m=hashlib.sha256()
      m.update(raw[:-4])
      checksum = m.digest()[:4]
      assert checksum==raw[-4:]
      self = _address
      return True

    def to_text(self):
      m=hashlib.sha256()
      m.update(self.serialize())
      checksum = m.digest()[:4]
      return base64.b64encode(self.serialize()+checksum).decode()

    '''
    def __init__(self, pubkey=None, signature=None, rec_sig=None, raw=False):
        self.pubkey = pubkey
        self.signature = signature
        if rec_sig:
          if raw:
            self.deserialize(rec_sig)
          else:
            self.from_recoverable_signature(rec_sig)
	
    def from_b58(self, _adr):
        pass

    def to_b58(self, _adr):
        pass

    def from_recoverable_signature(self, rec_sig):
        unrelated = PublicKey(flags=ALL_FLAGS)
        #rec_sig, rec_id = unrelated.ecdsa_recoverable_serialize(raw_rec_sig)
        self.pubkey = PublicKey(pubkey=unrelated.ecdsa_recover(b"", rec_sig))
        self.signature = unrelated.ecdsa_recoverable_convert(rec_sig)
        self.rec_sig = rec_sig

    def from_private_key(self, privkey):
        rec_sig = privkey.ecdsa_sign_recoverable(b"")
        self.from_recoverable_signature(rec_sig)
        return self

    def verify(self):
        unrelated = PublicKey(flags=ALL_FLAGS)
        return self.pubkey.ecdsa_verify(b"", self.signature)

    def serialize(self):
        unrelated = PublicKey(flags=ALL_FLAGS)
        return unrelated.ecdsa_recoverable_serialize_raw(self.rec_sig)

    def deserialize(self, ser_rec_sig):
        unrelated = PublicKey(flags=ALL_FLAGS)
        self.from_recoverable_signature(unrelated.ecdsa_recoverable_deserialize_raw(ser_rec_sig))
    '''


def excess_from_private_key(private_key, apc):
  e= Excess(message=apc)
  e.from_private_key(private_key)
  return e

def address_from_private_key(private_key):
  a= Address(message=b"")
  a.from_private_key(private_key)
  return a



#class Excess(Address, PublicKey):
#    def from_address(self, adr):
#        PublicKey.__init__(self, pubkey=adr.pubkey.public_key, raw=False)


