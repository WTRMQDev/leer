from leer.core.primitives.header import Header, PoPoW, VoteData
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.chains.headers_manager import HeadersManager
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.primitives.transaction_skeleton import TransactionSkeleton
from leer.core.lubbadubdub.transaction import Transaction
from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.offset_utils import sum_offset
from time import time
from leer.core.parameters.dynamic import next_reward, next_target
from leer.core.parameters.constants import initial_target


class Block():

  def __init__(self, storage_space, header=None, transaction_skeleton=None):
    self._header = header if header else Header()
    self.transaction_skeleton = transaction_skeleton if transaction_skeleton else TransactionSkeleton()
    self.tx=None
    self.storage_space = storage_space

  @property
  def header(self):
    try:
      return self._header
    except:
      self._header = Header()
      return self._header  

  @property
  def hash(self):
    return self.header.hash

  def serialize(self, rtx, rich_block_format=False, max_size =40000):
    serialized=b""
    serialized += self.header.serialize()
    serialized += self.transaction_skeleton.serialize(rich_format=rich_block_format, max_size=max_size,
        full_tx = build_tx_from_skeleton(self.transaction_skeleton,\
                                         self.storage_space.txos_storage,
                                         self.storage_space.excesses_storage, self.header.height, rtx=rtx,\
                                         historical = True) if rich_block_format else None)
    return serialized

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)


  def deserialize_raw(self, serialized):
    serialized = self.header.deserialize_raw(serialized)
    serialized = self.transaction_skeleton.deserialize_raw(serialized, storage_space=self.storage_space)
    return serialized

  def non_context_verify(self, rtx):
    '''
      To verify block we need to
        0) check that header is known and valid
        1) verify transaction 
        2) check that transaction can be applied 
        3) #logic error, this is context validation# check that after tx applied to prev state, new state roots 
           and checksums coinside with block header
        4) check reward size (actually in can be checked on headers level)
    '''
    # stage 1
    assert self.storage_space.headers_storage.has(self.header.hash, rtx=rtx), "Block's header is unknown"
    #self.storage_space.headers_storage.context_validation(self.header.hash)
    assert not self.storage_space.headers_storage.get(self.header.hash, rtx=rtx).invalid, "Block's header is invalid. Reason: `%s`"%self.storage_space.headers_storage.get(self.header.hash, rtx=rtx).reason

    #currently during building we automatically check that tx can ba applied and tx is valid
    self.tx = build_tx_from_skeleton(self.transaction_skeleton, txos_storage=self.storage_space.txos_storage,
                                     excesses_storage=self.storage_space.excesses_storage,
                                     block_height=self.header.height, rtx=rtx, non_context = True)
    # stage 3 => should be moved to blockchain
    #commitment_root, txos_root = self.storage_space.txos_storage.apply_tx_get_merkles_and_rollback(tx)
    #excesses_root = self.storage_space.excesses_storage.apply_tx_get_merkles_and_rollback(tx)
    #assert [commitment_root, txos_root, excesses_root]==self.header.merkles

    # This is context validation too??? TODO
    assert self.tx.coinbase.value == (next_reward(self.header.prev, self.storage_space.headers_storage, rtx=rtx)+self.transaction_skeleton.relay_fee), "Wrong block subsidy"
    
    return True


  def __str__(self):
    return "Block< hash: %s..., height: %d, inputs: %d, outputs %d>"%(self.header.hash[:6], self.header.height
                    , len(self.transaction_skeleton.input_indexes),len(self.transaction_skeleton.output_indexes) )
    

def build_tx_from_skeleton(tx_skeleton, txos_storage, excesses_storage, block_height, rtx, historical=False, non_context = False):
  '''
    By given tx_skeleton and txos_storage return transaction.
    If transaction is invalid or any input/output isn't available exception will be raised.
    Optionally, if `historical` is True we will check output_indexes both in mempool and spent outputs. 
  '''
  tx=Transaction(txos_storage=txos_storage, excesses_storage=excesses_storage)
  for _i in tx_skeleton.input_indexes:
       tx.inputs.append(txos_storage.confirmed.get(_i, rtx=rtx))
  for _o in tx_skeleton.output_indexes:
       if historical:
         try:
           tx.outputs.append(txos_storage.confirmed.find(_o, rtx=rtx))
         except:
           tx.outputs.append(txos_storage.mempool[_o])
       else:
         tx.outputs.append(txos_storage.mempool[_o])
  tx.additional_excesses = tx_skeleton.additional_excesses.copy()
  tx.updated_excesses = tx_skeleton.updated_excesses.copy()
  tx.mixer_offset = tx_skeleton.mixer_offset
  if historical or non_context:
    assert tx.non_context_verify(block_height=block_height)
  else:
    assert tx.verify(block_height=block_height, rtx=rtx)
  return tx

