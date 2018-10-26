class StorageSpace:
  '''
    Storage space is set of objects representing blockchain.
    Two different storage spaces, for instance testnet and mainnet should not
    share any objects.
    In the future it will be literally combination of all storages in one physical storage,
    thus truly atomic updates will be possible
  '''
  def __init__(self):
    pass

  def register_txos_storage(self, txos):
    self.txos_storage = txos

  def register_excesses_storage(self, excesses):
    self.excesses_storage = excesses

  def register_headers_storage(self, headers):
    self.headers_storage = headers

  def register_headers_manager(self, headers_manager):
    self.headers_manager = headers_manager

  def register_blocks_storage(self, blocks):
    self.blocks_storage = blocks

  def register_blockchain(self, blockchain):
    self.blockchain = blockchain

  def register_mempool_tx(self, mempool_tx):
    self.mempool_tx = mempool_tx

  def register_utxo_index(self, utxo_index):
    self.utxo_index = utxo_index

  def get_block_template(self):
    '''
      For now blocks are space dependent
    '''
    pass

