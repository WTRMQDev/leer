from secp256k1_zkp import PrivateKey
import shutil, os, time, lmdb, math
from hashlib import sha256
from leer.core.lubbadubdub.address import address_from_private_key
import base64

class KeyManagerClass:
  '''
    KeyManager holds information about private keys, spent and unspent outputs.
    TODO: separate key storage and transaction info handling
  '''
  def __init__(self, path, password=None):
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

  def priv_and_pub_by_output_index(self, output_index):
       return self.wallet.get_priv_and_pub_by_output_index(output_index)

  def get_output_private_data(self, output_index):
     return self.wallet.get_output_private_data(output_index)

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

  def is_unspent(self, output_index):
    '''
      Note it is not check whether output is unspent or not, we check that output is marked as our and unspent in our wallet
    '''
    try:
      self.wallet.get_output(output_index)
      return True
    except KeyError:
      return False

  def is_owned_pubkey(self, serialized_pubkey):
    pk = self.wallet.get_privkey(serialized_pubkey)
    if not pk:
      return False
    return True

  def spend_output(self, index, spend_height):
    self.wallet.spend_output(index,spend_height)

  def add_output(self, output, block_height):
    index = output.serialized_index
    pubkey = output.address.serialized_pubkey
    taddress = output.address.to_text().encode()
    output.detect_value(inputs_info = 
         {'priv_by_pub':{
                           pubkey : self.priv_by_address(output.address)
                        }
         }) 
    value = output.value
    self.wallet.put_output(index, (block_height, output.lock_height, value,
                                   output.blinding_key.private_key,
                                   output.serialized_apc, taddress))
    self.wallet.put_pubkey_output_assoc(pubkey, index)

  def rollback(self, block_height):
    self.wallet.remove_all_actions_in_last_block(block_height)
    self.wallet.remove_all_outputs_created_in_block(block_height)
    self.wallet.restore_all_outputs_spent_in_block(block_height)

  def get_confirmed_balance_stats(self, current_height):
    stats = {
              'matured': {'known_value':0, 'known_count':0, 'unknown_count':0},
              'immatured': {'known_value':0, 'known_count':0, 'unknown_count':0}
            }
    with self.wallet.env.begin(write=False) as txn:
      cursor = txn.cursor(db=self.wallet.pubkey_index)
      for pubkey, output_index  in cursor.iternext(values=True):
        try:
          created_height, lock_height, value, bk, apc, taddress = self.wallet.get_output(output_index)
        except KeyError:
          continue #It's ok, output is already spent
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

    
  def get_confirmed_balance_list(self, current_height):
    ret = {}
    with self.wallet.env.begin(write=False) as txn:
      cursor = txn.cursor(db=self.wallet.pubkey_index)
      for pubkey, output_index in cursor.iternext(values=True):
        try:
          created_height, lock_height, value, bk, apc, taddress = self.wallet.get_output(output_index)
        except KeyError:
          continue #It's ok, output is already spent
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

  def give_transactions(self, n):
    return self.wallet.generate_transaction_dict(n=n)

  def save_generated_transaction(self, tx):
    '''
      Save transaction generated by wallet, thus then this tx will be found in block
      wallet will note outgoing payment.
    '''
    for o in tx.outputs:
      output_index = o.serialized_index
      params = \
        0, o.lock_height, o.value, o.blinding_key.private_key,\
        o.serialized_apc, o.address.to_text().encode()
      self.wallet.put_outgoing_output(output_index, params)

  def is_saved(self, output):
    try:
      self.wallet.get_outgoing_output(output.serialized_index)
      return True
    except KeyError:
      return False

  def register_processed_output(self, output_index, block_height):
    self.wallet.register_processed_output(output_index)
    params = list(self.wallet.get_outgoing_output(output_index))
    params[0] = block_height
    self.wallet.put_outgoing_output(output_index, params)
    

def _(x):
  return x.to_bytes(4,"big")

def _d(x):
  return int.from_bytes(x, "big")


