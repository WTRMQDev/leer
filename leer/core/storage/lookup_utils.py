#All arguments are made keyword arguments for easier partial usage
def excess_lookup( pubkey=None, _hash=None, rtx=None, tx=None, excesses_storage=None):
  assert pubkey
  assert _hash
  assert rtx
  assert tx
  assert excesses_storage
  pk = pubkey.to_pubkey()
  _index = pk.serialize()+_hash

def output_lookup(commitment=None, rtx=None, tx=None, txos_storage=None):
  assert commitment
  assert rtx
  assert tx
  assert txos_storage
  commitment = commitment.to_pedersen_commitment()
  commitment_index = commitment.serialize()
  

