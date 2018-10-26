from leer.core.primitives.transaction_sceleton import TransactionSceleton
from leer.core.lubbadubdub.transaction import Transaction
from leer.core.utils import ObliviousDictionary
from leer.core.primitives.block import generate_block_template, build_tx_from_sceleton
from leer.core.parameters.dynamic import next_reward
from leer.core.parameters.constants import coinbase_maturity
from leer.core.lubbadubdub.ioput import IOput

class MempoolTx: #Should be renamed to Mempool since it now holds block_template info
  '''
    This manager holds information about known unconfirmed transaction and provide it for generation of next block and relay, also it holds (unsolved) block templates.
    self.transactions contain known transactions sceletons (before merging)
    self.current_set containt transactions which are 1) downloaded and 2) not contradict with each other
    self.short_memory_of_mined_transaction contains transaction which were mined in a last few blocks (we include tx to short_memory_of_mined_transaction if all tx.inputs and tx.outputs were in block_tx). It is necessery for safe rollbacks without
    loosing transactions.
  '''
  def __init__(self, storage_space):
    self.transactions = []
    self.built_tx = {}
    self.current_set = []
    self.combined_tx = None
    self.short_memory_of_mined_transaction = {}
    self.storage_space = storage_space
    self.storage_space.register_mempool_tx(self)
    self.block_templates = ObliviousDictionary(sink_delay=6000)
    self.key_manager = None

  def update_current_set(self):
    '''
      For now we have quite simple and dirty algo:
      1) sort all tx by input_num (bigger first)
      2) iterate through tx and add transactions to current_set if 
         a) it is downloaded
         b) it is valid (otherwise delete from self.transactions)
         c) itsn't contradict with any other
    '''
    self.transactions = sorted(self.transactions, key = lambda x: len(x.input_indexes), reverse=True)
    tx_to_remove_list = []
    txos_storage = self.storage_space.txos_storage
    merged_tx = Transaction(txos_storage=txos_storage)
    for tx_sceleton in self.transactions:
      #TODO build_tx_from_sceleton should raise distinctive exceptions
      downloaded = True
      for _i in tx_sceleton.input_indexes:
        if not _i in txos_storage.confirmed:
          downloaded = False
      for _o in tx_sceleton.output_indexes:
        if not _o in txos_storage.mempool:
          downloaded = False
      if not downloaded:
        continue
      try:
        if tx_sceleton.serialize() in self.built_tx:
          full_tx = self.built_tx[tx_sceleton.serialize()]
        else:
          if tx_sceleton.tx:
            full_tx = tx_sceleton.tx
          else:
            full_tx = build_tx_from_sceleton(tx_sceleton, self.storage_space.txos_storage, self.storage_space.blockchain.current_height +1)
            tx_sceleton.tx=full_tx
          self.built_tx[tx_sceleton.serialize()]=full_tx
      except Exception as e:
        tx_to_remove_list.append(tx_sceleton)
        continue
      try:
        merged_tx = merged_tx.merge(full_tx)
        self.current_set.append(tx_sceleton)
      except:
        pass #it is ok
    for tx in tx_to_remove_list:
      self.transactions.remove(tx)
      self.built_tx.pop(tx.serialize(), None)
    self.combined_tx = merged_tx

  def update(self, reason):
    self.update_current_set()

  def give_tx(self):
    return self.combined_tx

  def give_tx_sceleton(self):    
    return TransactionSceleton(tx = self.combined_tx)

  def add_tx(self,tx):
    if isinstance(tx, Transaction):
      tx_scel = TransactionSceleton(tx=tx)
      self.built_tx[tx_scel.serialize()]=tx
      self.transactions.append(tx_scel)
    elif isinstance(tx,TransactionSceleton):
      self.transactions.append(tx)
    else:
      raise
    self.update(reason="Tx addition")

  def set_key_manager(self, key_manager):
    self.key_manager = key_manager

  def give_block_template(self):
    if not self.key_manager:
      raise Exception("Key manager is not set")
    value = next_reward(self.storage_space.blockchain.current_tip, self.storage_space.headers_storage)
    coinbase = IOput()
    coinbase.fill(self.key_manager.new_address(), value, relay_fee=0, coinbase=True, lock_height=self.storage_space.blockchain.current_height + 1 + coinbase_maturity)
    coinbase.generate()
    self.storage_space.txos_storage.mempool[coinbase.serialized_index]=coinbase
    tx=Transaction(txos_storage = self.storage_space.txos_storage, key_manager= self.key_manager)
    tx.add_coinbase(coinbase)
    tx.compose_block_transaction()
    block = generate_block_template(tx, self.storage_space)
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
