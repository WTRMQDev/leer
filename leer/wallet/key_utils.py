from chacha20poly1305 import ChaCha20Poly1305
from leer.core.utils import sha256
from os import urandom

class Crypter:
  def __init__(self, password):
    self.aead = None
    self.password = password
    if self.password:
      raw_private_key = sha256(self.password.encode("utf-8"))
      self.aead = ChaCha20Poly1305(raw_private_key, 'python')
  def encrypt(self, payload):
    if self.aead:
      nonce = urandom(12)
      return nonce+self.aead.seal(nonce, payload, b'')
    else:
      return payload
  def decrypt(self, ciphertext):
    if self.aead:
      return bytes(self.aead.open(ciphertext[:12], ciphertext[12:], b''))
    else:
      return ciphertext



def encode_int_array(array):
  ret = b""
  l = len(array)
  if l> 256**3-1:
    raise Exception("Too big array, len: %d"%l)
  ret+=l.to_bytes(3,"big")
  for i in array:
    if i>256**4-1:
      raise Exception("Member of array is too high to be encoded"%i)
    ret+=i.to_bytes(4,"big")
  return ret

def decode_int_array(encoded_data):
  len_buf,encoded_data = encoded_data[:2]
  l = int.from_bytes(len_buf, "big")
  ret = []
  for i in range(l):
    buf, encoded_data = encoded_data[:4],encoded_data[4:]
    ret.append(int.from_bytes(buf, "big"))
  return ret
