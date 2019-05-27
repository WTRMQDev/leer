import shutil, os, time, math
import sqlite3
import base64
from hashlib import sha256
from secp256k1_zkp import PrivateKey
from leer.core.lubbadubdub.address import address_from_private_key

class KeyDB:
  """
    New KeyDB which will replace key_manager.
  """
  def __init__(self, path, password=None):
    pass
