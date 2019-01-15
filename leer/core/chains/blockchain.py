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
  def __init__(self, storage_space, notify_wallet=None):
    self.storage_space = storage_space
    self.awaited_blocks = {} # requested but not downloaded blocks
    self.storage_space.register_blockchain(self)
    self.download_queue = [] #Note: it's different from awaited blocks: download queue is queue of blocks still to be requested
    self.notify_wallet = notify_wallet

  def add_block(self, block, wtx, no_update=False):
    cb = ContextBlock(block=block)
    #TODO
    #if not block.hash in  self.awaited_blocks:
    #  raise Exception("Already have block")
    if self.storage_space.blocks_storage.has(block.hash, rtx=wtx):
      raise DOSException("Already have block")

    self.storage_space.blocks_storage.put(block.hash, cb, wtx=wtx)
    try:
      self.awaited_blocks.pop(block.hash)
    except:
      pass

    if not self.storage_space.blocks_storage.is_block_downloaded(block.hash, rtx=wtx, auto_download=True):
      pass
    else:
      try:
        assert block.non_context_verify(rtx=wtx)
      except Exception:
        self.storage_space.headers_manager.mark_subchain_invalid(block.hash, wtx=wtx, reason = "Block %s(h:%d) failed non-context validation"%(block.hash, block.header.height))
        return
      if not no_update: #During first syncing we want to get many blocks at once, so do not update after each
        self.update(wtx=wtx, reason="new block (verified)")
    
  def _add_block_to_chain(self, block_hash, wtx):
    '''
      To add block we need to apply tx both to txos storage and excesses.
      After that we need to set new state.
      Also we need to save info for rollback.
    '''
    block = self.storage_space.blocks_storage.get(block_hash, rtx=wtx)
    block.non_context_verify(rtx=wtx) #build tx from skeleton
    if not self.context_validation(block, wtx=wtx):
      ch = self.storage_space.headers_manager.mark_subchain_invalid(block.hash, wtx=wtx, reason = "Block %s(h:%d) failed context validation"%(block.hash, block.header.height))
      return self.update(wtx=wtx, reason="Detected corrupted block")    
    rb = RollBack()
    rb.prev_state = self.current_tip(rtx=wtx)
    # Note excesses_storage.apply_tx modidies transaction, in particular adds
    # context-dependent address_excess_num_index to outputs. Thus it should be applied before txos_storage.apply_tx
    excesses_num, rollback_updates = self.storage_space.excesses_storage.apply_tx(tx=block.tx, new_state=block_hash, wtx=wtx)  
    rollback_inputs, output_num = self.storage_space.txos_storage.apply_tx(tx=block.tx, new_state=block_hash, wtx=wtx)

    '''all_evaluations_are_good = True
    updated_excesses_are_burden_free = True
    burdens = []
    #Additional excesses can not create burdens
    for excess in block.tx.updated_excesses.values():
      if  self.current_height(rtx=wtx)>0:
        prev_block_props = {'height': self.current_height(rtx=wtx), 
                         'timestamp': self.storage_space.headers_storage.get(self.current_tip(rtx=wtx), rtx=wtx).timestamp}
      else:
        prev_block_props = {'height':0, 'timestamp':0}
      burden_list = []
      excess_lookup_partial = partial(excess_lookup, rtx=wtx, tx=block.tx, excesses_storage = self.storage_space.excesses_storage)
      output_lookup_partial = partial(output_lookup, rtx=wtx, tx=block.tx, txos_storage = self.storage_space.txos_storage)
      result = execute(script = excess.message,
                       prev_block_props = prev_block_props,
                       excess_lookup = excess_lookup_partial,
                       output_lookup = output_lookup_partial,
                       burden = burden_list)
      if not result:
        all_evaluations_are_good = False
        break
      if not len(burden_list)==0:
        updated_excesses_are_burden_free = False
        break
    if not (all_evaluations_are_good and updated_excesses_are_burden_free):
      self.storage_space.headers_manager.mark_subchain_invalid(block.hash, wtx=wtx, reason = "Block %s(h:%d) failed context validation: bad script"%(block.hash, block.header.height))
      return self.update(wtx=wtx, reason="Detected corrupted block")        

    burdens_authorized = True
    #Additionally check that all burdens are authorized  
    for excess in block.tx.additional_excesses:
      if  self.current_height(rtx=wtx)>0:
        prev_block_props = {'height': self.current_height(rtx=wtx), 
                         'timestamp': self.storage_space.headers_storage.get(self.current_tip(rtx=wtx), rtx=wtx).timestamp}
      else:
        prev_block_props = {'height':0, 'timestamp':0}
      burden_list = []
      excess_lookup_partial = partial(excess_lookup, rtx=wtx, tx=block.tx, excesses_storage = self.storage_space.excesses_storage)
      output_lookup_partial = partial(output_lookup, rtx=wtx, tx=block.tx, txos_storage = self.storage_space.txos_storage)
      result = execute(script = excess.message,
                       prev_block_props = prev_block_props,
                       excess_lookup = excess_lookup_partial,
                       output_lookup = output_lookup_partial,
                       burden = burden_list)
      if not result:
        all_evaluations_are_good = False
        break
      for commitment,_pubkey in burden_list:
        commitment_pc = commitment.to_pedersen_commitment()
        ser = commitment_pc.serialize()
        pubkey = _pubkey.to_pubkey()
        output = None
        for o in block.tx.outputs:
          if ser == o.serialized_apc:
            output = o
            break
        if not output:
          burdens_authorized = False
          break
        if (not output.authorized_burden) or (not output.authorized_burden==excess.burden_hash):
          burdens_authorized = False
          break
        burdens.append( (output.serialized_index,pubkey) )
      if not burdens_authorized:
        break
    if not (all_evaluations_are_good and burdens_authorized):
      self.storage_space.headers_manager.mark_subchain_invalid(block.hash, wtx=wtx, reason = "Block %s(h:%d) failed context validation: bad burden"%(block.hash, block.header.height))
      return self.update(wtx=wtx, reason="Detected corrupted block")        
    '''
    #Write to db
    burden_for_rollback = []
    for burden in block.tx.burdens:
      if not self.storage_space.txos_storage.confirmed.burden.get(burden[0], rtx=wtx):
        self.storage_space.txos_storage.confirmed.burden.put(burden[0], burden[1], wtx=wtx)
        burden_for_rollback.append((burden[0], burden[1]))
    # Rollback creation
    rb.pruned_inputs=rollback_inputs
    rb.updated_excesses = rollback_updates
    rb.num_of_added_outputs = output_num
    rb.num_of_added_excesses = excesses_num
    rb.burdens = burden_for_rollback
    self.storage_space.blocks_storage.put_rollback_object(block_hash, rb, wtx=wtx)
    self.storage_space.mempool_tx.update(rtx=wtx, reason="new block")
    if self.notify_wallet:
      self.notify_wallet("apply", block.tx, block.header.height)
    

  def _rollback(self, wtx):
    rb = self.storage_space.blocks_storage.pop_rollback_object(self.current_tip(rtx=wtx), wtx=wtx)
    h = self.current_height(rtx=wtx)
    self.storage_space.txos_storage.rollback(pruned_inputs=rb.pruned_inputs, num_of_added_outputs=rb.num_of_added_outputs, prev_state=rb.prev_state, wtx=wtx)
    self.storage_space.excesses_storage.rollback(num_of_added_excesses=rb.num_of_added_excesses, prev_state=rb.prev_state, rollback_updates=rb.updated_excesses, wtx=wtx)
    for burden in rb.burdens:
      self.storage_space.txos_storage.confirmed.burden.remove(burden[0], wtx=wtx)
    if self.notify_wallet:
      self.notify_wallet("rollback", rb, h)

  def clean_old_block_requests(self):
    to_delete = []
    for bh in self.awaited_blocks:
      if self.awaited_blocks[bh]+3600 < time():
         to_delete.append(bh)
    for bh in to_delete:
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
     

  def context_validation(self, block, wtx):
    assert block.header.prev == self.current_tip(rtx=wtx)
    block.tx.verify(block_height=self.current_height(rtx=wtx), rtx=wtx, skip_non_context=True)
    excesses_root = self.storage_space.excesses_storage.apply_tx_get_merkles_and_rollback(block.tx, wtx=wtx)
    commitment_root, txos_root = self.storage_space.txos_storage.apply_tx_get_merkles_and_rollback(block.tx, wtx=wtx)
    if not [commitment_root, txos_root, excesses_root]==block.header.merkles:
      return False
    '''excesses = block.tx.additional_excesses + list(block.tx.updated_excesses.values())
    excesses_indexes = [e.index for e in excesses]
    for i in block.tx.inputs:
      if self.storage_space.txos_storage.confirmed.burden.has(i.serialized_index, rtx=wtx):
        required_commitment = txos.storage.confirmed.burden.get(i.serialized_index, rtx=wtx)
        required_index =
        if (not required_index in excesses_indexes) and (not self.storage_space.excesses_storage.has_index(required_index)):
          return False
    for excess in excesses:
      if  self.current_height(rtx=wtx)>0:
        prev_block_props = {'height': self.current_height(rtx=wtx), 
                         'timestamp': self.storage_space.headers_storage.get(self.current_tip(rtx=wtx), rtx=wtx).timestamp}
      else:
        prev_block_props = {'height':0, 'timestamp':0}
      burden_list = []
      excess_lookup_partial = partial(excess_lookup, rtx=wtx, tx=block.tx, excesses_storage = self.storage_space.excesses_storage)
      output_lookup_partial = partial(output_lookup, rtx=wtx, tx=block.tx, txos_storage = self.storage_space.txos_storage)
      result = execute(script = excess.message,
                       prev_block_props = prev_block_props,
                       excess_lookup = excess_lookup_partial,
                       output_lookup = output_lookup_partial,
                       burden = burden_list)
      if not result:
        return False
    '''
    if block.header.height>0:
      subsidy = next_reward(block.header.prev, self.storage_space.headers_storage, rtx=wtx)
      if not self.storage_space.headers_storage.get(block.header.prev, rtx=wtx).supply + \
           subsidy - \
           block.transaction_skeleton.calc_new_outputs_fee(is_block_transaction=True) == block.header.supply:
        return False
      if not block.tx.coinbase.value == subsidy + block.tx.relay_fee: 
        # Note we already check coinbase in non_context_check, but using tx_skeleton info
        # Since information in tx_skeleton may be forged, this check is not futile
        return False
      
    return True

  def current_tip(self, rtx):
    ts,es = self.storage_space.txos_storage.confirmed.get_state(rtx=rtx), self.storage_space.excesses_storage.get_state(rtx=rtx)
    es=None if es == b"" else es #TODO
    assert ts==es
    if ts==None:
      return b"\x00"*32
    return ts

  def current_height(self,rtx):
    current_tip = self.current_tip(rtx=rtx)
    if current_tip==b"\x00"*32:
      current_height = -1
    else:
      current_height = self.storage_space.blocks_storage.get(current_tip,rtx=rtx).header.height
    return current_height

  def update(self, wtx, reason=None):
    current_tip = self.current_tip(rtx=wtx)
    max_steps = 2048
    actions = self.storage_space.headers_manager.next_actions(current_tip, rtx=wtx, n = max_steps)
    # before doing anything we should check that we have enough info (downloaded blocks)
    # to move to a better state (state with higher height)
    current_height = self.current_height(rtx=wtx)
    good_path=None
    for path in actions:
      if good_path:
        break
      for step in path:
        if step[0]=="ADDBLOCK":
          if not  self.storage_space.blocks_storage.has(step[1], rtx=wtx):
            #Try to download as much blocks as possible and break
            for _step in path:
              if _step[0]=="ADDBLOCK" and (not self.storage_space.blocks_storage.has(_step[1], rtx=wtx)):
                self._lazy_ask_for_block(_step[1])
            self._download_queued_blocks()
            break
          if (not self.storage_space.blocks_storage.is_block_downloaded(step[1], rtx=wtx)):
            break
          else:
            if self.storage_space.blocks_storage.get(step[1], rtx=wtx).header.height>current_height or \
               self.storage_space.blocks_storage.get(step[1], rtx=wtx).header.height-current_height>=max_steps:
              good_path=path
              break
    if not good_path:
      return
    progress = self.process_path(good_path, wtx=wtx)
    if progress:# and (not good_path==actions[0]):
      # workaround for situations when branch with best known header is not available:
      # in this case next_actions will return only one step for alternative branch.
      # details in HeadersManager.next_actions
      self.update(wtx=wtx, reason="recursive check")


  def process_path(self, path, wtx):
    progress = False
    for step in path:
      action, block_hash = step
      if action=="ROLLBACK":
        while self.current_tip(rtx=wtx)!=block_hash:
          self._rollback(wtx=wtx)
          #TODO Add some checks here to prevent rolling back to genesis in case of any mistakes
      if action=="ADDBLOCK":
        if (not self.storage_space.blocks_storage.has(block_hash, rtx=wtx)) or (not self.storage_space.blocks_storage.is_block_downloaded(block_hash, rtx=wtx)):
          break
          # We decide that path is good if we have enough downloaded blocks to get to current_height+1. Still, the path
          # may contain more steps and for some of those steps we may not have downloaded blocks. So stop now.
        try:
          self._add_block_to_chain(step[1], wtx=wtx)
          progress = True #at least one block was added
        except AssertionError:
          break
    return progress

  def _forget_top(self, wtx):
    """
      This function is used for tests only: currently we can generate blocks only on top of known ones.
      Thus, to collide two forks (one of which is previously unknown to blockchain) we need first to generate forks
      and then to force blockchain to forget it.
      This function deletes data not only from blockchain but also from blocks storage and txos_storage.
      Note, after forgeting top block, previous block became blockchain tip. If there is a known longer branch, 
      blockchain will not be switched to it.
    """
    ct =self.current_tip(rtx=wtx)
    block = self.storage_space.blocks_storage.get(ct, rtx=wtx)
    self._rollback(wtx=wtx)
    self.storage_space.blocks_storage.forget_block(ct, wtx=wtx)
    for _o in block.transaction_skeleton.output_indexes:
      self.storage_space.txos_storage.mempool.remove_by_index(_o)
      


  def is_block_in_main_chain(self, block_hash, rtx):
    header = self.storage_space.headers_storage.get(block_hash,rtx=rtx)
    return header_hash == self.storage_space.heders_manager.find_ancestor_with_height(self.current_tip, header.height, rtx=rtx) 
    

