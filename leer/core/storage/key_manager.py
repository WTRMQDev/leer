#from leer.core.storage.txos_storage import TXOsStorage
from secp256k1_zkp import PrivateKey
from leer.core.storage.default_paths import key_manager_path
import shutil, os, time, lmdb, math
from hashlib import sha256
from leer.core.lubbadubdub.address import address_from_private_key
import base64

class KeyManagerClass:
  def __init__(self, password=None, path = key_manager_path):
    #self.privkey = None
    #if password:
    #  password_bytes = bytes(password+")dod8q=(3fnS#904ff", "utf-16")
    #  m = sha256()
    #  m.update(password_bytes)
    #  self.privkey = Privkey(m.digest(), raw=True)
    self.wallet = DiscWallet(dir_path=path)

  def new_address(self):
    prk=PrivateKey()
    self.wallet.add_privkey_to_pool(prk.pubkey.serialize(), prk.private_key)
    privkey = PrivateKey(self.wallet.get_privkey_from_pool(), raw=True)
    return address_from_private_key(privkey) 

  def priv_by_pub(self, pubkey):
    raw_priv = self.wallet.get_privkey(pubkey.serialize())
    if not raw_priv:
      raise KeyError("Private key not in the wallet")
    return PrivateKey(raw_priv, raw=True)

  def priv_by_address(self, address):
    raw_priv = self.wallet.get_privkey(address.pubkey.serialize())
    if not raw_priv:
      raise KeyError("Private key not in the wallet")
    return PrivateKey(raw_priv, raw=True)

  def add_privkey(self, privkey):
    self.wallet.put(privkey.pubkey.serialize(), privkey.private_key)

  def fill_pool(self, keys_number=100):
    for _ in range(keys_number):
     prk=PrivateKey()
     self.wallet.add_privkey_to_pool(prk.pubkey.serialize(), prk.private_key)

  @property
  def pool_size(self):
    raw_pool_size = self.wallet.get_pool_size()
    if raw_pool_size:
      return int.from_bytes(self.wallet.get_pool_size(), "big") 
    else: #NoneType
      return 0

  def get_confirmed_balance_stats(self, utxo_index, txos_storage, current_height):
    stats = {
              'matured': {'known_value':0, 'known_count':0, 'unknown_count':0},
              'immatured': {'known_value':0, 'known_count':0, 'unknown_count':0}
            }
    with self.wallet.env.begin(write=False) as txn:
      cursor = txn.cursor(db=self.wallet.main_db)
      for ser_pub in cursor.iternext(keys=True, values=False):
        for output_index in utxo_index.get_all_unspent_for_serialized_pubkey(ser_pub):
          utxo = txos_storage.confirmed[output_index]
          if utxo.detect_value(self):
            if current_height>=utxo.lock_height:
              stats['matured']['known_value']+=utxo.value
              stats['matured']['known_count']+=1
            else:
              stats['immatured']['known_value']+=utxo.value
              stats['immatured']['known_count']+=1
          else:
            if current_height>=utxo.lock_height:
              stats['matured']['unknown_count']+=1
            else:
              stats['immatured']['unknown_count']+=1
    return stats

  def get_confirmed_balance_list(self, utxo_index, txos_storage, current_height):
    ret = {}
    with self.wallet.env.begin(write=False) as txn:
      cursor = txn.cursor(db=self.wallet.main_db)
      for ser_pub, priv in cursor.iternext(keys=True, values=True):
        address = address_from_private_key(PrivateKey(priv, raw=True))
        taddress = address.to_text()
        for output_index in utxo_index.get_all_unspent_for_serialized_pubkey(ser_pub):
          utxo = txos_storage.confirmed[output_index]
          texted_index = base64.b64encode(utxo.serialized_index).decode()
          if not taddress in ret:
            ret[taddress]={}
          if utxo.detect_value(self):
            ret[taddress][texted_index]=utxo.value
          else:
            ret[taddress][texted_index]='unknown'
    return ret

