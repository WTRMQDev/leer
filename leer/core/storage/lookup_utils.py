#All arguments are made keyword arguments for easier partial usage
def excess_lookup( pubkey=None, _hash=None, rtx=None, tx=None, excesses_storage=None):
  assert pubkey
  assert _hash
  assert rtx
  assert tx
  assert excesses_storage
  pk = pubkey.to_pubkey()
  _index = pk.serialize()+_hash
  return excess_lookup_by_index(_index, tx=tx, rtx=rtx, excesses_storage=excesses_storage)

def excess_lookup_by_index(index, tx=None, rtx=None, excesses_storage=None):
  excesses = tx.additional_excesses + list(tx.updated_excesses.values())
  excesses_indexes = {e.index:e for e in excesses}
  if index in excesses_indexes:
    return excesses_indexes[index].message
  e = excesses_storage.get_by_index(index, rtx=rtx)
  if e:
    return e.message
  return False

