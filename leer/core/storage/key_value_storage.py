class KeyValueStorage:
  def __init__(self, dir_path):
    self.dir_path = dir_path

    if not os.path.exists(self.dir_path): 
        os.makedirs(self.dir_path) #TODO catch
    self.env = lmdb.open(self.dir_path, max_dbs=10)
    with self.env.begin(write=True) as txn:
      self.main_db = self.env.open_db(b'main_db', txn=txn, dupsort=False)

  def put(self, key, value, w_txn=None):
    if not w_txn:
      with self.env.begin(write=True) as w_txn:
        return self.put(key, value, w_txn=w_txn)
    else:
      return txn.put( bytes(key), bytes(value), db=self.main_db)

  def get(self, key, r_txn=None):
    if not r_txn:
      with self.env.begin(read=True) as r_txn:
        return self.get(key, r_txn=r_txn)
    else:
      return txn.get( bytes(key), db=self.main_db)

