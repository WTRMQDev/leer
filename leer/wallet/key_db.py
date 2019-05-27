import shutil, os, time, math
import sqlite3
import base64
from hashlib import sha256
from secp256k1_zkp import PrivateKey
from leer.core.lubbadubdub.address import address_from_private_key
from leer.wallet.key_utils import Crypter

class KeyDB:
  """
    New KeyDB which will replace key_manager.
  """
  def __init__(self, path, password=None):
    self.path = path
    self.crypter = Crypter(password)
    self.encrypt = self.crypter.encrypt
    self.decrypt = self.crypter.decrypt

  def new_address(self, cursor):
    pass

  def priv_by_address(self, address, cursor):
    pass

  def add_privkey(self, privkey, cursor):
    pass

  def fill_pool(self, cursor, keys_number=100):
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


