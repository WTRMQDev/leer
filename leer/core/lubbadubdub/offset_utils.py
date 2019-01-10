secp256k1_order = 0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141

def sum_offset(offset1, offset2):
  return (offset1 + offset2) % secp256k1_order

def subtract_offset(offset1, offset2):
  return (offset1 + secp256k1_order - offset2) % secp256k1_order
