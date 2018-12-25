from leer.core.primitives.transaction_skeleton import TransactionSkeleton
from leer.core.lubbadubdub.transaction import Transaction
from leer.core.utils import ObliviousDictionary
from leer.core.primitives.block import generate_block_template, build_tx_from_skeleton
from leer.core.parameters.dynamic import next_reward
from leer.core.parameters.constants import coinbase_maturity
from leer.core.parameters.fee_policy import FeePolicyChecker
from leer.core.lubbadubdub.ioput import IOput

class MempoolTx: #Should be renamed to Mempool since it now holds block_template info
  '''
    This manager holds information about known unconfirmed transaction and provides it for generation of next block and relay, also it holds (unsolved) block templates.
    self.transactions contains skeletons of known transactions (before merging)
    self.current_set containt transactions which are 1) downloaded and 2) do not contradict with each other
    self.short_memory_of_mined_transaction contains transactions which were mined in the last few blocks (we include tx to short_memory_of_mined_transaction if all tx.inputs and tx.outputs were in block_tx). It is necessary for safe rollbacks without
    losing transactions.
  '''
  def __init__(self, storage_space, fee_policy_config=None):
    self.transactions = []
    self.built_tx = {}
    self.current_set = []
    self.combined_tx = None
    self.short_memory_of_mined_transaction = {}
    self.storage_space = storage_space
    self.storage_space.register_mempool_tx(self)
    self.block_templates = ObliviousDictionary(sink_delay=6000)
    self.key_manager = None
    self.fee_policy_checker = FeePolicyChecker(fee_policy_config) if fee_policy_config else FeePolicyChecker()

  def update_current_set(self, rtx):
    '''
      For now we have quite a simple and dirty algo:
      1) sort all tx by input_num (bigger first)
      2) iterate through tx and add transactions to current_set if 
         a) it is downloaded
         b) it is valid (otherwise delete from self.transactions)
         c) doesn't contradict with any other tx in the set
    '''
    self.transactions = sorted(self.transactions, key = lambda x: len(x.input_indexes), reverse=True)
    tx_to_remove_list = []
    txos_storage = self.storage_space.txos_storage
    excesses_storage = self.storage_space.excesses_storage
    merged_tx = Transaction(txos_storage=txos_storage, excesses_storage=excesses_storage)
    for tx_skeleton in self.transactions:
      #TODO build_tx_from_skeleton should raise distinctive exceptions
      downloaded = True
      for _i in tx_skeleton.input_indexes:
        if not txos_storage.confirmed.has(_i, rtx=rtx):
          downloaded = False
      for _o in tx_skeleton.output_indexes:
        if not _o in txos_storage.mempool:
          downloaded = False
      if not downloaded:
        continue
      try:
        if tx_skeleton.serialize() in self.built_tx:
          full_tx = self.built_tx[tx_skeleton.serialize()]
        else:
          if tx_skeleton.tx:
            full_tx = tx_skeleton.tx
          else:
            full_tx = build_tx_from_skeleton(tx_skeleton, self.storage_space.txos_storage,  self.storage_space.excesses_storage, self.storage_space.blockchain.current_height(rtx=rtx) +1, rtx=rtx)
            tx_skeleton.tx=full_tx
          self.built_tx[tx_skeleton.serialize()]=full_tx
      except Exception as e:
        tx_to_remove_list.append(tx_skeleton)
        continue
      try:
        if self.fee_policy_checker.check_tx(full_tx):
          merged_tx = merged_tx.merge(full_tx, rtx=rtx)
          self.current_set.append(tx_skeleton)
      except Exception as e:
        pass #it is ok, tx contradicts with other transactions in the pool
    for tx in tx_to_remove_list:
      self.transactions.remove(tx)
      self.built_tx.pop(tx.serialize(), None)
    self.combined_tx = merged_tx

  def update(self, rtx, reason):
    self.update_current_set(rtx=rtx)

  def give_tx(self):
    return self.combined_tx

  def give_tx_skeleton(self):    
    return TransactionSkeleton(tx = self.combined_tx)

  def add_tx(self,tx, rtx):
    if isinstance(tx, Transaction):
      tx_skel = TransactionSkeleton(tx=tx)
      self.built_tx[tx_skel.serialize()]=tx
      self.transactions.append(tx_skel)
    elif isinstance(tx,TransactionSkeleton):
      self.transactions.append(tx)
    else:
      raise
    self.update(rtx=rtx, reason="Tx addition")

  def set_key_manager(self, key_manager): #TODO remove
    self.key_manager = key_manager

  def give_block_template(self, coinbase_address, wtx):
    transaction_fees = self.give_tx().relay_fee if self.give_tx() else 0
    value = next_reward(self.storage_space.blockchain.current_tip(rtx=wtx), self.storage_space.headers_storage, rtx=wtx)+transaction_fees
    coinbase = IOput()
    coinbase.fill(coinbase_address, value, relay_fee=0, coinbase=True, lock_height=self.storage_space.blockchain.current_height(rtx=wtx) + 1 + coinbase_maturity)
    coinbase.generate()
    self.storage_space.txos_storage.mempool[coinbase.serialized_index]=coinbase
    tx=Transaction(txos_storage = self.storage_space.txos_storage, excesses_storage=self.storage_space.excesses_storage)
    tx.add_coinbase(coinbase)
    tx.compose_block_transaction(rtx=wtx)
    block = generate_block_template(tx, self.storage_space, wtx=wtx)
    self.add_block_template(block)
    return block
  
  def add_block_template(self, block):
    self.block_templates[block.header.template] = block

  def get_block_by_header_solution(self, header):
    if not header.template in self.block_templates:
      raise Exception("Unknown template")
    block = self.block_templates[header.template]
    block._header = header
    return block #This block is already ready to be added to blockchain (PoW is not checked, though)
