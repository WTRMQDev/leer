import shutil, os, time, math
import sqlite3
from hashlib import sha256
from secp256k1_zkp import PrivateKey
from leer.core.lubbadubdub.address import address_from_private_key
from leer.wallet.key_utils import Crypter, encode_int_array, decode_int_array
from functools import partial
import base64

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
    if not os.path.exists(path):
        os.makedirs(self.path)
    self.open = partial(sqlite3.connect, path+"/wallet.sql.db")

  def new_address(self, cursor):
    prk=PrivateKey()
    self._add_privkey_to_pool(prk, cursor)
    privkey = PrivateKey(self._get_privkey_from_pool(cursor), raw=True)
    return address_from_private_key(privkey) 

  def _ser_priv_by_ser_pub(self, ser_pub, cursor):
    pub = self.crypter.encrypt_deterministic(ser_pub)
    cursor.execute("SELECT privkey from keys where pubkey=?",(pub,))
    res = cursor.fetchone()
    if (not res) or (not len(res)):
      raise KeyError("Private key not in the wallet")
    raw_priv = self.crypter.decrypt(res[0])
    return raw_priv

  def priv_by_address(self, address, cursor):
    ser_pub = address.serialized_pubkey
    raw_priv = self._ser_priv_by_ser_pub(ser_pub, cursor)
    return PrivateKey(raw_priv, raw=True)

  def add_privkey(self, privkey, cursor, duplicate_safe=False, pool=False):
    pub = self.crypter.encrypt_deterministic(privkey.pubkey.serialize())
    priv = self.crypter.encrypt(privkey.private_key)
    outputs = self.crypter.encrypt(encode_int_array([]))
    if duplicate_safe:
      cursor.execute("SELECT COUNT(*) from keys where pubkey=?",(pub,))
      has_key = cursor.fetchone()[0]
      if has_key:
        return False
    now = time.time()
    cursor.execute("INSERT INTO keys (pubkey, privkey, outputs, created_at, updated_at, pool) VALUES (?, ?, ?, ?, ?, ?)",\
                                     (pub,    priv,    outputs,    now,        now,        pool) )
    return True

  def _add_privkey_to_pool(self, privkey, cursor):
    self.add_privkey(privkey, cursor, duplicate_safe=True, pool=True)

  def _get_privkey_from_pool(self, cursor):
    cursor.execute("SELECT id, privkey from keys where pool=1 order by id asc limit 1")
    res = cursor.fetchone()
    if (not res) or (not len(res)):
      self.fill_pool(cursor, 10)
      return self._get_privkey_from_pool(cursor)
    else:
      cursor.execute("UPDATE keys set pool=0 where id = ?", (res[0],))
      return self.crypter.decrypt(res[1])

  def fill_pool(self, cursor, keys_number):
    for _ in range(keys_number):
     prk=PrivateKey()
     self._add_privkey_to_pool(prk, cursor)

  def is_unspent(self, output_index, cursor):
    index = self.crypter.encrypt_deterministic(output_index)
    cursor.execute("SELECT spent from outputs where output=?",(index,))
    res = cursor.fetchone()
    if (not res) or (not len(res)):
      return False
    return not bool(res[0])

  def is_owned_pubkey(self, serialized_pubkey, cursor):
    pubkey = self.crypter.encrypt_deterministic(serialized_pubkey)
    cursor.execute("SELECT privkey from keys where pubkey=?",(pubkey,))
    res = cursor.fetchone()
    if (not res) or (not len(res)):
      return False
    return True

  def spend_output(self, output_index, spend_height, cursor):
    index = self.crypter.encrypt_deterministic(output_index)
    spent_h = self.crypter.encrypt_int_deterministic(spend_height)
    spent = 1
    now = int(time.time())
    cursor.execute("UPDATE outputs set spent_height = ?, spent = ?, updated_at = ? where output = ?",(spent_h, spent, now, index))
    print("spend ", output_index)

  def _update_outputs_list(self, serialiazed_pubkey, cursor, add=[], remove=[]):
    pub = self.crypter.encrypt_deterministic(serialiazed_pubkey)
    cursor.execute("SELECT outputs from keys where pubkey=?",(pub,))
    res = cursor.fetchone()
    if (not res) or (not len(res)):
      raise KeyError("Private key not in the wallet")
    outputs = decode_int_array(self.crypter.decrypt(res[0]))
    outputs += add
    outputs = [i for i in outputs if not i in remove]
    enc_outputs = self.crypter.encrypt(encode_int_array(outputs))
    cursor.execute("UPDATE keys set outputs = ?, updated_at = ? where pubkey = ?",(enc_outputs, int(time.time()), pub))

  def add_output(self, output, created_height, cursor):
    index = self.crypter.encrypt_deterministic(output.serialized_index)
    pubkey = output.address.serialized_pubkey
    pubkey_ = self.crypter.encrypt(pubkey)
    taddress = self.crypter.encrypt(output.address.to_text().encode())
    output.detect_value(inputs_info = 
         {'priv_by_pub':{
                           pubkey : self.priv_by_address(output.address, cursor)
                        }
         }) 
    value = self.crypter.encrypt_int(output.value)
    lock_height = self.crypter.encrypt_int(output.lock_height)
    created_height_ = self.crypter.encrypt_int_deterministic(created_height)
    ser_bl = self.crypter.encrypt(output.blinding_key.private_key)
    ser_apc = self.crypter.encrypt(output.serialized_apc)
    spent = 0
    now =  int(time.time())
    cursor.execute("""
                      INSERT INTO outputs 
                       (output, pubkey, amount, lock_height, created_height, ser_blinding_key, ser_apc, taddress, spent, created_at, updated_at)
                      VALUES
                       (?,      ?,      ?,     ?,           ?,              ?,                ?,       ?,        ?,     ?,          ?)""",\
                      (index, pubkey_, value, lock_height, created_height_, ser_bl,         ser_apc, taddress, spent,   now,         now))
    self._update_outputs_list(pubkey, cursor, add=[cursor.lastrowid], remove=[]) 

  def get_output_private_data(self, _index, cursor):
    output_index = self.crypter.encrypt_deterministic(_index)
    cursor.execute("""
                   SELECT pubkey, ser_blinding_key, ser_apc from outputs where output = ?
                   """, (output_index,))
    res = cursor.fetchone()
    en_pub, en_ser_blinding, en_apc = res
    ser_pub, ser_blinding, ser_apc = self.crypter.decrypt(en_pub), \
                                     self.crypter.decrypt(en_ser_blinding), \
                                     self.crypter.decrypt(en_apc)
    ser_priv = self._ser_priv_by_ser_pub(ser_pub, cursor)
    return ser_priv, ser_blinding, ser_apc
    


  def rollback(self, block_height, cursor):
    height = self.crypter.encrypt_int_deterministic(block_height)
    now = int(time.time())
    cursor.execute("""
                   SELECT id, pubkey from outputs where created_height = ?
                   """, (height,))
    res = cursor.fetchall()
    for _id, _pubkey in res:
      pubkey = self.crypter.decrypt(_pubkey)
      self._update_outputs_list(pubkey, cursor, add=[], remove=[_id]) #TODO Mass update 
    cursor.execute("""
                   DELETE from outputs where created_height = ?
                   """, (height,))
    cursor.execute("""
                   UPDATE outputs set spent=0, updated_at = ?, spent_height = NULL where spent_height =?
                   """, (now, height))
   

  def get_confirmed_balance_stats(self, current_height, cursor):
    stats = {
              'matured': {'known_value':0, 'known_count':0, 'unknown_count':0},
              'immatured': {'known_value':0, 'known_count':0, 'unknown_count':0}
            }
    cursor.execute("""
                   SELECT output, taddress, amount, lock_height from outputs where spent = 0
                   """)
    ret = {}
    for output, taddress, value, lock_height in cursor.fetchall():
        output = self.crypter.decrypt(output)
        taddress = self.crypter.decrypt(taddress)
        value = self.crypter.decrypt_int(value)
        lock_height = self.crypter.decrypt_int(lock_height)
        taddress = taddress.decode()
        mat = None
        if current_height>=lock_height:
          mat = 'matured'
        else:
          mat = 'immatured'
        if value:
          stats[mat]['known_value']+=value
          stats[mat]['known_count']+=1
        else:
          stats[mat]['unknown_count']+=1        
    return stats
    
  def get_confirmed_balance_list(self, current_height, cursor):
    cursor.execute("""
                   SELECT output, taddress, amount, lock_height from outputs where spent = 0
                   """)
    ret = {}
    for output, taddress, value, lock_height in cursor.fetchall():
        output_index = self.crypter.decrypt(output)
        taddress = self.crypter.decrypt(taddress)
        value = self.crypter.decrypt_int(value)
        lock_height = self.crypter.decrypt_int(lock_height)
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
    txdict = {} #Each element is dict {block_num: {'output':{params}}}
    cursor.execute("""
                   SELECT output, taddress, amount, lock_height, spent, created_height, spent_height, created_at, updated_at
                    from outputs order by updated_at desc
                   """)  
    already_processed_blocks = []
    for output, taddress, value, lock_height, spent, created_height, spent_height, created_at, updated_at in cursor.fetchall():
        if len(already_processed_blocks)>=n:
          break
        output_index = self.crypter.decrypt(output)
        taddress = self.crypter.decrypt(taddress)
        value = self.crypter.decrypt_int(value)
        lock_height = self.crypter.decrypt_int(lock_height)
        created_height = self.crypter.decrypt_int(created_height)
        spent_height = self.crypter.decrypt_int(spent_height) if spent_height else False

        taddress = taddress.decode()
        soi = base64.b64encode(output_index).decode()
        current_height = spent_height if spent else created_height
        if not current_height in txdict:
          txdict[current_height] = {}
        if spent:
          txdict[current_height][soi] = {'lock_height':lock_height, 'value':value, 'address':taddress, 'type':'spent'}
        else:
          txdict[current_height][soi] = {'lock_height':lock_height, 'value':value, 'address':taddress, 'type':'received'}
          if not created_at == updated_at:
            #this output was already spent and then rollback occured. We can not trust updated_at ordering here
            continue
        if not current_height in already_processed_blocks:
            already_processed_blocks.append(current_height)
            continue
    return txdict
          

  def save_generated_transaction(self, tx, cursor):
    '''
      Save transaction generated by wallet, thus then this tx will be found in block
      wallet will note outgoing payment.
    '''
    for o in tx.outputs:
      index = self.crypter.encrypt_deterministic(o.serialized_index)
      pubkey = o.address.serialized_pubkey
      pubkey_ = self.crypter.encrypt(pubkey)
      taddress = self.crypter.encrypt(o.address.to_text().encode())
      value = self.crypter.encrypt_int(o.value)
      lock_height = self.crypter.encrypt_int(o.lock_height)
      ser_bl = self.crypter.encrypt(o.blinding_key.private_key)
      ser_apc = self.crypter.encrypt(o.serialized_apc)
      confirmed = 0
      now =  int(time.time())
      cursor.execute("""
                      INSERT INTO outgoing_outputs
                       (output, pubkey, amount, lock_height, ser_blinding_key, ser_apc, taddress, confirmed, created_at, updated_at)
                      VALUES
                       (?,      ?,      ?,     ?,           ?,                ?,       ?,        ?,     ?,          ?)""",\
                      (index, pubkey_, value, lock_height, ser_bl,            ser_apc, taddress, confirmed,   now,         now))




  def is_saved(self, output, cursor):
    index = self.crypter.encrypt_deterministic(output.serialized_index)
    cursor.execute("SELECT output from outgoing_outputs where output=?",(index,))
    res = cursor.fetchone()
    if res and bool(len(res)):
      return True
    return False

  def register_processed_output(self, output_index, block_height, cursor):
    index = self.crypter.encrypt_deterministic(output_index)
    created_height = self.crypter.encrypt_int_deterministic(block_height)
    cursor.execute("UPDATE outgoing_outputs set created_height = ?, confirmed = 1 where output=?", (created_height, index))
    