def serialize_output_params(p):
  created_height, lock_height, value, blinding_key, serialized_apc, taddress = p
  ser_created_height = _(created_height)
  ser_lock_height = _(lock_height)
  if value == None:
    ser_value = b"\xff"*7
  else:
    ser_value = value.to_bytes(7,"big")
  return ser_created_height + ser_lock_height+ser_value+blinding_key+serialized_apc+taddress

def deserialize_output_params(p):  
  created_height, p = _d(p[:4]), p[4:]
  lock_height, p = _d(p[:4]), p[4:]
  value, p = _d(p[:7]), p[7:]
  ser_blinding_key, p = p[:32], p[32:]
  serialized_apc, p = p[:33], p[33:]
  taddress = p
  if value == 72057594037927935: #=b"\xff"*7
    value = None
  return created_height, lock_height, value, ser_blinding_key, serialized_apc, taddress


def serialize_spent_output_params(p):
  # While it is not necessary to store lock_height and created_height for spent outputs,
  # it is useful for effective unspending
  spend_height, created_height, lock_height, value, blinding_key, serialized_apc, taddress = p
  ser_spend_height = _(spend_height)
  ser_created_height = _(created_height)
  ser_lock_height = _(lock_height)
  if value == None:
    ser_value = b"\xff"*7
  else:
    ser_value = value.to_bytes(7,"big")
  return ser_spend_height+ser_created_height+ser_lock_height+ser_value+serialized_apc+blinding_key+taddress

def deserialize_spent_output_params(p):
  spend_height, p = _d(p[:4]), p[4:]
  created_height, p = _d(p[:4]), p[4:]
  lock_height, p = _d(p[:4]), p[4:]
  value, p = _d(p[:7]), p[7:]
  ser_blinding_key, p = p[:32], p[32:]
  serialized_apc, p = p[:33], p[33:]
  taddress = p
  if value == 72057594037927935: #=b"\xff"*7
    value = None
  return spend_height, created_height, lock_height, value, ser_blinding_key, serialized_apc, taddress

def repack_ser_output_to_spent(ser_output, height):
  '''
    Function for fast repacking without deserialization
  '''
  return _(height)+ser_output

def repack_ser_spent_output_to_unspent(ser_spent_output):
  '''
    Function for fast repacking without deserialization
  '''
  return ser_spent_output[4:]


RECEIVED, SPENT, SENT = b"\x00", b"\x01", b"\x02"

