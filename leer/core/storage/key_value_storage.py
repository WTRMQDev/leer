class KeyValueStorage:
  def __init__(self, dir_path, name, env, wtx):
    self.dir_path = dir_path
    self.name = name.encode("utf-8")
    self.env = env
    self.main_db = self.env.open_db(self.name + b'main_db', txn=wtx, dupsort=False)

  def put(self, key, value, wtx):
      return wtx.put( bytes(key), bytes(value), db=self.main_db)

  def get(self, key, rtx):
    return rtx.get( bytes(key), db=self.main_db)

