from collections import OrderedDict
from functools import partial
import struct, os

from secp256k1_zkp import PrivateKey, PublicKey, PedersenCommitment, RangeProof, default_blinding_generator, Point

from leer.core.lubbadubdub.offset_utils import sum_offset
from leer.core.lubbadubdub.constants import default_generator, default_generator_ser, generators, GLOBAL_TEST
from leer.core.lubbadubdub.address import Address, Excess, excess_from_private_key
from leer.core.lubbadubdub.ioput import IOput
from leer.core.storage.txos_storage import TXOsStorage


from leer.core.parameters.constants import coinbase_maturity, output_creation_fee
from leer.core.primitives.transaction_skeleton import TransactionSkeleton
from leer.core.storage.verification_cache import verification_cache
from leer.core.lubbadubdub.script import evaluate_scripts, check_burdens, generate_proof_script
from leer.core.storage.lookup_utils import excess_lookup

def is_sorted(lst, key=lambda x: x):
    for i, el in enumerate(lst[1:]):
        if key(el) < key(lst[i]): # i is the index of the previous element
            return False
    return True



class Transaction:

  def __init__(self, txos_storage, excesses_storage,  raw_tx=None, key_manager=None):
    #serializable data 
    self.inputs = []
    self.updated_excesses = {} # after spending inputs their addresses excesses should be updated to become additional excesses
    self.outputs = []
    self.additional_excesses = []
    self.mixer_offset = 0
    #inner data
    self._destinations = [] #destinations are unprepared outputs
    self.coinbase = None
    self.new_outputs_fee = None
    self.txid = None
    self.serialized = None

    self.txos_storage = txos_storage 
    self.excesses_storage = excesses_storage 
    self.key_manager = key_manager
    
    if raw_tx:
      self.deserialize(raw_tx)

  def push_input(self, _input):
    self.inputs.append(_input)

  def add_destination(self, destination):
    '''
      Destination is address, value, [optional] need_proof
    '''
    if len(destination)==2:
      destination = (destination[0], destination[1], True)
    self._destinations.append(destination)


  #TODO coinbase should be @property

  def add_coinbase(self, coinbase_output):
    self.serialized = None
    self.coinbase = coinbase_output

  def compose_block_transaction(self, rtx, combined_transaction=None):
    self.serialized = None
    if not self.coinbase:
      raise Exception("coinbase output is required")
    cb = self.coinbase
    self.__init__(txos_storage = self.txos_storage, excesses_storage = self.excesses_storage) #reset self
    self.outputs = [cb]
    offset_pk = PrivateKey()
    self.mixer_offset = int.from_bytes(offset_pk.private_key, "big")
    self.additional_excesses = [excess_from_private_key(cb.blinding_key+offset_pk, b"\x01\x00"+cb.serialized_index[:33])]
    if combined_transaction:
      new_tx = self.merge(combined_transaction)
      self.inputs = new_tx.inputs
      self.outputs = new_tx.outputs
      self.additional_excesses = new_tx.additional_excesses
      self.updated_excesses = new_tx.updated_excesses
    self.verify(rtx=rtx)

  '''
  # should be moved to wallet???
  def generate(self, change_address=None, relay_fee_per_kb=0): #TODO key_manager should be substituted with inputs_info = {..., 'new_address': '', 'priv_by_pub': {'':''}}
    self.serialized = None
    if self.coinbase:
      raise Exception("generate() can be used only for common transaction, to create block transaction as miner use compose_block_transaction")
    if not len(self.inputs):
      raise Exception("Tx should have at least one input")
    if not len(self._destinations):
      raise Exception("Tx should have at least one destination")
    for ioput in self.inputs:
      if not self.key_manager:
        raise Exception("Trying to generate tx which spends unknown input (KeyManager is None)")
      if not ioput.detect_value(self.key_manager):
        raise Exception("Trying to generate tx which spends unknown input")
    in_value = sum([ioput.value for ioput in self.inputs]) 
    out_value = sum([destination[1] for destination in self._destinations])
    relay_fee = self.calc_relay_fee(relay_fee_per_kb=relay_fee_per_kb)
    # +1 for destination is for change address
    self.fee = relay_fee + self.calc_new_outputs_fee(len(self.inputs), len(self._destinations)+1)
    remainder = in_value - out_value - self.fee
    if remainder<0:
      raise Exception("Not enough money in inputs to cover outputs")
    # TODO We need logic here to cover too low remainders (less than new output fee)
    change_address =  change_address if change_address else self.key_manager.new_address() # TODO Check: for first glance, we cannot get here if key_manager is None.
    self._destinations.append((change_address, remainder))
    privkey_sum=0
    out_blinding_key_sum = None
    for out_index in range(len(self._destinations)-1):
      address, value = self._destinations[out_index]
      output = IOput()
      output.fill(address, value, generator = default_generator_ser)
      self.outputs.append( output )
      out_blinding_key_sum = out_blinding_key_sum + output.blinding_key if out_blinding_key_sum else output.blinding_key
    # privkey for the last one output isn't arbitrary
    address, value = self._destinations[-1]
    in_blinding_key_sum = None
    for _input in self.inputs:
      in_blinding_key_sum = in_blinding_key_sum + _input.blinding_key if in_blinding_key_sum else _input.blinding_key
      in_blinding_key_sum += self.key_manager.priv_by_pub(_input.address.pubkey) # we can't get here if key_manager is None
    output = IOput()
    output.fill(address, value, blinding_key = in_blinding_key_sum-out_blinding_key_sum,
      relay_fee=relay_fee, generator = default_generator_ser) #TODO relay fee should be distributed uniformly, privacy leak
    self.outputs.append(output)
    [output.generate() for output in self.outputs]
    self.sort_ioputs()
    self.verify()
  '''

  # should be moved to wallet???
  def generate_new(self, priv_data, rtx, change_address=None, relay_fee_per_kb=0): #TODO key_manager should be substituted with inputs_info = {..., 'new_address': '', 'priv_by_pub': {'':''}}
    self.serialized = None
    if self.coinbase:
      raise Exception("generate() can be used only for common transaction, to create block transaction as miner use compose_block_transaction")
    if not len(self.inputs):
      raise Exception("Tx should have at least one input")
    if not len(self._destinations):
      raise Exception("Tx should have at least one destination")
    for ioput in self.inputs:
      if not ioput.detect_value(inputs_info=priv_data):
        raise Exception("Trying to generate tx which spends unknown input")
    in_value = sum([ioput.value for ioput in self.inputs]) 
    out_value = sum([destination[1] for destination in self._destinations])
    relay_fee = self.calc_relay_fee(relay_fee_per_kb=relay_fee_per_kb)
    # +1 for destination is for change address
    self.fee = relay_fee + self.calc_new_outputs_fee(len(self.inputs), len(self._destinations)+1)
    remainder = in_value - out_value - self.fee
    if remainder<0:
      raise Exception("Not enough money in inputs to cover outputs")
    # TODO We need logic here to cover too low remainders (less than new output fee)
    change_address =  change_address if change_address else priv_data['change address']
    self._destinations.append((change_address, remainder, True))
    privkey_sum=0
    out_blinding_key_sum = None
    need_proofs = []
    excesses_key_sum = None
    for out_index in range(len(self._destinations)-1):
      address, value, need_proof = self._destinations[out_index]
      output = IOput()
      output.fill(address, value, generator = default_generator_ser)
      self.outputs.append( output )
      out_blinding_key_sum = out_blinding_key_sum + output.blinding_key if out_blinding_key_sum else output.blinding_key
      if need_proof:
        need_proofs.append((output, PrivateKey())) #excesses will be generated after output generation
    offset_pk = PrivateKey()
    self.mixer_offset = int.from_bytes(offset_pk.private_key, "big")
    # privkey for the last one output isn't arbitrary
    address, value, need_proof = self._destinations[-1]
    if need_proof:
      need_proofs.append((output, PrivateKey())) #excesses will be generated after output generation
    in_blinding_key_sum = None
    burdens_to_be_covered = []
    for _input in self.inputs:
      in_blinding_key_sum = in_blinding_key_sum + _input.blinding_key if in_blinding_key_sum else _input.blinding_key
      priv_key = priv_data['priv_by_pub'][_input.address.pubkey.serialize()]
      in_blinding_key_sum += priv_key
      if self.txos_storage.confirmed.burden.has(_input.serialized_index, rtx=rtx):
        self.updated_excesses[_input.serialized_index]=excess_from_private_key(priv_key, b"\x01\x00"+_input.serialized_apc)
      else:
        self.updated_excesses[_input.serialized_index]=excess_from_private_key(priv_key, b"\x01\x00"+os.urandom(33))
    if len(need_proofs):
      excesses_key_sum = need_proofs[0][1]
      for i in need_proofs[1:]:
        excesses_key_sum+=i[1]
    output = IOput()
    last_blinding_key = in_blinding_key_sum-out_blinding_key_sum-offset_pk
    if excesses_key_sum:
      last_blinding_key += excesses_key_sum
    output.fill(address, value, blinding_key = last_blinding_key,
      relay_fee=relay_fee, generator = default_generator_ser) #TODO relay fee should be distributed uniformly, privacy leak
    self.outputs.append(output)
    [output.generate() for output in self.outputs]
    for ae in need_proofs:
      script = generate_proof_script(ae[0])
      e = excess_from_private_key(ae[1], script)
      self.additional_excesses.append(e)
    self.sort_ioputs()
    self.verify(rtx=rtx)
    

  def calc_relay_fee(self, relay_fee_per_kb):
    inputs_num, outputs_num, excesses_num = len(self.inputs), len(self._destinations)+1, len(self.additional_excesses)
    input_size = 67+2
    output_size = 5366+2
    excess_size = 65+2
    mixer_offset_size = 32
    estimated_size = 6+inputs_num*input_size + outputs_num*output_size + excesses_num*excess_size + mixer_offset_size
    return int((estimated_size/1000.)*relay_fee_per_kb)


  def calc_new_outputs_fee(self, inputs_num=None, outputs_num=None):
    return ( (outputs_num if outputs_num else len(self.outputs)) -
             (inputs_num if inputs_num else len(self.inputs)) - 
             (1 if self.coinbase else 0))*output_creation_fee

  def sort_ioputs(self):
      self.inputs = sorted(self.inputs, key= lambda _input: _input.authorized_pedersen_commitment.serialize())
      self.outputs = sorted(self.outputs, key= lambda _output: _output.authorized_pedersen_commitment.serialize())

  #XXX: obsolete, to be deleted
  def calc_txid(self):
    if not len(self.inputs) or not len(self.outputs):
      raise Exception("Tx is not ready for id formation")
    self.sort_ioputs()
    to_hash = b''
    for _list in [self.inputs, self.outputs]:
        for ioput in _list:
            to_hash += ioput.pedersen_commitment.serialize()
    if not GLOBAL_TEST:
        raise NotImplemented 
    h = hashlib.new('sha256')
    h.update(to_hash)
    self.txid = h.digest()

  def serialize(self):
    if self.serialized:
      return self.serialized
    ret=b""
    ret += struct.pack("> H", len(self.inputs)) 
    for _input in self.inputs:
        s_i = _input.serialized_index
        ret += struct.pack("> H", len(s_i))
        ret += s_i

    ret += struct.pack("> H", len(self.outputs)) 
    for _output in self.outputs:
        s_o = _output.serialize()
        ret += struct.pack("> H", len(s_o))
        ret += _output.serialize()

    ret += struct.pack("> H", len(self.additional_excesses)) 
    for _excess in self.additional_excesses:
        s_e = _excess.serialize()
        ret += struct.pack("> H", len(s_e))
        ret += s_e
    for _input in self.inputs:
        s_ue = self.updated_excesses[_input.serialized_index].serialize()
        ret += struct.pack("> H", len(s_ue))
        ret += s_ue
    ret += self.mixer_offset.to_bytes(32, "big")
    self.serialized = ret
    return ret

  def deserialize(self, serialized_tx, rtx, skip_verification=False):
    self.serialized = None
    if len(serialized_tx)<2:
        raise Exception("Serialized transaction doesn't contain enough bytes for inputs array length")
    inputs_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
    (inputs_len,) = struct.unpack("> H", inputs_len_buffer) 
    for _input_index in range(inputs_len):
        if len(serialized_tx)<2:
          raise Exception("Serialized transaction doesn't contain enough bytes for input %s length"%_input_index)
        input_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
        (input_len,) = struct.unpack("> H", input_len_buffer)
        if len(serialized_tx)<input_len:
          raise Exception("Serialized transaction doesn't contain enough bytes for input %s"%_input_index)
        input_index_buffer, serialized_tx = serialized_tx[:input_len], serialized_tx[input_len:]

        if not GLOBAL_TEST['spend from mempool']:
            raise NotImplemented
        else:
          if not skip_verification:
            if (not self.txos_storage.confirmed.has(input_index_buffer, rtx=rtx)):
              raise Exception("Unknown input index")
            self.inputs.append(self.txos_storage.confirmed.get(input_index_buffer, rtx=rtx))
          else:
            self.inputs.append(input_index_buffer)

    if len(serialized_tx)<2:
        raise Exception("Serialized transaction doesn't contain enough bytes for outputs array length")
    outputs_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
    (outputs_len,) = struct.unpack("> H", outputs_len_buffer)
    for _output_index in range(outputs_len):
      if len(serialized_tx)<2:
          raise Exception("Serialized transaction doesn't contain enough bytes for output %s length"%_output_index)
      output_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
      (output_len,) = struct.unpack("> H", output_len_buffer)
      if len(serialized_tx)<output_len:
          raise Exception("Serialized transaction doesn't contain enough bytes for output %s"%_output_index)
      output_buffer, serialized_tx = serialized_tx[:output_len], serialized_tx[output_len:]
      self.outputs.append(IOput(binary_object=output_buffer) )

    if len(serialized_tx)<2:
        raise Exception("Serialized transaction doesn't contain enough bytes for additional excesses array length")
    aes_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
    (aes_len,) = struct.unpack("> H", aes_len_buffer)
    for _ae in range(aes_len):
      if len(serialized_tx)<2:
          raise Exception("Serialized transaction doesn't contain enough bytes for additional excess %s length"%_ae)
      ae_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
      (ae_len,) = struct.unpack("> H", ae_len_buffer)
      if len(serialized_tx)<ae_len:
          raise Exception("Serialized transaction doesn't contain enough bytes for additional excess %s"%_ae)
      ae_buffer, serialized_tx = serialized_tx[:ae_len], serialized_tx[ae_len:]
      e = Excess()
      e.deserialize_raw(ae_buffer)
      self.additional_excesses.append(e )

    for _ue in range(inputs_len):
      if len(serialized_tx)<2:
          raise Exception("Serialized transaction doesn't contain enough bytes for updated excess %s length"%_ue)
      ue_len_buffer, serialized_tx =serialized_tx[:2], serialized_tx[2:]
      (ue_len,) = struct.unpack("> H", ue_len_buffer)
      if len(serialized_tx)<ue_len:
          raise Exception("Serialized transaction doesn't contain enough bytes for updated excess %s"%_ue)
      ue_buffer, serialized_tx = serialized_tx[:ue_len], serialized_tx[ue_len:]
      e = Excess()
      e.deserialize_raw(ue_buffer)
      #Depending on skif_verification self.inputs either contains inputs or serialized_indexes only
      if isinstance(self.inputs[_ue], bytes):
        self.updated_excesses[self.inputs[_ue]]=e        
      elif isinstance(self.inputs[_ue], IOput):
        self.updated_excesses[self.inputs[_ue].serialized_index]=e
    if len(serialized_tx)<32:
        raise Exception("Serialized transaction doesn't contain enough bytes for mixer_offset")
    self.mixer_offset, serialized_tx = int.from_bytes(serialized_tx[:32], "big"), serialized_tx[32:]
    if not skip_verification:
      self.verify(rtx=rtx)
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented

  def to_json(self):
    pass #TODO

  def from_json(self):
    pass #TODO

  def non_context_verify(self, block_height):
    #Actually we partially use context via block_height. Consider renaming.
    try:
      if verification_cache[(self.serialize(), block_height)]:
        #We set coinbase during verification, thus if we scip verification
        #we need to set it manually. TODO (verification should be free from initialisation stuff)
        for output in self.outputs:
          if output.version==0:
            self.coinbase = output
        return verification_cache[(self.serialize(), block_height)]
    except KeyError:
      pass

    assert is_sorted(self.inputs, key= lambda _input: _input.authorized_pedersen_commitment.serialize()), "Inputs are not sorted"
    assert is_sorted(self.outputs, key= lambda _output: _output.authorized_pedersen_commitment.serialize()), "Outputs are not sorted"

    assert len(self.inputs)==len(self.updated_excesses)
    for _input in self.inputs:
       assert _input.lock_height<block_height, "Timelocked input"
       s_i = _input.serialized_index
       assert s_i in self.updated_excesses, "Updated excesses do not contain update for address %s"%_input.address.to_text()
       assert _input.address.serialized_pubkey == self.updated_excesses[s_i].serialized_pubkey

    #Check that there are no duplicated outputs
    #TODO probably authorized????
    assert len(set([_output.unauthorized_pedersen_commitment.serialize() for _output in self.outputs]))==len(self.outputs), "Duplicated output"

    coinbase_num=0
    
    output_apcs = []

    for output in self.outputs:
        assert output.verify(), "Nonvalid output"
        _o_index =output.serialized_index
        output_apcs.append(_o_index[:33])
        if output.version==0:
            coinbase_num+=1
            self.coinbase = output
    assert coinbase_num<2, "More then one coinbase"

    for excess in self.additional_excesses:
        assert excess.verify(), "Nonvalid excess"
        #if not excess.message in output_apcs:
        #  return False
        #else:
        #  output_apcs.remove(excess.message)

    left_side, right_side = [], []

    _t = PublicKey()

    # Transaction should contain outputs (while it may not contain inputs)
    assert len(self.outputs), "Empty outputs"

    if len(self.inputs):
      _t.combine([_input.authorized_pedersen_commitment.to_public_key().public_key for _input in self.inputs])
      inputs_pedersen_commitment_sum = _t.to_pedersen_commitment()
      left_side.append(inputs_pedersen_commitment_sum)

    if len(self.outputs):
      _t.combine([_output.authorized_pedersen_commitment.to_public_key().public_key for _output in self.outputs])
      outputs_pedersen_commitment_sum = _t.to_pedersen_commitment()
      right_side.append(outputs_pedersen_commitment_sum)

      _t.combine([_output.address.pubkey.public_key for _output in self.outputs])
      outputs_excesses_sum = _t.to_pedersen_commitment()
      left_side.append(outputs_excesses_sum )

    if len(self.additional_excesses):
        _t.combine([excess.pubkey.public_key for excess in self.additional_excesses])
        additional_excesses_sum = _t.to_pedersen_commitment()
        left_side.append(additional_excesses_sum)

    if coinbase_num:
        minted_pc = PedersenCommitment(value_generator = default_generator)
        minted_pc.create(self.coinbase.value, b'\x00'*32)
        left_side.append(minted_pc)
     
     
    relay_fee = 0   
    for _output in self.outputs:
      if not _output.version==0:
        if _output.generator==default_generator_ser:
          relay_fee += _output.relay_fee

    new_outputs_fee = self.calc_new_outputs_fee()
    fee = relay_fee + new_outputs_fee

    negative_fee = False
    if fee<0:
      # It's okay, transaction has consumed so many inputs that it is profitable by itself
      # however we need to handle it manually: libsecp256k1 cannot handle negative value
      negative_fee = True
      fee = -fee

    if not fee==0:
      fee_pc = PedersenCommitment(value_generator = default_generator) #TODO think about fees for assets
      fee_pc.create(fee, b'\x00'*32)
      if negative_fee:
        left_side.append(fee_pc)
      else:
        right_side.append(fee_pc)

    mixer_pc = (Point(default_blinding_generator)*self.mixer_offset).to_pedersen_commitment() #TODO we should optimise here and generate fee_mixer pc
    right_side.append(mixer_pc)

    checker = PedersenCommitment()
    # For transaction which contains coinbase only, both sides will be empty
    if len(left_side) or len(right_side):
      sum_to_zero = checker.verify_sum(left_side, right_side)
      assert sum_to_zero, "Non-zero Pedersen commitments summ"

    if self.coinbase:
      info = self.coinbase.info()
      assert info['exp'] == -1, "Non-transparent coinbase"
      assert self.coinbase.lock_height >= block_height + coinbase_maturity,\
             "Wrong coinbase maturity timelock: %d should be %d"%(\
              self.coinbase.lock_height, block_height + coinbase_maturity)

    tx_skel = TransactionSkeleton(tx=self)
    assert len(tx_skel.serialize(rich_format=False))<50000, "Too big tx_skeleton"
    verification_cache[(self.serialize(), block_height)] = True
    return True

  def verify(self, rtx, block_height = None, skip_non_context=False):
    """
     Transaction is valid if:
      0) inputs and outputs are sorted  (non context verification)
      1) all inputs are in utxo set
      2) no outputs are in utxo
      3) no updated_excesses duplicate already existed 
      3) all outputs are unique (exactly equal outputs are prohibited) (non context verification)
      3) all outputs are valid (non context verification)
      4) all additional excesses are valid (non context verification)
      5) sum(inputs)+sum(additional_excesses)+sum(outputs_excesses)+sum(minted_coins) == sum(outputs) + sum(fee) (non context verification)
      6) For each combined excess sum(digested_excesses) == combined_excess (non context verification)
      7) if coinbase is presented lock_height is set correctly (non context verification)
      8) size check : serialized tx_skeleton should have size less than 50k bytes (non context verification)
    """
    if not block_height:
      # Why +1 is here:
      # There are two general cases for verifying transactions:
      # 1) While generating new transaction. In this case transaction will be in the next block.
      # 2) While checking transaction in the block. In this case, current blockchain state is set 
      #     to prev block (prev to which we are checking) and block_height is current+1
      block_height = self.txos_storage.storage_space.blockchain.current_height(rtx=rtx) + 1

    if not skip_non_context: # skip_non_context is used when non context verification for that tx was made earlier
      assert self.non_context_verify(block_height)

    if not GLOBAL_TEST['spend from mempool']:
        raise NotImplemented #XXX Check that all inputs in UTXO
    else:
        database_inputs = []
        assert len(set([_input.serialized_index for _input in self.inputs]))==len(self.inputs)
        for _input in self.inputs:
          index=_input.serialized_index
          if not self.txos_storage.confirmed.has(index, rtx=rtx):
              raise Exception("Spend unknown output")
          else:
              database_inputs.append(self.txos_storage.confirmed.get(index, rtx=rtx))
          assert not self.excesses_storage.excesses.has_index(rtx, self.updated_excesses[index].index), "Duplication of already existed excess during update"
          self.inputs = database_inputs
    
    if not GLOBAL_TEST['spend from mempool']:
        raise NotImplemented #XXX Check that all inputs are in UTXOSet
    else:
        for _output in self.outputs:
          _o_index = _output.serialized_index
          if self.txos_storage.confirmed.has(_o_index, rtx=rtx):
              raise Exception("Create duplicate output")
          elif _o_index in self.txos_storage.mempool:
              pass #It's ok
          else:
              #previously unknown output, let's add to database
              self.txos_storage.mempool[_o_index] = _output

    for _ae in self.additional_excesses:
      assert not self.excesses_storage.excesses.has_index(rtx, _ae.index), "New additional excess duplicates old one"

    if not GLOBAL_TEST['block_version checking']: 
        # Note, transactions where outputs have different block_versions are valid
        # by consensus rules. However, they cannot be included into any block.
        raise NotImplemented

    if block_height > 0:
      prev_block_props = {'height': self.txos_storage.storage_space.blockchain.current_height(rtx=rtx), 
                        'timestamp': self.txos_storage.storage_space.headers_storage.get(self.txos_storage.storage_space.blockchain.current_tip(rtx=rtx), rtx=rtx).timestamp}
    else:
      prev_block_props = {'height':0, 'timestamp':0}
    excess_lookup_partial = partial(excess_lookup, rtx=rtx, tx=self, excesses_storage = self.excesses_storage)
    assert evaluate_scripts(self, prev_block_props, excess_lookup_partial), "Bad script"
    assert check_burdens(self, self.txos_storage.confirmed.burden, self.excesses_storage, rtx=rtx), "Burden is not satisfied"

    return True
    #[inputs_pedersen_commitment_sum, outputs_excesses_sum, additional_excesses_sum], [outputs_pedersen_commitment_sum, fee_pc])
    #sum(inputs)+sum(additional_excesses)+sum(outputs_excesses) == sum(outputs) + sum(fee)
    

  def merge(self, another_tx, rtx):
    self.serialized = None
    tx=Transaction(txos_storage = self.txos_storage, key_manager = self.key_manager, excesses_storage=self.excesses_storage) #TODO instead of key_manager, inputs info should be merged here
    tx.inputs=self.inputs+another_tx.inputs
    tx.outputs=self.outputs+another_tx.outputs
    tx.additional_excesses = self.additional_excesses + another_tx.additional_excesses
    tx.updated_excesses = self.updated_excesses.copy()
    tx.updated_excesses.update(another_tx.updated_excesses)
    tx.mixer_offset = sum_offset(self.mixer_offset, another_tx.mixer_offset)
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented
      #tx.combined_excesses = self.combined_excesses.update(another_tx.combined_excesses)
    tx.sort_ioputs()
    if not GLOBAL_TEST['spend from mempool']: 
      # If we merge transactions where the second spends outputs from the first, result is invalid
      # since we don't delete identical ioputs 
      raise NotImplemented
    assert tx.verify(rtx=rtx)
    return tx

  def __repr__(self):
    s=""
    s+="Inputs:\n"
    for _input in self.inputs:
       s+=" "*4+_input.__str__()+"\n"
    
    s+="Outputs:\n"
    for _output in self.outputs:
       s+=" "*4+_output.__str__()+"\n"
    return s

  @property
  def relay_fee(self):
    fee = 0
    for _output in self.outputs:
       fee += _output.relay_fee
    return fee

    
