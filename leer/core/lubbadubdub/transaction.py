from collections import OrderedDict
import struct

from secp256k1_zkp import PrivateKey, PublicKey, PedersenCommitment, RangeProof

from leer.core.lubbadubdub.constants import default_generator, default_generator_ser, generators, GLOBAL_TEST
from leer.core.lubbadubdub.address import Address, Excess, excess_from_private_key
from leer.core.lubbadubdub.ioput import IOput
from leer.core.storage.txos_storage import TXOsStorage


from leer.core.parameters.constants import coinbase_maturity, output_creation_fee

from leer.core.primitives.transaction_sceleton import TransactionSceleton

def is_sorted(lst, key=lambda x: x):
    for i, el in enumerate(lst[1:]):
        if key(el) < key(lst[i]): # i is the index of the previous element
            return False
    return True



class Transaction:

  def __init__(self, txos_storage, raw_tx=None, key_manager=None):
    #serializable data 
    self.inputs = []
    self.outputs = []
    self.additional_excesses = []
    self.combined_excesses = OrderedDict()
    #inner data
    self._destinations = [] #destinations are unprepared outputs
    self.coinbase = None
    self.new_outputs_fee = None
    self.txid = None

    self.txos_storage = txos_storage #we can switch fron global txos_storage to stubs for testing
    self.key_manager = key_manager
    
    if raw_tx:
      self.deserialize(raw_tx)

  def push_input(self, _input):
    self.inputs.append(_input)

  def add_destination(self, destination):
    self._destinations.append(destination)


  #TODO coinbase should be @property

  def add_coinbase(self, coinbase_output):
    self.coinbase = coinbase_output

  def compose_block_transaction(self, combined_transaction=None):
    if not self.coinbase:
      raise Exception("coinbase output is required")
    cb = self.coinbase
    self.__init__(txos_storage = self.txos_storage) #reset self
    self.outputs = [cb]
    self.additional_excesses = [excess_from_private_key(cb.blinding_key, cb.serialized_index[:33])]
    if combined_transaction:
      new_tx = self.merge(combined_transaction)
      self.inputs = new_tx.inputs
      self.outputs = new_tx.outputs
      self.additional_excesses = new_tx.additional_excesses
      self.combined_excesses = new_tx.combined_excesses
    self.verify()


  # should be moved to wallet???
  def generate(self, change_address=None):
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
    relay_fee = self.calc_relay_fee()
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
    # privkey for last one output isn't arbitrary
    address, value = self._destinations[-1]
    in_blinding_key_sum = None
    for _input in self.inputs:
      in_blinding_key_sum = in_blinding_key_sum + _input.blinding_key if in_blinding_key_sum else _input.blinding_key
      in_blinding_key_sum += self.key_manager.priv_by_pub(_input.address.pubkey) # we cant get here if key_manager is None
    output = IOput()
    output.fill(address, value, blinding_key = in_blinding_key_sum-out_blinding_key_sum,
      relay_fee=relay_fee, generator = default_generator_ser) #TODO relay fee should be distributed uniformly, privacy leak
    self.outputs.append(output)
    [output.generate() for output in self.outputs]
    self.sort_ioputs()
    self.verify()
    

  def calc_relay_fee(self, relay_fee_per_kb=0):
    pass #TODO
    return 0


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
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented
    return ret

  def deserialize(self, serialized_tx):
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
          if not input_index_buffer in self.txos_storage.confirmed:
            raise Exception("Unknown input index")
          self.inputs.append(self.txos_storage.confirmed[input_index_buffer])

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

    self.verify()
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented

  def to_json(self):
    pass #TODO

  def from_json(self):
    pass #TODO

  def non_context_verify(self, block_height):
    #Actually we partially use context via block_height. Consider renaming.

    assert is_sorted(self.inputs, key= lambda _input: _input.authorized_pedersen_commitment.serialize()), "Inputs are not sorted"
    assert is_sorted(self.outputs, key= lambda _output: _output.authorized_pedersen_commitment.serialize()), "Outputs are not sorted"

    for _input in self.inputs:
       assert _input.lock_height<block_height, "Timelocked input"

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
        if not excess.message in output_apcs:
          return False
        else:
          output_apcs.remove(excess.message)

    left_side, right_side = [], []

    _t = PublicKey()

    # Transaction should contain either outputs (while it may not contain inputs)
    # either combined excesses (for transactions which only delete excesses)
    assert len(self.outputs) or len(self.combined_excesses), "Empty outputs"

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
        minted_pc = PedersenCommitment(blinded_generator = default_generator)
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
      # Its okay, transaction consumed so many inputs that it is profitable by itself
      # however we need to handle it manually: libsecp256k1 cannot handle negative value
      negative_fee = True
      fee = -fee

    if not fee==0:
      fee_pc = PedersenCommitment(blinded_generator = default_generator) #TODO think about fees for assets
      fee_pc.create(fee, b'\x00'*32)
      if negative_fee:
        left_side.append(fee_pc)
      else:
        right_side.append(fee_pc)

    checker = PedersenCommitment()
    # For transaction which contains coinbase only, both sides will be empty
    if len(left_side) or len(right_side):
      sum_to_zero = checker.verify_sum(left_side, right_side)
      assert sum_to_zero, "Non-zero Pedersen commitments summ"

    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented
    if self.coinbase:
      info = self.coinbase.info()
      assert info['exp'] == -1, "Non-transparent coinbase"
      # TODO Ugly ->`self.txos_storage.storage_space.blockchain.current_height`
      assert self.coinbase.lock_height >= block_height + coinbase_maturity,\
             "Wrong coinbase maturity timelock: %d should be %d"%(\
              self.coinbase.lock_height, block_height + coinbase_maturity)

    tx_scel = TransactionSceleton(tx=self)
    assert len(tx_scel.serialize(rich_format=False))<50000, "Too big tx_sceleton"
    return True

    

  def verify(self, block_height = None, skip_non_context=False):
    """
     Transaction is valid if:
      0) inputs and outputs are sorted  (non context verification)
      1) all inputs are in utxo set
      2) no outputs are in utxo 
      3) all outputs are unique (exactly equal outputs are prohibited) (non context verification)
      3) all outputs are valid (non context verification)
      4) all additional excesses are valid (non context verification)
      5) sum(inputs)+sum(additional_excesses)+sum(outputs_excesses)+sum(minted_coins) == sum(outputs) + sum(fee) (non context verification)
      6) For each combined excess sum(digested_excesses) == combined_excess (non context verification)
      7) if coinbase is presented lock_height is set correctly (non context verification)
      8) size check : serialized tx_sceleton should have size less than 50k bytes (non context verification)
    """
    if not block_height:
      # Why +1 is here:
      # There are two general cases for verifying transactions:
      # 1) While generating new transaction. In this case transaction will be in the next block.
      # 2) While checkin tx in block. In this height of this block is passed.
      block_height = self.txos_storage.storage_space.blockchain.current_height + 1

    if not skip_non_context: # skip_non_context is used when non context verification for that tx was made earlier
      assert self.non_context_verify(block_height)

    if not GLOBAL_TEST['spend from mempool']:
        raise NotImplemented #XXX Check that all inputs in UTXO
    else:
        database_inputs = []
        assert len(set([_input.serialized_index for _input in self.inputs]))==len(self.inputs)
        for _input in self.inputs:
          index=_input.serialized_index
          if not index in self.txos_storage.confirmed:
              raise Exception("Spend unknown output")
          else:
              database_inputs.append(self.txos_storage.confirmed[index])
          self.inputs = database_inputs
           

    
    if not GLOBAL_TEST['spend from mempool']:
        raise NotImplemented #XXX Check that all inputs in UTXO
    else:
        for _output in self.outputs:
          _o_index = _output.serialized_index
          if _o_index in self.txos_storage.confirmed:
              raise Exception("Create duplicate output")
          elif _o_index in self.txos_storage.mempool:
              pass #It's ok
          else:
              #previously unknown output, lets add to database
              self.txos_storage.mempool[_o_index] = _output


    if not GLOBAL_TEST['block_version checking']: 
        # Note transactions, where outputs have different block_versions are valid
        # by consensus rules however they cannot be included into any block
        raise NotImplemented


    return True
    #[inputs_pedersen_commitment_sum, outputs_excesses_sum, additional_excesses_sum], [outputs_pedersen_commitment_sum, fee_pc])
    #sum(inputs)+sum(additional_excesses)+sum(outputs_excesses) == sum(outputs) + sum(fee)
    

  def merge(self, another_tx):
    tx=Transaction(txos_storage = self.txos_storage, key_manager = self.key_manager)
    tx.inputs=self.inputs+another_tx.inputs
    tx.outputs=self.outputs+another_tx.outputs
    tx.additional_excesses = self.additional_excesses + another_tx.additional_excesses
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented
      #tx.combined_excesses = self.combined_excesses.update(another_tx.combined_excesses)
    tx.sort_ioputs()
    if not GLOBAL_TEST['spend from mempool']: 
      # If we merge transactions where second spends outputs from first, result is invalid
      # since we don't delete identical ioputs 
      raise NotImplemented
    assert tx.verify()
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
    