class DiscWallet:
  '''
    It is generally key-value db:
     1) private keys:  key is serialized pubkey; value - serialized privkey.
     2) unspent parsed outputs: key is output_index; value - tuple (lock_height, value)
     3) spent outputs: key is output_index; value - tuple (spend_height, value)
     4) block-outputs map: key is block_number; value - tuple (spent/created, output_index)
     5) pubkey-outputs map 
     6) num_index -> output: list of touched (created/spent) outputs
     7) generated outputs: key is output_index; value - output params
    There is privkey pool: bunch of pregenerated privkeys. It is expected that on a higher level
    instead of generating and immediate usage of new key, new key will be put into the pool and the oldest key
    from the pool will be used. Thus, in case of backups, copies and so on, "old copy" will contain
    some keys used after copy being made.
  '''
  def __init__(self, dir_path):
    self.dir_path = dir_path

    if not os.path.exists(self.dir_path): 
        os.makedirs(self.dir_path) #TODO catch
    self.env = lmdb.open(self.dir_path, max_dbs=10, map_size=int(250e6)) #TODO this database is too big, should be checked
    with self.env.begin(write=True) as txn:
      self.main_db = self.env.open_db(b'main_db', txn=txn, dupsort=False)
      self.pool = self.env.open_db(b'pool', txn=txn, dupsort=False)
      self.output = self.env.open_db(b'output', txn=txn, dupsort=False)
      self.spent = self.env.open_db(b'spent', txn=txn, dupsort=False)
      self.generated_outputs = self.env.open_db(b'generated', txn=txn, dupsort=False)
      self.block_index = self.env.open_db(b'block_index', txn=txn, dupsort=True, dupfixed=True)
      self.pubkey_index = self.env.open_db(b'pubkey_index', txn=txn, dupsort=True, dupfixed=True)
      self.pubkey_index_reversed = self.env.open_db(b'pubkey_index_reversed', txn=txn, dupsort=True, dupfixed=True)
      self.actions_list = self.env.open_db(b'actions_list', txn=txn)
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
        return self.put(serialized_pubkey, serialized_privkey, txn=txn)
    else:
      p1=txn.put( bytes(serialized_pubkey), bytes(serialized_privkey), db=self.main_db)    
  

  def put_output(self, output_index, output_params, txn=None):
    if not txn:
      with self.env.begin(write=True) as txn:
        return self.put_output(output_index, output_params, txn=txn)
    else:     
      p1=txn.put( bytes(output_index), serialize_output_params(output_params), db=self.output)  
      self.add_block_new_output_association(output_params[0], output_index, w_txn=txn)  
      txn.put( _(self.last_action_num()), RECEIVED+bytes(output_index), db=self.actions_list)
      self.bump_action_num(w_txn=txn)

  def put_outgoing_output(self, output_index, output_params):
    with self.env.begin(write=True) as txn:
      p1=txn.put( bytes(output_index), serialize_output_params(output_params), db=self.generated_outputs)    

  def register_processed_output(self, output_index):
    with self.env.begin(write=True) as txn:
      txn.put( _(self.last_action_num()), SENT+bytes(output_index), db=self.actions_list)
      self.bump_action_num(w_txn=txn)

  def get_output(self, output_index, txn=None):
    if not txn:
      with self.env.begin(write=False) as txn:
        return self.get_output(output_index, txn=txn)
    else:     
      output_params = txn.get( bytes(output_index), db=self.output)    

      if not output_params:
         raise KeyError
      else:
        return deserialize_output_params( output_params)

  def get_outgoing_output(self, output_index, r_txn=None):
    if not r_txn:
      with self.env.begin(write=False) as r_txn:
        return self.get_outgoing_output(output_index, r_txn=r_txn)
    else:     
      output_params = r_txn.get( bytes(output_index), db=self.generated_outputs)    
      if not output_params:
         raise KeyError
      else:
        return deserialize_output_params( output_params)

  def pop_ser_output(self, output_index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.pop_ser_output(output_index, w_txn=w_txn)
    else:     
      output_params = w_txn.pop( bytes(output_index), db=self.output)    
      if not output_params:
         raise KeyError
      else:
        return output_params

  def spend_output(self, output_index, block_height, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        self.spend_output(output_index, block_height, w_txn=w_txn)
    else:     
      ser_output = self.pop_ser_output(output_index, w_txn=w_txn) # KeyError exception may be thrown here
      ser_spent_output = repack_ser_output_to_spent(ser_output, block_height)
      p1=w_txn.put( bytes(output_index), ser_spent_output, db=self.spent) 
      w_txn.put( _(self.last_action_num()), SPENT+bytes(output_index), db=self.actions_list)
      self.bump_action_num(w_txn=w_txn)

  def unspend_output(self, output_index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        self.unspend_output(output_index, w_txn=w_txn)
    else:     
      ser_spent_output = w_txn.pop( bytes(output_index), w_txn=w_txn)
      if not ser_spent_output:
        raise KeyError
      ser_output = repack_ser_spent_output_to_unspent(ser_spent_output)
      p1=w_txn.put( bytes(output_index), ser_output, db=self.output) # TODO self.put_output?

  def get_spent_output(self, output_index, txn=None):
    if not txn:
      with self.env.begin(write=False) as txn:
        return self.get_output(output_index, txn=txn)
    else:     
      output_params = txn.get( bytes(output_index), db=self.spent)    
      if not output_params:
         raise KeyError
      else:
        return deserialize_spent_output_params( output_params)


  def get_privkey_from_pool(self):
    '''
      Privkey will be immideately removed from the pool.
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
      Note: Being get by pubkey, key pair is not checked wether it was in the pool or not.
    '''
    with self.env.begin(write=False) as txn:
      return txn.get(serialized_pubkey, db=self.main_db)
    #TODO if no such serialized_pubkey KeyError should be raised here

  def add_block_spent_output_association(self, block_height, output_index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.add_block_spent_output_association(block_height, output_index, w_txn)
    else:   
      w_txn.put( _(block_height), b"\x01"+output_index, db=self.block_index, dupdata=True)
        

  def add_block_new_output_association(self, block_height, output_index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.add_block_new_output_association(block_height, output_index, w_txn)
    else:     
      w_txn.put( _(block_height), b"\x00"+output_index, db=self.block_index, dupdata=True)


  def remove_block_spent_output_association(self, block_height, output_index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.remove_block_spent_output_association(block_height, output_index, w_txn)
    else:     
      w_txn.delete( _(block_height), b"\x01"+output_index, db=self.block_index)


  def remove_block_new_output_association(self, block_height, output_index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.remove_block_new_output_association(block_height, output_index, w_txn)
    else:     
      w_txn.delete( _(block_height), b"\x00"+output_index, db=self.block_index)


  def remove_all_outputs_created_in_block(self, block_height, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.remove_all_outputs_created_in_block(block_height, w_txn)
    else: 
      cursor = w_txn.cursor(db=self.block_index)
      if not cursor.set_key(_(block_height)):
        return #It's okay, block doesn't contain anything related to our wallet
      for assoc in cursor.iternext_dup():
        if assoc[:1] == b"\x00":
          self.pop_ser_output(assoc[1:], w_txn=w_txn)
          self.remove_block_new_output_association(block_height, assoc[1:], w_txn=w_txn)
      #NOTE: last n actions can also contain spent outputs, so remove_all_outputs_created_in_block call
      # without restore_all_outputs_spent_in_block call is unsafe
      #self.remove_last_actions(n=len(output_list), w_txn=w_txn)
          


  def restore_all_outputs_spent_in_block(self, block_height, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.restore_all_outputs_spent_in_block(block_height, w_txn)
    else:     
      cursor = w_txn.cursor(db=self.block_index)
      output_list = []
      if not cursor.set_key(_(block_height)):
        return #It's okay, block doesn't contain anything related to our wallet
      for assoc in cursor.iternext_dup():
        if assoc[:1] == b"\x01":
          output_list.append(self.unspend_output(assoc[1:], w_txn=w_txn))
          self.remove_block_spent_output_association(block_height, assoc[1:], w_txn=w_txn)
      #NOTE: last n actions can also contain spent outputs, so remove_all_outputs_created_in_block call
      # without restore_all_outputs_spent_in_block call is unsafe
      #self.remove_last_actions(n=len(output_list), w_txn=w_txn)

  def search_output_everywhere(self, output_index, r_txn, guess=None):
      methods = [self.get_output, self.get_spent_output, self.get_outgoing_output]
      if not guess or guess==RECEIVED:
        pass
      elif guess==SPENT:
        methods = [self.get_spent_output, self.get_output, self.get_outgoing_output]
      elif guess==SENT:
        methods = methods[::-1]
      for method in methods:
        try:
          return method(output_index, r_txn)
        except KeyError:
          continue
      raise KeyError

  def remove_all_actions_in_last_block(self, block_height, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.remove_all_actions_in_last_block(block_height, w_txn)
    start = current = self.last_action_num(r_txn=w_txn)    
    num = 0
    while current>0:
      tp = w_txn.get(_(current-1), db = self.actions_list)
      act, output_index = tp[:1], tp[1:]
      try:
          height = self.search_output_everywhere(output_index, r_txn = w_txn)[0]
      except KeyError:
          pass
      if height<block_height:
        break
      current-=1
      num+=1
    self.remove_last_actions(num, w_txn)  
  
  def put_pubkey_output_assoc(self, pubkey, index, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.put_pubkey_output_assoc(pubkey, index, w_txn)
    else:     
      w_txn.put( pubkey, index, db=self.pubkey_index, dupdata=True)
      w_txn.put( index, pubkey, db=self.pubkey_index_reversed, dupdata=True)

  def get_priv_and_pub_by_output_index(self, output_index, r_txn=None):
    if not r_txn:
      with self.env.begin(write=False) as r_txn:
        return self.get_priv_and_pub_by_output_index( output_index, r_txn)
    else:
      pubkey = r_txn.get(output_index, db=self.pubkey_index_reversed)
      if not pubkey:
        raise KeyError
      priv = r_txn.get(pubkey, db=self.main_db)
      if not priv:
        raise KeyError
      return pubkey, priv

  def get_output_private_data(self, output_index):
    with self.env.begin(write=False) as r_txn:
      pubkey = r_txn.get(output_index, db=self.pubkey_index_reversed)
      if not pubkey:
        raise KeyError
      priv = r_txn.get(pubkey, db=self.main_db)
      if not priv:
        raise KeyError
      output_params = r_txn.get( bytes(output_index), db=self.output)    
      if not output_params:
         raise KeyError
      params = deserialize_output_params( output_params)
      blinding_key = params[3]
      apc = params[4]
      return priv, blinding_key, apc 

  def add_sent_output(self, output, w_txn=None):
    if not r_txn:
      with self.env.begin(write=True) as w_txn:
        return self.add_sent_output(output, w_txn=w_txn)
    w_txn.put( _(self.last_action_num()), SENT+bytes(output_index), db=self.actions_list)
    self.bump_action_num(w_txn=w_txn)    

      
  def last_action_num(self, r_txn=None):
    if not r_txn:
      with self.env.begin(write=False) as r_txn:
        return self.last_action_num(r_txn=r_txn)
    lan = r_txn.get(b'last num', db = self.actions_list)
    if not lan:
      lan = 0
    else:
      lan = _d(lan)
    return lan

  def bump_action_num(self, w_txn, n=None):
    lan = self.last_action_num(r_txn=w_txn) if not n else n-1
    w_txn.put(b'last num', _(lan+1), db = self.actions_list)

  def remove_last_actions(self, n, w_txn):
    lan = self.last_action_num(r_txn=w_txn)
    for i in range(lan-1, lan-1-n, -1):
      w_txn.delete(_(i), db = self.actions_list)
    self.bump_action_num(w_txn=w_txn, n = lan-n)
        

  def generate_transaction_dict(self, n):
    with self.env.begin(write=False) as r_txn:
      txdict = {} #Each element is dict {block_num: {'output':{params}}}
      current_action = self.last_action_num(r_txn=r_txn) - 1
      while current_action>=0 and len(txdict)<n:
        tp = r_txn.get(_(current_action), db = self.actions_list)
        action, output_index = tp[:1], tp[1:]
        soi = base64.b64encode(output_index).decode()
        current_action-=1
        output_params = None
        try:
          output_params = self.get_output(output_index, txn=r_txn)
        except KeyError:
          try:
            output_params = self.search_output_everywhere(output_index, r_txn = r_txn, guess=action)
          except KeyError:
            pass #TODO warning
            continue
        if action==SPENT:
          spend_height, created_height, lock_height, value, ser_blinding_key, serialized_apc, taddress = output_params
          if not spend_height in txdict:
            txdict[spend_height] = {}
          txdict[spend_height][soi] = {'lock_height':lock_height, 'value':value, 'address':taddress.decode(), 'type':'spent'}
        elif action==RECEIVED:
          if len(output_params)==6:
            created_height, lock_height, value, ser_blinding_key, serialized_apc, taddress = output_params
          elif len(output_params)==7: #It was received on created_height but later spent
            spend_height, created_height, lock_height, value, ser_blinding_key, serialized_apc, taddress = output_params
          if not created_height in txdict:
            txdict[created_height] = {}
          _type = 'received'
          if soi in txdict[created_height] and txdict[created_height][soi]['type']=='sent':
           _type = 'inner transfer'
          txdict[created_height][soi] = {'lock_height':lock_height, 'value':value, 'address':taddress.decode(), 'type':_type}
        elif action==SENT:
          created_height, lock_height, value, ser_blinding_key, serialized_apc, taddress = output_params
          if not created_height in txdict:
            txdict[created_height] = {}
          _type = 'sent'
          if soi in txdict[created_height] and txdict[created_height][soi]['type']=='received':
           _type = 'inner transfer'
          txdict[created_height][soi] = {'lock_height':lock_height, 'value':value, 'address':taddress.decode(), 'type':_type}
      return txdict  
        
            