#To setup utils
def generate_genesis(tx, storage_space, wtx):
    '''
        1. spend inputs and add outputs and excesses from tx to storage
        2. calc new mercles
        3. generate header
        4. rollback outputs
    '''
    storage = storage_space.txos_storage
    excesses = storage_space.excesses_storage

    exc_merkle = excesses.apply_tx_get_merkles_and_rollback(tx, wtx=wtx) # it should be calced first, since we nned to calc address_excess_num_index
    merkles = storage.apply_tx_get_merkles_and_rollback(tx, wtx=wtx) + [exc_merkle]
    popow = PoPoW([])
    votedata = VoteData()
    target = initial_target
    full_offset = tx.mixer_offset
    header=Header(height = 0, supply=tx.coinbase.value, full_offset=full_offset, merkles=merkles, popow=popow, votedata=votedata, timestamp=int(time()), target=target, version=int(1), nonce=b"\x00"*16)
    
    tx_skeleton = TransactionSkeleton(tx=tx)
    new_block = Block(storage_space, header, tx_skeleton)
    return new_block




def generate_block_template(tx, storage_space, wtx, get_tx_from_mempool = True, timestamp = None):
    '''
        Generate block template: block is correct but nonce (by default) is equal to zero.
        Thus difficulty target (almost always) isn't met.
        arguments:
          tx [mandatory]: transaction which contains coinbase output. It also may contain other inputs and outputs.
          storage_space [mandatory] : -
          get_tx_from_mempool [optional, default True]: if get_tx_from_mempool, transaction from mempool will be merged to block_transaction. If this merge will produce invalid tx (for instance tx from mempool spends the same inputs as tx with coinbase), tx from mempool will be discarded.

        Inner logic:
        1. apply block_tx to txos_storage and excesses_storage
        2. calc new merkles
        3. generate header with new merkles
        4. generate block by appending tx_skeleton and new header
        5. rollback block_tx
    '''

    storage = storage_space.txos_storage
    excesses = storage_space.excesses_storage
    current_block = storage_space.blocks_storage.get(storage_space.blockchain.current_tip(rtx=wtx), rtx=wtx)
    if get_tx_from_mempool:
      try:
        tx = tx.merge(storage_space.mempool_tx.give_tx(), rtx=wtx)
      except:
        pass

    exc_merkle = excesses.apply_tx_get_merkles_and_rollback(tx, wtx=wtx) # it should be calced first, since we nned to calc address_excess_num_index
    merkles = storage.apply_tx_get_merkles_and_rollback(tx, wtx=wtx) + [exc_merkle]

    popow = current_block.header.next_popow()
    #We subtract relay fee, since coinbase value contain relay fees, but it isn't new money, but redistribution
    supply = current_block.header.supply + tx.coinbase.value - tx.calc_new_outputs_fee() - tx.relay_fee 
    height = current_block.header.height+1
    votedata = VoteData()
    target = next_target(current_block.hash, storage_space.headers_storage, rtx=wtx)    
    full_offset = sum_offset(current_block.header.full_offset,tx.mixer_offset)
    if not timestamp:
      timestamp = max(int(time()), storage_space.headers_storage.get(storage_space.blockchain.current_tip(rtx=wtx), rtx=wtx).timestamp+1)
    header=Header(height = height, supply=supply, full_offset=full_offset, merkles=merkles, popow=popow, votedata=votedata, timestamp=timestamp, target=target, version=int(1), nonce=b"\x00"*16)
    
    tx_skeleton = TransactionSkeleton(tx=tx)
    new_block = Block(storage_space, header, tx_skeleton)
    return new_block


class ContextBlock(Block):
  # TODO consider removing ContextBlock. For now we store all information about validity in ContextHeader
  # (it allows headers_manager to provide less useless paths).
  '''
    Wrapper of Block for inner storage. It contains contextual info about block: for instance is it valid in chain or not.
  '''
  def __init__(self, storage_space = None, block=None):
    if block:
      Block.__init__(self, storage_space= block.storage_space, header=block.header, transaction_skeleton=block.transaction_skeleton)
      if block.tx:
        self.tx=block.tx
    else:
      if not storage_space:
        raise TypeError("ContextBlock initialized without context")
      Block.__init__(self, storage_space)
    self.invalid = False
    self.reason = None

  def serialize_with_context(self):
    ser = super(ContextBlock, self).serialize(rtx=None) # We can pass None as rtx, since rtx is required for rich block serialization
    ser += int(self.invalid).to_bytes(1,'big')
    reason = self.reason if self.reason else ""
    ser += int(len(reason)).to_bytes(2,'big')
    ser += reason.encode('utf-8')
    return ser

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)

  def deserialize_raw(self, serialized):
    ser = super(ContextBlock, self).deserialize_raw(serialized)
    self.invalid, ser = bool(ser[0]), ser[1:]
    reason_len, ser = int.from_bytes(ser[:2], 'big'), ser[2:]
    self.reason, ser = ser[:reason_len].decode('utf-8'), ser[reason_len:]
    return ser
    
  def __str__(self):
    return "ContextBlock< hash: %s..., height: %d, inputs: %d, outputs %d, valid: %s, reason %s>"%(self.header.hash[:6], self.header.height
                    , len(self.transaction_skeleton.input_indexes),len(self.transaction_skeleton.output_indexes),
                    ("-" if self.invalid else '+'), self.reason  )


