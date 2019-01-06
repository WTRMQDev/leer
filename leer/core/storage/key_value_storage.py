class KeyValueStorage:
  def __init__(self, name, env, wtx, dupsort=False):
    self.name = name.encode("utf-8")
    self.env = env
    self.main_db = self.env.open_db(self.name + b'_main_db', txn=wtx, dupsort=dupsort)

  def put(self, key, value, wtx, dupdata=False):
      return wtx.put( bytes(key), bytes(value), db=self.main_db, dupdata=dupdata)

  def get(self, key, rtx):
    return rtx.get( bytes(key), db=self.main_db)

  def remove(self, key, wtx, value=None):
    return wtx.remove( bytes(key), value= value, db=self.main_db)

  def has(self, key, rtx):
    return not (self.get( bytes(key), rtx=rtx)==None)