class DiscWallet:
  '''
    It is generally key-value db: key is serialized pubkey, value - serialized privkey.
    There is privkey pool: bunch of pregenerated privkeys. It is expected that on higher level
    instead of generating and immediate usage of new key, new key will be put into pool and the oldest key
    from pool will be used. Thus, in case of backups, copies and so on, "old copy" will contain
    some keys used after copy being made.
  '''
  def __init__(self, dir_path):
    self.dir_path = dir_path

    if not os.path.exists(self.dir_path): 
        os.makedirs(self.dir_path) #TODO catch
    self.env = lmdb.open(self.dir_path, max_dbs=10)
    with self.env.begin(write=True) as txn:
      self.main_db = self.env.open_db(b'main_db', txn=txn, dupsort=False)
      self.pool = self.env.open_db(b'pool', txn=txn, dupsort=False)
      #if not txn.get(b'pool_size', db=self.pool):
      #  txn.put( b'pool_size', 0, db=self.pool) 

  def get_pool_prop(self, prop, txn = None):
    if not txn:
      with self.env.begin(write=False) as txn:
        return self.get_pool_prop(prop, txn)
    else:
      return txn.get( prop, db=self.pool) 

  def get_pool_size(self,txn=None):
    return self.get_pool_prop(b'size', txn=txn)

  def get_pool_current(self,txn=None):
    return self.get_pool_prop(b'current', txn=txn)

  def get_pool_top(self,txn=None):
    return self.get_pool_prop(b'top', txn=txn)

  def set_pool_prop(self, prop, value, txn = None):
    if not txn:
      with self.env.begin(write=True) as txn:
        return self.set_pool_prop(prop, value)
    else:
      if not value==None:
        return txn.put( prop, value.to_bytes(4,'big'), db=self.pool) 
      else:
        return txn.delete( prop, db=self.pool) 

  def set_pool_size(self, value, txn=None):
    return self.set_pool_prop(b'size', value, txn=txn)

  def set_pool_current(self, value, txn=None):
    return self.set_pool_prop(b'current', value, txn=txn)

  def set_pool_top(self, value, txn=None):
    return self.set_pool_prop(b'top', value, txn=txn)



  def put(self, serialized_pubkey, serialized_privkey, txn=None):
    if not txn:
      with self.env.begin(write=True) as txn:
        self.put(serialized_pubkey, serialized_privkey, txn=txn)
    else:
      p1=txn.put( bytes(serialized_pubkey), bytes(serialized_privkey), db=self.main_db)    
  
  def get_privkey_from_pool(self):
    '''
      Privkey will be immideately removed from pool.
    '''
    with self.env.begin(write=True) as txn:
        # pool is integer->pubkey key_value
        current = self.get_pool_current(txn=txn)
        if not current:
          raise Exception("Pool is empty")
        privkey = txn.get( txn.get(current, db=self.pool), db=self.main_db)
        current_int = int.from_bytes(current, 'big')
        top_int = int.from_bytes(self.get_pool_top(txn=txn), 'big')
        if current_int < top_int:
          self.set_pool_current(current_int+1, txn=txn)
        else:
          self.set_pool_current(None, txn=txn)
        self.set_pool_size(int.from_bytes(self.get_pool_size(txn=txn), 'big')-1, txn=txn)
        return privkey
        

  def add_privkey_to_pool(self, serialized_pubkey, serialized_privkey):
    with self.env.begin(write=True) as txn:
      self.put(serialized_pubkey, serialized_privkey, txn=txn)
      pool_current = self.get_pool_current(txn=txn)
      if pool_current == None:
         self.set_pool_size(1, txn=txn)
         pool_current = b"\x00\x00\x00\x00"
         current = 0
         self.set_pool_current(current, txn=txn)
         self.set_pool_top(current, txn=txn)
      else:
         self.set_pool_size(int.from_bytes(self.get_pool_size(txn=txn),"big")+1, txn=txn)
         self.set_pool_top(int.from_bytes(self.get_pool_top(txn=txn),"big")+1, txn=txn)
      txn.put( self.get_pool_top(txn=txn), serialized_pubkey, db=self.pool)  


  def get_privkey(self, serialized_pubkey):
    '''
      Note: Being get by pubkey, key pair is not checked wether it was in pool or not.
    '''
    with self.env.begin(write=False) as txn:
      return txn.get(serialized_pubkey, db=self.main_db)
  

 
