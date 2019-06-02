import shutil, os, time, math
import sqlite3
from hashlib import sha256
from secp256k1_zkp import PrivateKey
from leer.core.lubbadubdub.address import address_from_private_key
from leer.wallet.key_utils import Crypter, encode_int_array, decode_int_array
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
    prk=PrivateKey()
    self._add_privkey_to_pool(prk, cursor)
    privkey = PrivateKey(self._get_privkey_from_pool(cursor), raw=True)
    return address_from_private_key(privkey) 

  def priv_by_address(self, address, cursor):
    pub = self.encrypt_deterministic(address.pubkey.serialize())
    cursor.execute("SELECT privkey from keys where pubkey=?",(pub,))
    res = cursor.fetchone()
    if not len(res):
      raise KeyError("Private key not in the wallet")
    raw_priv = self.decrypt(res[0])
    return PrivateKey(raw_priv, raw=True)

  def add_privkey(self, privkey, cursor, duplicate_safe=False, pool=False):
    pub = self.encrypt_deterministic(privkey.pubkey.serialize())
    priv = self.encrypt(privkey.private_key))
    outputs = self.encrypt(encode_int_array([]))
    if duplicate_safe:
      cursor.execute("SELECT COUNT(*) from keys where pubkey=?",(pub,))
      has_key = cursor.fetchone()[0]
      if has_key:
        return False
    now = time.time()
    cursor.execute("INSERT INTO keys (pubkey, privkey, outputs, created_at, updated_at, pool) VALUE (?, ?, ?, ?, ?, ?)",\
                                     (pub,    priv,    outputs,    now,        now,        pool) )
    return True

  def _add_privkey_to_pool(self, privkey, cursor):
    self.add_privkey(privkey, cursor, duplicate_safe=True, pool=True)

  def _get_privkey_from_pool(self, cursor):
    cursor.execute("SELECT privkey from keys where pool=1 order by id asc limit 1")
    res = cursor.fetchone()
    if not len(res):
      self.fill_pool(cursor, 10)
      return self._get_privkey_from_pool(cursor)
    else:
      return self.decrypt(res[0])

  def fill_pool(self, cursor, keys_number):
    for _ in range(keys_number):
     prk=PrivateKey()
     self._add_privkey_to_pool(prk, cursor)

  def is_unspent(self, output_index, cursor):
    pass

  def is_owned_pubkey(self, serialized_pubkey, cursor):
    pass

  def spend_output(self, index, spend_height, cursor):
    pass

  def _update_outputs_list(self, pubkey, cursor, add=[], remove=[]):
    pub = self.encrypt_deterministic(address.pubkey.serialize())
    cursor.execute("SELECT outputs from keys where pubkey=?",(pub,))
    res = cursor.fetchone()
    if not len(res):
      raise KeyError("Private key not in the wallet")
    outputs = decode_int_array(self.decrypt(res[0]))
    outputs += add
    outputs = [i for i in outputs if not i in remove]
    enc_outputs = self.encrypt(encode_int_array(outputs))
    cursor.execute("UPDATE keys set outputs = ? where pubkey = ?",(enc_outputs, pub))

  def add_output(self, output, created_height, cursor):
    index = self.encrypt_deterministic(output.serialized_index)
    pubkey = output.address.serialized_pubkey
    pubkey_ = self.encrypt(pubkey)
    taddress = self.encrypt(output.address.to_text().encode())
    output.detect_value(inputs_info = 
         {'priv_by_pub':{
                           pubkey : self.priv_by_address(output.address, r_txn=w_txn)
                        }
         }) 
    value = self.encrypt_int(output.value)
    lock_height = self.encrypt_int(output.lock_height)
    created_height_ = self.encrypt_int_deterministic(created_height)
    ser_bl = self.encrypt(output.blinding_key.private_key)
    ser_apc = self.encrypt(output.serialized_apc)
    spent = 0
    cursor.execute("INSERT INTO outputs (output, pubkey, value, lock_height, created_height, ser_blinding_key, ser_apc, taddress, spent) VALUE (?, ?, ?, ?, ?, ?)",\
                                         (index, pubkey_, value, lock_height, created_height_, ser_bl,         ser_apc, taddress, spent))
    self._update_outputs_list(pubkey, cursor, add=[cursor.lastrowid], remove=[]) 


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


