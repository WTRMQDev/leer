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



