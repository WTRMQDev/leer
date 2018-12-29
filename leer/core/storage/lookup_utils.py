#All arguments are made keyword arguments for easier partial usage
def excess_lookup( pubkey=None, _hash=None, rtx=None, tx=None):
  assert pubkey
  assert _hash
  assert rtx
  assert tx
  pk = pubkey.to_pubkey()

def output_lookup(commitment=None, rtx=None, tx=None):
  assert commitment
  assert rtx
  assert tx
  commitment = commitment.to_pedersen_commitment()

