from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import address_from_private_key
from secp256k1_zkp import PrivateKey

keys = [PrivateKey() for i in range(5)]
adr1,adr2,adr3,adr4,adr5= [address_from_private_key(keys[i]) for i in range(5)]

def test_ioput():
  ioput_serialize_deserialize()
  ioput_proofs_info()
  ioput_encrypted_messsage()
  test_ioput_indexes()


def ioput_serialize_deserialize():
  options = {'address': [adr1], 'value':[1,100, int(705e6*1e8)], 'relay_fee': [0,100, int(1e8)], 
             'generator':[None], #b'\x0b\xf8x*\xe9\xdc\xb1\xfd\xe9k\x8eZ\xf9\x8250\xdcrLU`p\xbaD\xf1\xfdh\x93\xd7\x85\xb9\x9e\x07'], #TODO arbitraty value gen
             'burden_hash':[None, b"\x44"*32], 'coinbase':[True, False], 'lock_height':[0, 10, 10000]}
  all_possible_options = [{}]
  for opt in options:
    c= all_possible_options
    all_possible_options = []
    for i in options[opt]:
      for prev in c:
        n = prev.copy()
        if i!=None:
          n[opt] = i
        all_possible_options.append(n)

  for var in all_possible_options:
    _input1=IOput()
    _input1.fill(**var)
    _input1.generate()

    _input2=IOput(binary_object=_input1.serialize())
    _input2.verify()

    assert _input1.version==_input2.version
    assert _input1.block_version==_input2.block_version
    assert _input1.lock_height==_input2.lock_height
    assert _input1.authorized_pedersen_commitment.serialize()==_input2.authorized_pedersen_commitment.serialize()
    assert _input1.address.serialize()==_input2.address.serialize()
    assert _input1.rangeproof.proof==_input2.rangeproof.proof
    assert _input1.encrypted_message==_input2.encrypted_message
    assert _input1.generator==_input2.generator
    assert _input1.relay_fee==_input2.relay_fee
    assert _input1.authorized_burden==_input2.authorized_burden

  print("ioput_serialize_deserialize OK")

def ioput_proofs_info():
  _input1=IOput()
  _input1.fill(adr1, 100)
  _input1.version = 1 #To use RangeProof instead of BulletProofs
  _input1.generate(exp=2, concealed_bits=3)
  info=_input1.info()
  assert info['exp']==2
  assert info['min_value']==0
  assert info['max_value']==700
  _input1=IOput()
  _input1.fill(adr1, 3)
  _input1.version = 1 #To use RangeProof instead of BulletProofs
  _input1.generate(exp=0, concealed_bits=3, min_value=1)
  info=_input1.info()
  assert info['exp']==0
  assert info['mantissa']==3
  assert info['min_value']==1
  assert info['max_value']==8
  _input1=IOput()
  _input1.fill(adr1, 300)
  _input1.version = 1 #To use RangeProof instead of BulletProofs
  #coceanled bits cannot be less than bits in value
  _input1.generate(exp=0, concealed_bits=3)
  info=_input1.info()
  assert info['exp']==0
  assert info['mantissa']==9
  assert info['min_value']==0
  assert info['max_value']==511
  print("ioput_proofs_info OK")

  _input1=IOput()
  _input1.fill(adr1, 300)
  _input1.generate()
  info=_input1.info()
  assert info['exp']==0
  assert info['mantissa']==0
  assert info['min_value']==0
  assert info['max_value']==2**64-1

def ioput_encrypted_messsage():
  _input1=IOput()
  _input1.fill(adr1, 100)
  _input1.generate(exp=2, concealed_bits=3)

  _input2=IOput(binary_object=_input1.serialize())
  _input2.verify()
  _input2.detect_value({'priv_by_pub':{adr1.serialized_pubkey:keys[0]}})
  
  assert _input1.value==_input2.value
  assert _input1.blinding_key.serialize()==_input2.blinding_key.serialize()
  print("ioput_encrypted_message OK")

def test_ioput_indexes():
  _input1=IOput()
  _input1.fill(adr1, 100)
  _input1.generate(exp=2, concealed_bits=3)
  assert _input1.index_len==32+33
  assert len(_input1.serialized_index)==32+33
  assert len(_input1.commitment_index)==32+33
  print("ioput_indexes len OK")

