#All arguments are made keyword arguments for easier partial usage
def excess_lookup( pubkey=None, _hash=None, rtx=None, tx=None, excesses_storage=None):
  assert pubkey
  assert _hash
  assert rtx
  assert tx
  assert excesses_storage
  pk = pubkey.to_pubkey()
  _index = pk.serialize()+_hash
  excesses = tx.additional_excesses + list(tx.updated_excesses.values())
  excesses_indexes = {e.index:e for e in excesses}
  if _index in excesses_indexes:
    return excesses_indexes[_index].message
  e = excesses_storage.get_by_index(_index)
  if e:
    return e.message
  return False

def output_lookup(commitment=None, rtx=None, tx=None, txos_storage=None):
  assert commitment
  assert rtx
  assert tx
  assert txos_storage
  commitment = commitment.to_pedersen_commitment()
  commitment_index = commitment.serialize()
  res = txos_storage.commitments.fuzzy_search(commitment_index, rtx=rtx)
  if not res:
    return False
  ind, trash = res
  if ind[:33]==commitment_index:
    return True
  return False
  

