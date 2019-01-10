import os, lmdb


class UTXOIndex:
  '''
    Basically it is index [public_key -> set of unspent outputs with this public key] 
  '''
  __shared_states = {}

  def __init__(self, storage_space, wtx):
    path = storage_space.path
    if not path in self.__shared_states:
      self.__shared_states[path]={}
    self.__dict__ = self.__shared_states[path]
    self.directory = path
    if not os.path.exists(path): 
        os.makedirs(self.directory) #TODO catch
    self.env = storage_space.env
    self.main_db = self.env.open_db(b'utxoi_main_db', txn=wtx, dupsort=True, dupfixed=True) #TODO duplicate
    self.storage_space = storage_space
    self.storage_space.register_utxo_index(self)

  def _add(self, serialized_pubkey, utxo_hash_and_pc, wtx):
    wtx.put( serialized_pubkey, utxo_hash_and_pc, db=self.main_db, dupdata=True)

  def add_utxo(self, output, wtx):
    self._add(output.address.pubkey.serialize(), output.serialized_index, wtx=wtx)

  def _remove(self, serialized_pubkey, utxo_hash_and_pc, wtx):
    wtx.delete( serialized_pubkey, utxo_hash_and_pc, db=self.main_db)
    

  def remove_utxo(self, output, wtx):
    self._remove(output.address.pubkey.serialize(), output.serialized_index, wtx=wtx)


  def get_all_unspent(self, pubkey, rtx):
    return self.get_all_unspent_for_serialized_pubkey(pubkey.serialize(),rtx=rtx)

  def get_all_unspent_for_serialized_pubkey(self, serialized_pubkey, rtx):
    cursor = rtx.cursor(db=self.main_db)
    if not cursor.set_key(serialized_pubkey):
      return []
    else:
      return list(cursor.iternext_dup())
