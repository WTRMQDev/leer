import struct
import hashlib

from secp256k1_zkp import PrivateKey, PedersenCommitment, RangeProof

from leer.core.lubbadubdub.constants import default_generator, default_generator_ser, generators, GLOBAL_TEST
from leer.core.lubbadubdub.address import Address
from leer.core.lubbadubdub.utils import encrypt, decrypt

def is_sorted(lst, key=lambda x: x):
    for i, el in enumerate(lst[1:]):
        if key(el) < key(lst[i]): # i is the index of the previous element
            return False
    return True


class IOput:
  """ Basic class which represent transaction input or output"""

  # Pedersen commitment should be unique, it is id of IOput
  def __init__(self, json_object=None, binary_object=None):
    """
    Initialize empty ioput

    Parameters
    ----------
    [optional] binary_object : bytes
        serialized output.
    """
    #serializable data
    self.version = 1
    self.block_version = 1
    self.lock_height = 0
    self.authorized_pedersen_commitment = None
    self.address = None
    self.rangeproof = None
    self.encrypted_message = None
    self.generator = None
    self.relay_fee = None
    #inner data
    self.unauthorized_pedersen_commitment = None
    self.value = None
    self.blinding_key = None

    if json_object:
      self.from_json(json_object)
    if binary_object:
      self.deserialize(binary_object)

  def from_json(self, json_object):
    pass  #TODO

  def to_json(self):
    pass #TODO

  def serialize(self):
    """ Returns binary representation of output"""
    ret = self.signed_part()

    ser_range_proof = self.rangeproof.proof
    ret += struct.pack("> H", len(ser_range_proof))
    ret += ser_range_proof

    return ret

  @property
  def hash(self):
    seed = self.serialize()
    m=hashlib.sha256()
    m.update(seed)
    return m.digest()

  @property
  def index_len(self):
    #len apc + len hash
    return 33+32

  @property
  def serialized_index(self):
    """
      Returns binary representation of output index.
      For transaction, to be spent, it is necessery that all inputs are known.
      Thus it is possible to include only index for inputs.
      Since all outputs should have unique authorized pedersen commitments(APC),
      it seems expedient to use APC as index. However it may cause issues with
      transaction which spends from memory pool. Indeed, while confirmed 
      transactions strictly have unique APC, different node may have in memory
      transaction with different outputs, but with the same APC for thos outputs
      (_double spend_).
      Then, if another transaction which spend _double spending_ will be added
      to memory pool, different nodes may have different opinios on its validity.
      It is possible to use such dis-consensus as attack to disrupt connectivity.

      Another option is hash of outputs. However, hash as index hinders some
      basic mimblewimble checks: we cant check that sum of inputs and outputs is
      zero without access to ledger. In our terms all checks become context
      dependent.
      Thus we use concantenation of APC and hash. It slightly bigger (although nothing
      in comparisson with rangeproof) but allows both basic checks and unambiguous
      indexing.
    """
    return self.authorized_pedersen_commitment.serialize()+self.hash

  @property
  def commitment_index(self):
    """
      Special index which is used for building commitment merkle tree
    """
    m=hashlib.sha256()
    m.update(self.authorized_pedersen_commitment.serialize())
    return self.authorized_pedersen_commitment.serialize() + m.digest()

  @property
  def is_coinbase(self):
    return self.version==0

  def deserialize(self, serialized_output):
    """ Decode output from serialized representation. """
    self.deserialize_raw(serialized_output)

  def deserialize_raw(self, serialized_output):  
    #TODO part1, part2, part3 should be substitued with construction `something, serialized = serialized[:x], serialized[x:]`
    # as it done in other modules
    """ Decode output from serialized representation. Return residue of data after serialization"""

    if len(serialized_output)<145:
        raise Exception("Serialized output doesn't contain enough bytes for constant length parameters")

    part1, part2 = serialized_output[:80], serialized_output[80:]
    (self.version, self.block_version, self.lock_height,
      self.generator, self.relay_fee, self.apc) = struct.unpack("> H H H 33s Q 33s", part1) 

    if self.generator in generators:
      self.authorized_pedersen_commitment = PedersenCommitment(commitment=self.apc, raw=True, blinded_generator = generators[self.generator])
    else:
      raise NotImplemented

    self.address = Address()
    part2 = self.address.deserialize_raw(part2)
    
    if len(part2)<2:
        raise Exception("Serialized output doesn't contain enough bytes for encrypted message length")
    (encrypted_message_len,) = struct.unpack("> H", part2[:2]) 
    if len(part2)<2+encrypted_message_len:
        raise Exception("Serialized output doesn't contain enough bytes for encrypted message")
    self.encrypted_message = part2[2:2+encrypted_message_len]

    part3=part2[2+encrypted_message_len:]
    (range_proof_len,) = struct.unpack("> H", part3[:2])
    if len(part3)<2+range_proof_len: 
        raise Exception("Serialized output doesn't contain enough bytes for rangeproof")

    self._calc_unauthorized_pedersen()    
    self.rangeproof = RangeProof(proof=part3[2:2+range_proof_len], 
        pedersen_commitment=self.unauthorized_pedersen_commitment, 
        additional_data = self.signed_part())

    info=self.info()
    if info['min_value']==info['max_value']:
      self.value=info['min_value']

    return part3[2+range_proof_len:]

  def detect_value(self, key_manager):
    try:
          privkey = key_manager.priv_by_address(self.address)
          nonce = self.apc
          decrypted_message = decrypt(privkey, nonce, self.encrypted_message)
          raw_blinding_key, self.value = struct.unpack( "> 32s Q", decrypted_message)
          self.blinding_key=PrivateKey(raw_blinding_key, raw=True)
          if not self._calc_pedersen_wos()==self.unpc:
            self.blinding_key, self.value = None,None
            raise Exception("Incorrect blinding key and value")
    except Exception as e:
         #TODO definetely some logic should be added here to notify about missed info
         pass  
    return bool(self.value)
       

  def signed_part(self):
    """
      Flurbo output has more abundant structure than classical mw output.
      To be sure that all elements of structure were relayed unchanged, all
      elements are signed in rangeproof. This function returns serialized
      representation elements which should be signed.
    """
    ret = b''
    ret += struct.pack("> H H H 33s Q 33s",
      self.version, self.block_version, self.lock_height,
      self.generator, self.relay_fee,
      self.authorized_pedersen_commitment.serialize())
    ret += self.address.serialize()
    ret += struct.pack("> H", len(self.encrypted_message))
    ret += self.encrypted_message
    return ret


  #Wallet functionality
  def fill(self, address, value, relay_fee = 0, blinding_key=None, generator=default_generator_ser, coinbase=False, lock_height = 0):
    """
    Fill basic params of ouput.

    Fill params, but doesn't generate commitments and rangeproofs.
    It should be done separately by generate() function

    Parameters
    ----------
    address : Address
        Address of output
    value : int
        Value of output in minimal indivisible units
    [optional] relay_fee : int
        Default:0. Relay fee of output in minimal indivisible units
    [optional] blinding_key : PrivateKey
        Default: random. Usually wallet should not store this key: it will
        be encrypted it output with private key of address
    [optional] generator : GeneratorOnCurve
        Default: default_generator. Asset transactions will use another generators
    [optional] coinbase : bool
        Default: False. Coinbase outputs have version 0 (while common version is 1)
    [optional] lock_height : integer
        Default: 0. Minimal height at which output can be spent.
    """
    self.address = address
    self.generator = generator
    self.value = value
    if blinding_key is None:
      blinding_key = PrivateKey() #we do not store this key in wallet
    self.blinding_key = blinding_key
    self.relay_fee = relay_fee
    if coinbase:
      self.version=0
    self.lock_height = lock_height


  def _calc_pedersen_wos(self):
    """
      Calc unauthorized pedersen commitment from generators, blinding key
      and value.
      Note, it is differs from _calc_unauthorized_pedersen (which calc UPC
      from APC and address).
    """
    assert(self.generator and self.address and self.blinding_key and isinstance(self.value, int)) #self.value can be 0
    if self.generator in generators:
      unpc = PedersenCommitment(blinded_generator = generators[self.generator])
    else:
      raise NotImplemented #TODO
    unpc.create(self.value, self.blinding_key.private_key)
    return unpc

  # rename? 
  def _calc_pedersen(self):
    self.unauthorized_pedersen_commitment = self._calc_pedersen_wos()
    

  def _calc_authorized_pedersen(self):
    """
      Calc authorized pedersen commitment from from UPC and address.
    """
    assert self.unauthorized_pedersen_commitment
    assert self.generator
    self.authorized_pedersen_commitment = \
      (self.unauthorized_pedersen_commitment.to_public_key() + self.address.pubkey).to_pedersen_commitment(
      blinded_generator = generators[self.generator])

  def _calc_unauthorized_pedersen(self):
    """
      Calc unauthorized pedersen commitment from from APC and address.
    """
    assert self.authorized_pedersen_commitment
    assert self.generator
    if not self.generator in generators:
      raise NotImplemented
    self.unauthorized_pedersen_commitment = \
      (self.authorized_pedersen_commitment.to_public_key() - self.address.pubkey).to_pedersen_commitment(
      blinded_generator = generators[self.generator])

  #TODO default exp should be more wise
  def generate(self, min_value=0, nonce=None, exp=0, concealed_bits=64):
    """
    Generate output

    Calc all necessery params like APC, rangeproofs and so on. After generating
    ouput is ready for serialization. Params listed below control what should be
    concealed by proof.

    Parameters
    ----------
    address : Address
        Address of output
    [optional] min_value : int
        Default: 0. Constructs a proof where the verifer can tell the minimum
                   value is at least the specified amount.
    [optional] exp : int
        Default: 0. Base-10 exponent. Digits below above will be made public,
                   but the proof will be made smaller. Allowed range is -1 to
                   18 (-1 is a special case that makes the value public. 0 is
                   the most private.)
    [optional] nonce : 32bytes
        Default: random. 32-byte secret nonce used to initialize the proof.
    [optional] concealed_bits : int
        Default:64. Number of bits of the value to keep private. 
                    (0 = auto/minimal, 64). For instance minimal number of bits
                    to conceal value 100 is 7. For proof with 7 bits observer 
                    can check that value is between 0 and 127. If minimal number
                    of bits will be used chainwide observer can with a certain 
                    degree of confidence guess that value is between 64 and 127.
                    
    """    
    self._calc_pedersen()
    self._calc_authorized_pedersen()

    apc = self.authorized_pedersen_commitment.serialize() 
    plaintext = struct.pack( "> 32s Q", self.blinding_key.private_key, self.value)
    self.encrypted_message = encrypt(self.address.pubkey, apc, plaintext);

    additional_data = self.signed_part()
    self.rangeproof = RangeProof(pedersen_commitment=self.unauthorized_pedersen_commitment, additional_data = additional_data)
    if self.version==0:
      res = self.rangeproof._sign(exp=-1, concealed_bits=0,
                                  nonce=nonce)
    elif self.version==1:
      self.rangeproof._sign(min_value=min_value, nonce=nonce,
                        exp=exp, concealed_bits=concealed_bits)
    
  #rename to validate?
  def verify(self):
    """
     Verify IOput.
     
     Requirements for valid ouput:
     0) version is known
     1) address is valid
     2) generator is known
     3) range_proof is valid and signs (version, address, asset_type, encrypted_message, relay_fee)
    """
    if self.version==1 or self.version==0:
      try:
        assert self.address.verify(), "Bad address"
        assert self.generator in generators, "Bad generator"
        assert self.rangeproof.verify(), "Bad rangeproof"
      except AssertionError as e:
        return False
    else:
      return False
    return self.address.verify()

  def info(self):
    """
      Returns dictionary with params extracted from proof:
      'exp', 'mantissa' (the same as concealed bits), 
      'min_value', 'max_value'
    """
    a,b,c,d =  self.rangeproof.info()
    return {'exp':a, 'mantissa':b, 'min_value':c, 'max_value':d}

  def __str__(self):
    s=""
    s+="Output[ coinbase: %s, Pedersen: 0x%s, Pubkey: 0x%s, RangeProof: %s, Value: %s, Fee: %s, Blinding key: %s...]" %(
      "+" if self.version==0 else "-", 
      self.authorized_pedersen_commitment.serialize()[:8].hex(),
      self.address.pubkey.serialize()[:10].hex(),
      "+" if self.rangeproof else "-", 
      str(self.value) if self.value else 'unknown',
      str(self.relay_fee), 
      ('0x'+self.blinding_key.serialize()[:8]) if self.blinding_key else 'unknown', )
    return s
