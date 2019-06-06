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
    index = self.encrypt_deterministic(output_index)
    cursor.execute("SELECT spent from outputs where output=?",(index,))
    res = cursor.fetchone()
    if not len(res):
      raise KeyError("Private key not in the wallet")
    return bool(res[0])

  def is_owned_pubkey(self, serialized_pubkey, cursor):
    pubkey = self.encrypt_deterministic(serialized_pubkey)
    cursor.execute("SELECT privkey from keys where pubkey=?",(pubkey,))
    res = cursor.fetchone()
    if not len(res):
      return False
    return True

  def spend_output(self, output_index, spend_height, cursor):
    index = self.encrypt_deterministic(output_index)
    spent_h = self.encrypt_int_deterministic(spend_height)
    spent = 1
    now = int(time.time())
    cursor.execute("UPDATE outputs set spent_height = ?, spent = ?, updated_at = ? where output = ?",(spent_h, spent, now, index))

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
    cursor.execute("UPDATE keys set outputs = ?, updated_at = ? where pubkey = ?",(enc_outputs, int(time.time()), pub))

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
    cursor.execute("""
                      INSERT INTO outputs 
                       (output, pubkey, value, lock_height, created_height, ser_blinding_key, ser_apc, taddress, spent, updated_at)
                      VALUE
                       (?, ?, ?, ?, ?, ?)""",\
                      (index, pubkey_, value, lock_height, created_height_, ser_bl,         ser_apc, taddress, spent, int(time.time())))
    self._update_outputs_list(pubkey, cursor, add=[cursor.lastrowid], remove=[]) 


  def rollback(self, block_height, cursor):
    height = self.encrypt_int_deterministic(block_height)
    now = int(time.time())
    cursor.execute("""
                   SELECT id, pubkey from outputs where created_height = ?
                   """, (height,))
    res = cursor.fetchall()
    for _id, _pubkey in res:
      pubkey = self.decrypt(_pubkey)
      self._update_outputs_list(pubkey, cursor, add=[], remove=[_id]) #TODO Mass update 
    cursor.execute("""
                   DELETE from outputs where created_height = ?
                   """, (height,))
    cursor.execute("""
                   UPDATE outputs set spent=0, updated_at = ?, spent_height = NULL where spent_height =?
                   """, (now, height))
   

  def get_confirmed_balance_stats(self, current_height, cursor):
    pass
    
  def get_confirmed_balance_list(self, current_height, cursor):
    cursor.execute("""
                   SELECT output, taddress, value, lock_height from outputs where spent = 0
                   """)
    ret = {}
    for output, taddress, value, lock_height in cursor.fetchall():
        output = self.decrypt(output)
        taddress = self.decrypt(taddress)
        value = self.decrypt_int(value)
        lock_height = self.decrypt_int(lock_height)
        taddress = taddress.decode()
        if not current_height>=lock_height:
          continue
        texted_index = base64.b64encode(output_index).decode()
        if not taddress in ret:
            ret[taddress]={}
        if value:
            ret[taddress][texted_index]=value
        else:
            ret[taddress][texted_index]='unknown'      
    return ret

  def give_transactions(self, n, cursor):
    pass

  def save_generated_transaction(self, tx, time, cursor):
    pass

  def is_saved(self, output, cursor):
    pass

  def register_processed_output(self, output_index, block_height, cursor):
    pass


