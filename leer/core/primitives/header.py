import hashlib
from leer.core.utils import encode_target, decode_target
from leer.core.hash.mining_canary import mining_canary_hash

class PoPoW:
  # We use compact version of PoPoW (https://eprint.iacr.org/2017/963.pdf) here
  # Differences from abovemention protocol are:
  # 1. \mu-level chain is chain of headers with hashes (4+2*\mu) zeroes (less
  #    than 2**(256-(4+\mu)*4) )
  # 2. All interlinks with level less than previous header level are skipped
  #    (anyway they are all equal prev hash)
  # 3. If \mu-level chain is empty (there was no header with so much work in it)
  #    this level is not included. However, genesis header hash is allways final
  #    in list. Maximum level is not fixed and thus PoPoW has variable length 
  #    and should contain length. Genesis header is appended to the list to 
  #    prevent using PoPoW from another chain

  def __init__(self, pointers=None):
    self.pointers = pointers
    
  @property
  def prev(self):
    if not len(self.pointers):
      #Genesis header has empty popow
      return b"\x00"*32
    return self.pointers[0]

  def serialize(self):
    ser = len(self.pointers).to_bytes(1,'big')
    for pointer in self.pointers:
      ser += pointer
    return ser

  def deserialize(self, serialized_popow):
    self.deserialize_raw(serialized_popow)

  def deserialize_raw(self, serialized_popow):
    # This function derserialize popow and returns unused serialized data
    self.pointers=[]
    if len(serialized_popow)<1:
      raise Exception("Not enough bytes in PoPoW to store length")
    _len, serialized_popow = serialized_popow[0], serialized_popow[1:]
    for i in range(_len):
      if len(serialized_popow)<32:
        raise Exception("Not enough bytes in PoPoW to store %d pointer"%i)
      pointer,serialized_popow = serialized_popow[:32], serialized_popow[32:]
      self.pointers.append(pointer)
    return serialized_popow

  def check_self_consistency(self):
    # 1. Check that all levels are consistent, except last one (genesis)
    if not len(self.pointers):
      #Genesis block
      return True
    level = self._get_level(self.pointers[0])
    for i in self.pointers[1:-1]:
      next_level = self._get_level(i)
      if level>=next_level:
        return False
    return True

  def _get_level(self, _hash):
    level=-2
    for i in _hash: # Python3: getting element of bytes return integer
      if not i==0:
        break
      level+=1
    return level

  def generate_from_prev(self, prev_popow, prev_hash):
    prev_level = self._get_level(prev_hash)
    self.pointers = [prev_hash]
    current_level = prev_level
    for i in prev_popow.pointers:
      level = self._get_level(i)
      if level<=current_level or level<0:
        continue
      else:
        self.pointers.append(i)
        current_level = self._get_level(i)
    genesis = prev_popow.pointers[-1] if len(prev_popow.pointers) else prev_hash
    if not self.pointers[-1]==genesis:
      self.pointers.append(genesis)
    
  def __eq__(self, another):
    return self.pointers==another.pointers



class VoteData:
  # VoteData contains vector for voting (something like https://github.com/bitcoin/bips/blob/master/bip-0009.mediawiki)
  # This vector is 4 bytes long: 1 byte for hard forks and 3 bytes for soft forks
  # Also it contains one specific type of voting: voting for miner susbsidy which is planned to be variable (under constraints)
  # MinerSubsidyVote is 1 byte long and represents setting reward from 0 to 100% of maximal at this height

  # TODO defaults should be set at higher level
  def __init__(self, forks_vector=b"\x00"*4, miner_subsidy_vote=b"\xff"):
    self.forks_vector = forks_vector
    self.miner_subsidy_vote = miner_subsidy_vote

  @property
  def miner_subsidy_vote_int(self):
    return int.from_bytes(self.miner_subsidy_vote, "big")

  def serialize(self):
    return self.forks_vector+self.miner_subsidy_vote

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)

  def deserialize_raw(self, serialized):
    if len(serialized)<5:
      raise Exception("Not enough bytes for deserialization")
    self.forks_vector, self.miner_subsidy_vote, serialized = serialized[:4], serialized[4:5], serialized[5:]
    return serialized


