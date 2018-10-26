from leer.core.primitives.header import Header, ContextHeader
import shutil, os, time, lmdb, math
from leer.core.storage.default_paths import headers_storage_path

class HeadersStorage:

  __shared_states = {}

  def __init__(self, storage_space, path):
    if not path in self.__shared_states:
        self.__shared_states[path]={}
    self.__dict__ = self.__shared_states[path]
    self.storage = HeadersDiscStorage(path)
    self.storage_space = storage_space
    self.storage_space.register_headers_storage(self)

  def __getitem__(self, _hash):
    serialized_header = self.storage.get_by_hash(_hash)
    if not serialized_header:
      raise KeyError(_hash)
    ch=ContextHeader()
    ch.deserialize(serialized_header)
    return ch

  def __setitem__(self, _hash, header):
    #here we should save
    self.storage.put(header.height, header.hash, header.serialize_with_context())

  def update(self, _hash, header):
    self.storage.update(header.hash, header.serialize_with_context())

  def __contains__(self, _hash):
    return bool(self.storage.get_by_hash(_hash))
      
  def get_headers_at_height(self, height):
    ret=[]
    for serialized_header in self.storage.get_by_height(height):
      ch=ContextHeader()
      ch.deserialize(serialized_header)
      ret.append(ch)
    return ret

  def get_headers_hashes_at_height(self, height):
    return self.storage.get_hashes_by_height(height)


def __(x):
  return (x).to_bytes(4,'big')

class HeadersDiscStorage:
  def __init__(self, dir_path):
    self.dir_path = dir_path

    if not os.path.exists(self.dir_path): 
        os.makedirs(self.dir_path) #TODO catch
    self.env = lmdb.open(self.dir_path, max_dbs=10)
    with self.env.begin(write=True) as txn:
      self.main_db = self.env.open_db(b'main_db', txn=txn, dupsort=False)
      self.height_db = self.env.open_db(b'height_db', txn=txn, dupsort=True)

  def put(self, height, _hash, serialized_header):
    with self.env.begin(write=True) as txn:
      p1=txn.put( bytes(_hash), bytes(serialized_header), db=self.main_db, dupdata=False, overwrite=True)
      p2=txn.put( __(height), bytes(_hash), db=self.height_db, dupdata=True)

  def update(self, _hash, serialized_header):
    with self.env.begin(write=True) as txn:
      txn.put(bytes(_hash), bytes(serialized_header), db=self.main_db, dupdata=False, overwrite=True)

  def get_by_hash(self, _hash):
    with self.env.begin(write=False) as txn:
      return txn.get(bytes(_hash), db=self.main_db)

  def get_by_height(self, height):
    with self.env.begin(write=False) as txn:
      cursor = txn.cursor(db=self.height_db)
      assert cursor.set_key(__(height))
      _hashes = list(cursor.iternext_dup())
      return [txn.get(bytes(_hash), db=self.main_db) for _hash in _hashes] #we do not use self.get_by_hash to keep one txn. Consider to add optional txn for all funcs?
  
  def get_hashes_by_height(self, height):
    with self.env.begin(write=False) as txn:
      cursor = txn.cursor(db=self.height_db)
      assert cursor.set_key(__(height))
      return list(cursor.iternext_dup())
  

