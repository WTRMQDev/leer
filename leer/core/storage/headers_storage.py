from leer.core.primitives.header import Header, ContextHeader
import shutil, os, time, lmdb, math

class HeadersStorage:

  __shared_states = {}

  def __init__(self, storage_space, wtx):
    path = storage_space.path
    if not path in self.__shared_states:
        self.__shared_states[path]={}
    self.__dict__ = self.__shared_states[path]
    self.storage = HeadersDiscStorage(path, env=storage_space.env, wtx=wtx)
    self.storage_space = storage_space
    self.storage_space.register_headers_storage(self)

  def get(self, _hash, rtx):
    serialized_header = self.storage.get_by_hash(_hash, rtx=rtx)
    if not serialized_header:
      raise KeyError(_hash)
    ch=ContextHeader()
    ch.deserialize(serialized_header)
    return ch

  def put(self, _hash, header, wtx):
    self.storage.put(header.height, header.hash, header.serialize_with_context(), wtx=wtx)

  def update(self, _hash, header, wtx):
    self.storage.update(header.hash, header.serialize_with_context(), wtx=wtx)

  def has(self, _hash, rtx):
    return bool(self.storage.get_by_hash(_hash, rtx=rtx))
      
  def get_headers_at_height(self, height, rtx):
    ret=[]
    for serialized_header in self.storage.get_by_height(height, rtx=rtx):
      ch=ContextHeader()
      ch.deserialize(serialized_header)
      ret.append(ch)
    return ret

  def get_headers_hashes_at_height(self, height, rtx):
    return self.storage.get_hashes_by_height(height,rtx=rtx)


def __(x):
  return (x).to_bytes(4,'big')

class HeadersDiscStorage:
  def __init__(self, dir_path, env, wtx):
    self.dir_path = dir_path

    self.env = env
    self.main_db = self.env.open_db(b'headers_main_db', txn=wtx, dupsort=False)
    self.height_db = self.env.open_db(b'headers_height_db', txn=wtx, dupsort=True)

  def put(self, height, _hash, serialized_header, wtx):
    p1=wtx.put( bytes(_hash), bytes(serialized_header), db=self.main_db, dupdata=False, overwrite=True)
    p2=wtx.put( __(height), bytes(_hash), db=self.height_db, dupdata=True)

  def update(self, _hash, serialized_header, wtx):
    wtx.put(bytes(_hash), bytes(serialized_header), db=self.main_db, dupdata=False, overwrite=True)

  def get_by_hash(self, _hash, rtx):
    return rtx.get(bytes(_hash), db=self.main_db)

  def get_by_height(self, height, rtx):
      cursor = rtx.cursor(db=self.height_db)
      assert cursor.set_key(__(height))
      _hashes = list(cursor.iternext_dup())
      return [self.get_by_hash(_hash, rtx=rtx) for _hash in _hashes] 
  
  def get_hashes_by_height(self, height, rtx):
      cursor = rtx.cursor(db=self.height_db)
      assert cursor.set_key(__(height))
      return list(cursor.iternext_dup())
  

