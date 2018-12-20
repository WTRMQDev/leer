from key_value_storage import KeyValueStorage

class BurdenStorage(KeyValueStorage):
  '''
    Burden storage is helper storage.
    It stores information about dependencies (via OUTPUTORHASH script) of existed
    additional excesses on output set. 
    When such output with burden is spent we should check that specific excess was 
    added to blockchain.
  '''
  def __init__(env, wtx):
    KeyValueStorage.__init__(self, b"burden", env, wtx)

  def add_excess_with_burden(excess, wtx):
    pass

  def delete_excess_with_burden(excess, wtx):
    pass

  def complete_excess_with_burden(excess, wtx):
    pass
