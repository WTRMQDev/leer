from leer.core.primitives.header import Header, PoPoW, VoteData, ContextHeader
from leer.core.storage.headers_storage import HeadersStorage
import time
from leer.core.parameters.dynamic import next_reward, next_target, output_creation_fee
from leer.core.parameters.constants import initial_target, initial_reward
from leer.core.lubbadubdub.utils import compare_supply_and_merkle_roots


class HeadersManager:
  def __init__(self, storage_space, do_not_check_pow=False):
    self.storage_space = storage_space
    self.storage_space.register_headers_manager(self)
    self.loose_ends = {}
    self.do_not_check_pow = do_not_check_pow #For testing purposes

  def set_genesis(self, genesis_header, wtx):
    self.genesis = genesis_header
    self.best_tip = (self.genesis.hash, self.genesis.height)
    if not self.storage_space.headers_storage.has(self.genesis.hash, rtx=wtx):
      self.add_header(self.genesis, wtx=wtx)


  def add_header(self, header, wtx):
    #try:
      assert header.check_self_consistency(), "Block header %s is invalid by itself"%(header.hash)
      assert (not self.storage_space.headers_storage.has(header.hash, rtx=wtx)), "Duplication header %s"%(header.hash)

      context_header = ContextHeader(header)
      if self.storage_space.headers_storage.has(header.prev, rtx=wtx):
        prev =  self.storage_space.headers_storage.get(header.prev, rtx=wtx)
        context_header.connected_to_genesis = prev.connected_to_genesis
        context_header.invalid = prev.invalid
        prev.descendants.add(header.hash)
        self.storage_space.headers_storage.update(header.prev, prev, wtx=wtx)
      else:
        context_header.connected_to_genesis = False
        if not header == self.genesis:
          self.loose_ends[header.prev] = header.hash
        else:
          context_header.connected_to_genesis = True

      if header.hash in self.loose_ends:
        context_header.descendants.add(self.loose_ends.pop(header.hash))
        

      self.storage_space.headers_storage.put(header.hash, context_header, wtx=wtx)

      if context_header.connected_to_genesis:
        self.mark_subchain_connected_to_genesis(header.hash, wtx=wtx)
      #if context_header.invalid:
      #  self.mark_subchain_invalid(header.hash)

      #context_header = self.storage_space.headers_storage.get(header.hash, rtx=wtx) # prev checks could change params
      #if context_header.connected_to_genesis and not context_header.invalid:
        # NOTE if new header has the same height as current tip, best_tip will not be changed
        # (header.height==self.best_tip[1] and header.hash > self.best_tip[0])
      #  if header.height>self.best_tip[1]:
      #    self.best_tip = (context_header.hash, context_header.height)
    #except Exception as e:
    #  raise e

  def mark_subchain_invalid(self, _hash, wtx, reason=None):
    if not reason:
      # reason of invalidity is by default inherited from prev block
      this_header = self.storage_space.headers_storage.get(_hash, rtx=wtx)
      prev_header = self.storage_space.headers_storage.get(this_header.prev, rtx=wtx)
      reason=prev_header.reason      
    to_be_marked = [_hash]
    # Recursion, while beatiful, can easily reach max depth here
    need_new_best_tip = False
    while len(to_be_marked):
      header_hash = to_be_marked.pop(0)
      header = self.storage_space.headers_storage.get(header_hash, rtx=wtx)
      header.invalid = True
      if reason:
        header.reason = reason
      self.storage_space.headers_storage.put(header_hash, header, wtx=wtx)
      to_be_marked += list(header.descendants)
      if header.hash == self.best_tip[0]:
        #subchain which was intended to be best occurs to be invalid
        need_new_best_tip = True
    if need_new_best_tip:
      self.find_best_tip(rtx=wtx)

  def mark_subchain_connected_to_genesis(self, _hash, wtx):
    to_be_marked = [_hash]
    # Recursion, while beatiful, can easily reach max depth here
    while len(to_be_marked):
      header_hash = to_be_marked.pop(0)
      header = self.storage_space.headers_storage.get(header_hash,rtx=wtx)
      header.connected_to_genesis = True
      to_be_marked += list(header.descendants)
      if _hash ==self.genesis.hash:
        header.coins_to_be_mint = header.supply
      else:
        try:
          header.coins_to_be_mint = self.storage_space.headers_storage.get(header.prev,rtx=wtx).coins_to_be_mint + \
                                  next_reward(header.prev, self.storage_space.headers_storage, rtx=wtx) +\
                                  output_creation_fee
        except KeyError:
          ''' If something is wrong with block.height, for instance it is set to 2000, while it is 20 in sequence
              next_reward will raise.
          '''
          header.coins_to_be_mint = 0
        header.total_difficulty = self.storage_space.headers_storage.get(header.prev, rtx=wtx).total_difficulty + header.difficulty
        # we should save here, since context_validation checks coins_to_be_mint too
        self.storage_space.headers_storage.put(header_hash, header, wtx=wtx)
        if self.storage_space.headers_storage.get(header.prev, rtx=wtx).invalid:
          header.invalid = True
          header.reason = self.storage_space.headers_storage.get(header.prev, rtx=wtx).reason
        else:
          try:
            self.context_validation(_hash, rtx=wtx)
          except Exception as e:
            header.invalid = True
            header.reason = str(e)
      self.storage_space.headers_storage.put(header_hash, header, wtx=wtx)
      # NOTE if new header has the same height as current best tip, best_tip will not be changed
      # (header.height==self.best_tip[1] and header.hash > self.best_tip[0])
      if header.height > self.best_tip[1]:
        if not header.invalid:
          self.best_tip = (header.hash, header.height)

  def is_known(self):
    pass

  def find_best_tip(self, rtx): 
    # This function should be called only if subchain which was
    # intended to be best, occurs to be invalid. For all other cases
    # get_best_tip should be called
    
    # TODO consider refactoring. Finding best tip should be implemented on 
    # database level, smthing like SQL 
    #`select * from headers where invalid==None and connected_to_genesis=True ORDER BY height desc limit 1`
    height = self.best_tip[1]+1
    self.best_tip = None
    while not self.best_tip:
      height -=1
      if height<0:
        raise
      try:
        candidates = self.storage_space.headers_storage.get_headers_hashes_at_height(height, rtx=rtx)
      except Exception as e: #specific exception
        continue 
      valid_candidates = []
      for candidate_hash in candidates:
        candidate = self.storage_space.headers_storage.get(candidate_hash, rtx=rtx)
        if not candidate.invalid:
          if candidate.connected_to_genesis: #Always true, consider to remove
            valid_candidates.append(candidate_hash)
      if len(valid_candidates):
        best_candidate_hash = max(valid_candidates)
        best_candidate = self.storage_space.headers_storage.get(best_candidate_hash, rtx=rtx)
        self.best_tip = (best_candidate.hash, best_candidate.height)

  def get_best_tip(self):
    return self.best_tip

  @property
  def best_header_height(self):
    return self.best_tip[1]

  @property
  def best_header_hash(self):
    return self.best_tip[0]

  def best_header(self, rtx):
    return self.storage_space.headers_storage.get(self.best_tip[0], rtx=rtx)

  def best_header_total_difficulty(self, rtx):
    return self.best_header(rtx=rtx).total_difficulty

  def find_bifurcation_point(self, hash1, hash2, rtx):
    # Both headers should be connected genesis otherwise search may not finish
    # successfuly: exception will be raised. Note its ok for headers to be invalid
    header1 = self.storage_space.headers_storage.get(hash1, rtx=rtx)
    header2 = self.storage_space.headers_storage.get(hash2, rtx=rtx)
    while not header1.height==header2.height:
      # put header with higher height first
      (header1,header2) = (header1, header2) if header1.height>header2.height else (header2, header1)
      header1 = self.storage_space.headers_storage.get(header1.prev, rtx=rtx)
    if header1.hash == header2.hash:
      return header1.hash
    #Headers are in different forks
    while not header1.hash==header2.hash:
      header1 = self.storage_space.headers_storage.get(header1.prev, rtx=rtx)
      header2 = self.storage_space.headers_storage.get(header2.prev, rtx=rtx)
    return header1.hash

  def all_descendants_with_height(self, from_hash, height, rtx):
    current_height = self.storage_space.headers_storage.get(from_hash, rtx=rtx).height
    current_round = set([from_hash])
    while current_height<height:
      next_round=set()
      for i in current_round:
        _h = self.storage_space.headers_storage.get(i, rtx=rtx)
        if not _h.invalid:
          next_round= next_round.union(_h.descendants)
      current_height+=1
      current_round=next_round
    current_round = [ _h for _h in current_round if not self.storage_space.headers_storage.get(_h, rtx=rtx).invalid ]
    return list(current_round)

  def get_subchain(self, from_hash, to_hash, rtx):
    '''
    Get_subchain function goes down from to_hash and stops when finds from_hash.
    In case from_hash and to_hash are in different forks, it will be found
    only when descent hits genesis and throws exception `no prev`.
    '''
    subchain=[]
    while not to_hash==from_hash:
      subchain.append(to_hash)
      to_hash=self.storage_space.headers_storage.get(to_hash, rtx=rtx).prev
    return subchain[::-1]

  def next_actions(self, at_hash, rtx, n=100, looking_back_horizont=64):
    # Bad design, should be moved to blockchain?
    '''
    This function is used by BlockchainManager to decide what to do next.
    It gets current blockchain tip hash and returns possible paths to "better state"
    (state with higher height) sorted by "quality".
    
    Paths represented by lists of actions, each action is a tuple of `action_name` and `hash`.
    Actions:
     Action_name params
     ROLLBACK	 hash
     ADDBLOCK    hash

    Default behavior is returning path to best_headers_tip as best path, and all other paths 
    to height==current_height+1 (which forked less than looking_back_horizont blocks ago)
    in random order.
    
    Probably we should return paths sorted by max known height and also supply more than one
    step per path. However, this will make internal logic too cumbersome, while at worst scenario
    of long forks and unreacheable main branch the only negative effect is slow synchronisation.
    
    '''
    if not self.storage_space.headers_storage.has(at_hash, rtx=rtx):
      if at_hash == b"\x00"*32:#pre-genesis
        return [[("ADDBLOCK", self.genesis.hash)]]
      else:
        raise Exception("Unknown start point")
    actions=[]
    best_tip_actions = []    
    if at_hash == self.best_tip[0]:
      return [best_tip_actions]

    main_brunch_hashes=[]
    #path to best tip
    bifurcation_point = self.find_bifurcation_point(at_hash, self.best_tip[0], rtx=rtx)
    if not bifurcation_point==at_hash:
      best_tip_actions.append(("ROLLBACK", bifurcation_point))
    for _hash in self.get_subchain(bifurcation_point, self.best_tip[0], rtx=rtx)[:n]:
      best_tip_actions.append(("ADDBLOCK", _hash))
      main_brunch_hashes.append(_hash)

    actions.append(best_tip_actions)

    current_height = self.storage_space.headers_storage.get(at_hash, rtx=rtx).height
    hash_on_horizont = at_hash
    for i in range(looking_back_horizont):
      prev = self.storage_space.headers_storage.get(hash_on_horizont, rtx=rtx).prev
      if prev==b"\00"*32:#before genesis
        break
      else:
        hash_on_horizont=prev
      
    candidates = self.all_descendants_with_height(hash_on_horizont, current_height+1, rtx=rtx)
    for candidate in candidates:
      if candidate in main_brunch_hashes:
        continue # Do not repeat main brunch
      path_actions = []
      bifurcation_point = self.find_bifurcation_point(at_hash, candidate, rtx=rtx)
      if not bifurcation_point==at_hash:
        path_actions.append(("ROLLBACK", bifurcation_point))
      for _hash in self.get_subchain(bifurcation_point, candidate, rtx=rtx)[:n]:
        path_actions.append(("ADDBLOCK", _hash))
      actions.append(path_actions)
    return actions
      

  def context_validation(self, _hash, rtx):
    '''
      v 0. Check that context is ready
      v 1. check height sequence
      2. (obsolete) check version
      v 3. check supply sequence
      v 4. partially check merkles: we cannot fully validate merkles without tx, however
           we can check that summ of money supply and excesses is equal to commitment sum
           (TODO more explanations should be added here) (TODO consider moving to header self validation)
      v 5. check popow sequence
      v 6. check timestamp
      v 7. check target
      v 8. check PoW is less than target
    '''
    header = self.storage_space.headers_storage.get(_hash, rtx=rtx)
    #0
    if not header.connected_to_genesis:
      return
      # TODO context_validation should raise its own exception that will be
      # caught in context_validation_of_subchain (Now we can't throw exception for
      # incorect checks like not connected chains, it will be assigned to block)
    if self.storage_space.headers_storage.has(header.prev, rtx=rtx): #otherwise it is genesis
      prev = self.storage_space.headers_storage.get(header.prev, rtx=rtx)
      #1
      assert prev.height+1==header.height, "Block height is out of sequence"
      #3
      assert (header.supply<=header.coins_to_be_mint), "Supply is wrong: header.supply %d, header.coins_to_be_mint %d"%(header.supply, header.coins_to_be_mint)
      #5
      assert prev.next_popow() == header.popow, "PoPoW sequence is wrong"
      #6
      assert header.timestamp>prev.timestamp, "Timestamp sequence is wrong"
      #7
      assert next_target(header.prev, self.storage_space.headers_storage, rtx=rtx)==header.target, "Wrong target"
    else:
      #1
      assert header.height == 0, "Block height is out of sequence(genesis)"
      #3
      assert initial_reward==header.supply
      #5
      assert header.popow == PoPoW([]), "Block height is out of sequence(genesis)"
      #7
      assert initial_target==header.target, "Wrong target"

    #4
    assert compare_supply_and_merkle_roots(header.supply, header.merkles[0], header.merkles[2], header.full_offset)
    #8
    if(not self.do_not_check_pow):
      assert header.integer_hash<header.target, "PoW less than target"

  def context_validation_of_subchain(self, from_hash, wtx):
    to_be_validated = [from_hash]
    while len(to_be_validated):
      header_hash = to_be_validated.pop(0)
      check_descendants=True
      try:
        self.context_validation(header_hash, rtx=wtx)
      except Exception as e:
        self.mark_subchain_invalid(header_hash, reason=str(e), rtx=wtx)
        check_descendants=False
      if check_descendants:
        to_be_validated += list(self.storage_space.headers_storage.get(header_hash, rtx=wtx).descendants)


  def find_ancestor_with_height(self, header_hash, height, rtx):
    # Previously we used recursion here, however we found in the wild 
    # (testnet2) that we can hit recursion limit: if PoW is constantly less
    # than 2**252 our fast PoPoW navigation doesn't work and instead we searchin
    # block after block. Thousand of such 'low PoW blocks' and we hit limit.
    header = self.storage_space.headers_storage.get(header_hash, rtx=rtx)
    confirmed_search_point = header
    while True:
      for pointer in confirmed_search_point.popow.pointers[:-1]:
        next_search_point = self.storage_space.headers_storage.get(pointer, rtx=rtx)
        if next_search_point.height<height:
          break
        else:
          confirmed_search_point = next_search_point
      if confirmed_search_point.height<height:
        raise Exception("Asking for ancestor with higher height")
      if confirmed_search_point.height==height:
          return confirmed_search_point.hash
      if confirmed_search_point.height==height+1:
          return confirmed_search_point.prev

