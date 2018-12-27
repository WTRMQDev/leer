class KeyValueStorage:
  def __init__(self, name, env, wtx):
    self.name = name.encode("utf-8")
    self.env = env
    self.main_db = self.env.open_db(self.name + b'_main_db', txn=wtx, dupsort=False)

  def put(self, key, value, wtx):
      return wtx.put( bytes(key), bytes(value), db=self.main_db)

  def get(self, key, rtx):
    return rtx.get( bytes(key), db=self.main_db)

  def has(self, key, rtx):
    return not (self.get( bytes(key), db=self.main_db)==None)

