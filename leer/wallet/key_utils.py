from chacha20poly1305 import ChaCha20Poly1305
from leer.core.utils import sha256
from os import urandom
from base64 import b85encode, b85decode

class Crypter:

  def __init__(self, password):
    self.aead = None
    self.password = password
    if self.password:
      self.raw_private_key = sha256(self.password.encode("utf-8"))
      self.aead = ChaCha20Poly1305(self.raw_private_key, 'python')

  def encrypt(self, payload, nonce=None):
    if self.aead:
      if not nonce:
        nonce = urandom(12)
      return b85encode(nonce+self.aead.seal(nonce, payload, b'')).decode('utf8')
    else:
      return b85encode(payload).decode('utf8')

  def deterministic_nonce(self, payload):
    return sha256(payload+self.raw_private_key)[:12] if self.password else None

  def encrypt_deterministic(self, payload):
    nonce = self.deterministic_nonce(payload)
    return self.encrypt(payload, nonce=nonce)

  def decrypt(self, ciphertext):
    ciphertext_bytes = b85decode(ciphertext.encode('utf8'))
    if self.aead:
      return bytes(self.aead.open(ciphertext_bytes[:12], ciphertext_bytes[12:], b''))
    else:
      return ciphertext_bytes

  def encrypt_int(self, payload, size=8):
    return self.encrypt(payload.to_bytes(size, "big"))

  def encrypt_int_deterministic(self, payload, size=8):
    _payload = payload.to_bytes(size, "big")
    return self.encrypt(_payload, self.deterministic_nonce(_payload))

  def decrypt_int(self, ciphertext):
    return int.from_bytes(self.decrypt(ciphertext), "big")


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
  len_buf,encoded_data = encoded_data[:2], encoded_data[2:]
  l = int.from_bytes(len_buf, "big")
  ret = []
  for i in range(l):
    buf, encoded_data = encoded_data[:4],encoded_data[4:]
    ret.append(int.from_bytes(buf, "big"))
  return ret
