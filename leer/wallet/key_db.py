import shutil, os, time, math
import sqlite3
import base64
from hashlib import sha256
from secp256k1_zkp import PrivateKey
from leer.core.lubbadubdub.address import address_from_private_key
from leer.wallet.key_utils import Crypter
from functools import partial

class KeyDB:
  """
    KeyDB is sqlite3 database which holds information about private keys, 
    owned outputs and incoming/outcoming transactions.
    Sensitive data may be optionally encrypted with password.
    There is privkey pool: bunch of pregenerated privkeys. It is expected that on a higher level
    instead of generating and immediate usage of new key, new key will be put into the pool and the oldest key
    from the pool will be used. Thus, in case of backups, copies and so on, "old copy" will contain
    some keys used after copy being made.
  """
  def __init__(self, path, password=None):
    self.path = path
    self.crypter = Crypter(password)
    self.encrypt = self.crypter.encrypt
    self.decrypt = self.crypter.decrypt
    self.open = partial(sqlite3.connect, path+"/wallet.sql.db")

  def new_address(self, cursor):
    pass

  def priv_by_address(self, address, cursor):
    pass

  def add_privkey(self, privkey, cursor, duplicate_safe=False):
    pub = base64.b85encode(privkey.pubkey.serialize()).decode('utf8')
    priv = base64.b85encode(self.encrypt(privkey.private_key)).decode('utf8')
    if duplicate_safe:
      cursor.execute("SELECT COUNT(*) from keys where pubkey=?",(pub,))
      has_key = cursor.fetchone()[0]
      if has_key:
        return False
    cursor.execute("INSERT INTO keys VALUE (?, ?, ?, ?, ?)", (pub, priv, "[]", int(time.time()), int(time.time()), ) )
    return True

  def fill_pool(self, cursor, keys_number):
    pass

  def is_unspent(self, output_index, cursor):
    pass

  def is_owned_pubkey(self, serialized_pubkey, cursor):
    pass

  def spend_output(self, index, spend_height, cursor):
    pass

  def add_output(self, output, block_height, cursor):
    pass

  def rollback(self, block_height, cursor):
    pass

  def get_confirmed_balance_stats(self, current_height, cursor):
    pass
    
  def get_confirmed_balance_list(self, current_height, cursor):
    pass

  def give_transactions(self, n, cursor):
    pass

  def save_generated_transaction(self, tx, time, cursor):
    pass

  def is_saved(self, output, cursor):
    pass

  def register_processed_output(self, output_index, block_height, cursor):
    pass