class Header:
  def __init__(self, height=None, supply=None, merkles=None, popow=None, votedata=None, timestamp=None, target=None, version=None, nonce=None):
    self.height = height
    self.version = version
    self.supply = supply #since miners can vote for changing reward supply is not predetermined function of height
    self.merkles = merkles
    self.popow = popow
    self.votedata = votedata
    self.timestamp = timestamp
    self.target = target
    self.extension_bytes = b"\x00\x00\x00\x00"
    self.nonce = nonce

  @property
  def serialized_merkles(self):
    # self.merkles is list of 3 merkle roots:
    # 1. (unspent) outputs commitment
    # 2. (unspent) outputs data (rangeproof and so on)
    # 3. (unmerged) excesses
    assert len(self.merkles[0])==65
    assert len(self.merkles[1])==32
    assert len(self.merkles[2])==65
    return self.merkles[0] + self.merkles[1] + self.merkles[2]

  @property
  def encoded_target(self):
    significand, order = encode_target(self.target)
    return significand.to_bytes(1,"big") + order.to_bytes(1,"big")

  @property
  def difficulty(self):
    return (2**256)//self.target

  @property
  def template(self):
    '''
      Serialized header without nonce. Templates are used during mining, when we search for acceptable nonce
    '''
    return self.height.to_bytes(4,"big") +\
           self.popow.serialize() +\
           self.votedata.serialize() + \
           self.serialized_merkles + \
           self.supply.to_bytes(8,"big") + \
           int(self.timestamp).to_bytes(5, "big") +\
           self.encoded_target +\
           self.version.to_bytes(1, "big") +\
           self.extension_bytes

  def serialize(self):
    return self.template + self.nonce

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)

  def deserialize_raw(self, serialized):
    if len(serialized)<4:
      raise Exception("Not enough bytes for height deserialization")
    self.height, serialized = int.from_bytes(serialized[:4], "big"), serialized[4:]
    self.popow = PoPoW()
    serialized = self.popow.deserialize_raw(serialized)
    self.votedata = VoteData()
    serialized = self.votedata.deserialize_raw(serialized)
    if len(serialized)<162:
      raise Exception("Not enough bytes for merkle roots deserialization")
    self.merkles, serialized = [serialized[:65],serialized[65:97],serialized[97:162]], serialized[162:]
    if len(serialized)<8:
      raise Exception("Not enough bytes for supply deserialization")
    self.supply, serialized = int.from_bytes(serialized[:8], "big"), serialized[8:]
    if len(serialized)<5:
      raise Exception("Not enough bytes for timestamp deserialization")
    self.timestamp, serialized = int.from_bytes(serialized[:5], "big"), serialized[5:]
    if len(serialized)<5:
      raise Exception("Not enough bytes for target deserialization")
    self.target, serialized = decode_target(serialized[0],serialized[1]), serialized[2:]
    if len(serialized)<1:
      raise Exception("Not enough bytes for version deserialization")
    self.version, serialized = serialized[0], serialized[1:]
    if len(serialized)<4:
      raise Exception("Not enough bytes for extension bytes deserialization")
    self.extension_bytes, serialized = serialized[:4], serialized[4:]
    if len(serialized)<16:
      raise Exception("Not enough bytes for nonce deserialization")
    self.nonce, serialized = serialized[:16], serialized[16:]
    return serialized
    

  def check_self_consistency(self):
    popow_check = self.popow.check_self_consistency()
    # TODO header by itself has enough information to check wether supply and merkles consistent
    return popow_check

  def score(self):
    pass

  @property
  def hash(self):
    return mining_canary_hash(self.serialize())

  @property
  def integer_hash(self):
    return int.from_bytes(self.hash, "big")

  @property
  def prev(self):
    return self.popow.prev

  def next_popow(self):
    template = PoPoW()
    template.generate_from_prev(self.popow, self.hash)
    return template

  def __repr__(self):
    return "<Header %s>"%self.hash

  def __eq__(self, h):
    return (self.height == h.height and
            self.popow == h.popow and
            self.votedata.serialize() == h.votedata.serialize() and
            self.merkles == h.merkles and
            self.supply == h.supply and
            self.timestamp == h.timestamp and
            self.encoded_target == h.encoded_target and
            self.version == h.version and
            self.nonce == h.nonce)


class ContextHeader(Header):
  def __init__(self, header=None):
    if header:
      Header.__init__(self, header.height, header.supply, header.merkles, header.popow, 
                          header.votedata, header.timestamp, header.target, 
                          header.version, header.nonce)
    else:
      Header.__init__(self)
    self.descendants = set()
    self.connected_to_genesis = False
    self.invalid = False
    self.reason = None
    '''
      difference between coins_to_be_mint and supply is sum of `new_outputs_fee`s.
      We set (by default) coins_to_be_mint to 0. It will be overwritten when header become connected to genesis
      and value will be required during context validation.
    '''
    self.coins_to_be_mint = 0 
    self.total_difficulty = 0 

  def serialize_with_context(self):
    ser = super(ContextHeader, self).serialize()
    #TODO what if attacker creates more than 255 headers?
    #It may be extremely cheap for old blocks
    ser += len(self.descendants).to_bytes(1,'big')
    for descendant in self.descendants:
      ser += descendant
    ser += int(self.connected_to_genesis).to_bytes(1,'big')
    ser += int(self.invalid).to_bytes(1,'big')
    reason = self.reason if self.reason else ""
    ser += int(len(reason)).to_bytes(2,'big')
    ser += reason.encode('utf-8')
    ser += self.coins_to_be_mint.to_bytes(8,"big")
    ser += self.total_difficulty.to_bytes(32,"big")
    return ser

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)

  def deserialize_raw(self, serialized):
    #TODO exceptions for not enough bytes
    # No urgency: however we never should get contextHeader from others
    ser = super(ContextHeader, self).deserialize_raw(serialized)
    desc_num, ser = int.from_bytes(ser[:1], 'big'), ser[1:]
    for desc in range(desc_num):
      d, ser = ser[:32], ser[32:]
      self.descendants.add(d)
    self.connected_to_genesis, self.invalid, ser = bool(ser[0]), bool(ser[1]), ser[2:]
    reason_len, ser = int.from_bytes(ser[:2], 'big'), ser[2:]
    self.reason, ser = ser[:reason_len].decode('utf-8'), ser[reason_len:]
    self.coins_to_be_mint, ser = int.from_bytes(ser[:8], "big"), ser[8:]
    self.total_difficulty, ser = int.from_bytes(ser[:32], "big"), ser[32:]
    return ser
    



