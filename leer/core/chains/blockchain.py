from time import time
from leer.core.primitives.block import Block, ContextBlock
from leer.core.primitives.header import Header
from leer.core.storage.blocks_storage import BlocksStorage, RollBack
from leer.core.storage.txos_storage import TXOsStorage
from leer.core.storage.headers_storage import HeadersStorage
from leer.core.storage.excesses_storage import ExcessesStorage
from leer.core.parameters.dynamic import next_reward
from leer.core.utils import DOSException

class Blockchain:
  def __init__(self, storage_space):
    self.storage_space = storage_space
    self.awaited_blocks = {} # requested but not downloaded blocks
    self.storage_space.register_blockchain(self)
    self.download_queue = [] #Note: it's different from awaited blocks: download queue is queue of blocks still to be requested

  def add_block(self, block, no_update=False):
    cb = ContextBlock(block=block)
    #TODO
    #if not block.hash in  self.awaited_blocks:
    #  raise Exception("Already have block")
    if block.hash in self.storage_space.blocks_storage:
      raise DOSException("Already have block")

    self.storage_space.blocks_storage[block.hash] = cb
    try:
      self.awaited_blocks.pop(block.hash)
    except:
      pass

    if not self.storage_space.blocks_storage.is_block_downloaded(block.hash, auto_download=True):
      pass
    else:
      try:
        assert block.non_context_verify()
      except Exception:
        self.storage_space.headers_manager.mark_subchain_invalid(block.hash, reason = "Block %s(h:%d) failed non-context validation"%(block.hash, block.header.height))
        return
      if not no_update: #During first syncing we want to get many blocks at once, so do not update after each
        self.update(reason="new block (verified)")
    
  def _add_block_to_chain(self, block_hash):
    '''
      To add block we need to apply tx both to txos storage and excesses.
      After that we need to set new state.
      Also we saving info for rollback.
      TODO: We definetely should use transactional writing here to avoid db inconsistency.
    '''
    #TODO transactional writing
    block = self.storage_space.blocks_storage[block_hash]
    block.non_context_verify() #build tx from sceleton
    if not self.context_validation(block):
      ch = self.storage_space.headers_manager.mark_subchain_invalid(block.hash, reason = "Block %s(h:%d) failed context validation"%(block.hash, block.header.height))
      return self.update(reason="Detected corrupted block")    
    rb = RollBack()
    rb.prev_state = self.current_tip
    rollback_inputs, output_num = self.storage_space.txos_storage.apply_tx(tx=block.tx, new_state=block_hash)
    excesses_num = self.storage_space.excesses_storage.apply_tx(tx=block.tx, new_state=block_hash)
    rb.pruned_inputs=rollback_inputs
    rb.num_of_added_outputs = output_num
    rb.num_of_added_excesses = excesses_num
    self.storage_space.blocks_storage.put_rollback_object(block_hash, rb)
    self.storage_space.mempool_tx.update(reason="new block")
    

  def _rollback(self):
    rb = self.storage_space.blocks_storage.pop_rollback_object(self.current_tip)
    self.storage_space.txos_storage.rollback(pruned_inputs=rb.pruned_inputs, num_of_added_outputs=rb.num_of_added_outputs, prev_state=rb.prev_state)
    self.storage_space.excesses_storage.rollback(num_of_added_excesses=rb.num_of_added_excesses, prev_state=rb.prev_state)

  def clean_old_block_requests(self):
    for bh in self.awaited_blocks:
      if self.awaited_blocks[bh]+3600 < time():
         self.awaited_blocks.pop(bh)

  def _lazy_ask_for_block(self, block_hash):
    self.download_queue.append(block_hash)

  def _download_queued_blocks(self):
    self.clean_old_block_requests()
    if len(self.awaited_blocks)>256:
      return
    to_download = []
    for bh in self.download_queue:
      if (not bh in to_download) and (not bh in self.awaited_blocks):
        self.awaited_blocks[bh]=time()
        to_download.append(bh)
    self.ask_for_blocks_hook(to_download)
    self.download_queue=[]

  def _ask_for_blocks(self, block_hash):
    self.clean_old_block_requests()
    if len(self.awaited_blocks)>256 or (block_hash in self.awaited_blocks):
      return
    self.awaited_blocks[block_hash]=time()
    self.ask_for_blocks_hook(block_hash) #It should be set by user
     

  def context_validation(self, block):
    assert block.header.prev == self.current_tip
    block.tx.verify(block_height=self.current_height, skip_non_context=True)
    commitment_root, txos_root = self.storage_space.txos_storage.apply_tx_get_merkles_and_rollback(block.tx)
    excesses_root = self.storage_space.excesses_storage.apply_tx_get_merkles_and_rollback(block.tx)
    if not [commitment_root, txos_root, excesses_root]==block.header.merkles:
      return False
    if block.header.height>0:
      if not self.storage_space.headers_storage[block.header.prev].supply + \
           next_reward(block.header.prev, self.storage_space.headers_storage) - \
           block.transaction_sceleton.calc_new_outputs_fee(is_block_transaction=True) == block.header.supply:
        return False
    return True

  @property
  def current_tip(self):
    ts,es = self.storage_space.txos_storage.confirmed.get_state(), self.storage_space.excesses_storage.get_state()
    assert ts==es
    if ts==None:
      return b"\x00"*32
    return ts

  @property
  def current_height(self):
    current_tip = self.current_tip
    if current_tip==b"\x00"*32:
      current_height = -1
    else:
      current_height = self.storage_space.blocks_storage[current_tip].header.height
    return current_height

  def update(self, reason=None):
    current_tip = self.current_tip
    actions = self.storage_space.headers_manager.next_actions(current_tip)
    # before doing anything we should check that we have enough info (downloaded blocks)
    # to move to better state (state with higher height)
    current_height = self.current_height
    good_path=None
    for path in actions:
      if good_path:
        break
      for step in path:
        if step[0]=="ADDBLOCK":
          if (not step[1] in self.storage_space.blocks_storage):
            #Try to download as much blocks as possible and break
            for _step in path:
              if _step[0]=="ADDBLOCK" and (not _step[1] in self.storage_space.blocks_storage):
                self._lazy_ask_for_block(_step[1])
            self._download_queued_blocks()
            break
          if (not self.storage_space.blocks_storage.is_block_downloaded(step[1])):
            break
          else:
            if self.storage_space.blocks_storage[step[1]].header.height>current_height:
              good_path=path
              break
    if not good_path:
      return
    progress = self.process_path(good_path)
    if progress:# and (not good_path==actions[0]):
      # workaround for situations when best known by headers branch is not available:
      # in this case next_actions will return only one step for alternative branch.
      # details in HeadersManager.next_actions
      self.update(reason="recursive check")


  def process_path(self, path):
    progress = False
    for step in path:
      action, block_hash = step
      if action=="ROLLBACK":
        while self.current_tip!=block_hash:
          self._rollback()
          #TODO Add some checks here to prevent rolling back to genesis in case of any mistakes
      if action=="ADDBLOCK":
        if (not block_hash in self.storage_space.blocks_storage) or (not self.storage_space.blocks_storage.is_block_downloaded(block_hash)):
          break
          # We decide that path is good if we have enough downloaded blocks to get to current_height+1. Still path
          # may contains more steps and for some of those steps we may not have downloaded blocks. So stop now.
        try:
          self._add_block_to_chain(step[1])
          progress = True #at least one block was added
        except AssertionError:
          break
    return progress

  def _forget_top(self):
    """
      This function is used for tests only: currently we can generate blocks only on top of known ones.
      Thus, to collide two forks (one of which is previously unknown to blockchain) we need first generate forks
      and then force blockchain to forget it.
      This function not only delete data from blockchain but also from blocks storage and txos_storage.
      Note, after forgeting top blockchain doesn't automatically update: if there is longer branch blockchain will not be switched to it.
    """
    ct =self.current_tip
    block = self.storage_space.blocks_storage[ct]
    self._rollback()
    self.storage_space.blocks_storage.forget_block(ct)
    for _o in block.transaction_sceleton.output_indexes:
      self.storage_space.txos_storage.mempool.remove_by_index(_o)
      


  def is_block_in_main_chain(self, block_hash):
    header = self.storage_space.headers_storage[block_hash]
    return header_hash == self.storage_space.heders_manager.find_ancestor_with_height(self.current_tip, header.height) 
    

