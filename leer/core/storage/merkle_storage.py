from collections import OrderedDict
import os, lmdb, math


def _(x):
  return (x).to_bytes(5,'big')

class MMR:
  """
    Storage with merkle tree structure above it.

    We add obj and also obj index (sometimes term `hash` is used instead of `index`).
    Tree is built from indexes via summ which should be redefined in subclass.
                     
                       root = i4_1=sum(i3_1,i3_2)
                     /                           \
             i3_1=sum(i2_1,i2_2)             i3_2=i2_3
             /                 \                     |
     i2_1=sum(i1,i2)    i2_2=sum(i3,i4)      i2_3=sum(i5,i6)
       /        \          /        \         /         \
      i1        i2        i3        i4        i5        i6 
      |         |         |         |         |         |         
    obj1      obj2      obj3      obj4      obj5      obj6      

  Boundary case: tree with zero leafs has root equal to `'\\x00'*default_index_size`

  Inner structure contains 4 lmdb databases: leaf_db, node_db, order_db, reverse_order_db.
  order_db: 		sequence_num -> index
  reverse_order_db: 	index -> sequence_num
  leaf_db: 		index -> object
  node_db: 		(level,sequence_num) -> tree_node_index

  3 remove-like operations are supported:
    remove(n)  - removes n elements from the end of the list. Cannot be undone.
                 This operation is used to delete information from orphan blocks.
                 This operation is available for all trees
    clear(index) - delete obj with `index`, however keep its place (any other elements 
                  after this operation occupies the same places). Hash of place become
                  equal None: no matter how summ of indexes is redefined in subclasses
                  `None`+`smth`=`smth`, `None`+`None`=`None`. This operation is used for
                  unspent outputs tree.
    discard(index) - delete obj, but keeps its index. This operation is used for txos tree.

  Special value is leaf db with index `b'state'. It is used to store identifier of current MMR state on disc.
    `set_state` and `get_state` write and read this value
  """
  def __init__(self, name, dir_path, waterline_depth=16, default_index_size=65, discard_only=False, clear_only=False, save_pruned=True):
    self.index={}
    self.dir_path = dir_path
    self.directory = dir_path+"/"+name
    self.default_index_size = default_index_size
    self.discard_only = discard_only
    self.clear_only = clear_only
    self.save_pruned = save_pruned # Do not really delete data from db for debug purposes

    if not os.path.exists(self.directory): 
        os.makedirs(self.directory) #TODO catch
    self.env = lmdb.open(self.directory, max_dbs=10)
    with self.env.begin(write=True) as txn:
      self.leaf_db = self.env.open_db(b'leaf_db', txn=txn)
      self.node_db = self.env.open_db(b'node_db', txn=txn)
      self.order_db = self.env.open_db(b'order_db', txn=txn)
      self.reverse_order_db = self.env.open_db(b'reverse_order_db', txn=txn)
      if self.save_pruned:
        self.pruned_db = self.env.open_db(b'pruned_db', txn=txn)
        self.pruned_ro_db = self.env.open_db(b'pruned_ro_db', txn=txn)

  def _get_node(self, level, sequence_num, tx=None):
    if not tx:
      with self.env.begin(write=False) as tx:
        return self._get_node(level, sequence_num, tx)   
    if level==0:
          return tx.get( _(sequence_num), db=self.order_db)
    else:
        return tx.get(_(level-1)+_(sequence_num), db=self.node_db)

  def get_by_hash(self, _hash, tx=None):
    if not tx:
      with self.env.begin(write=False) as tx:
        return self.get_by_hash(_hash, tx)  
    return tx.get(_hash, db=self.leaf_db)

  def get_pruned_by_hash(self, _hash, tx=None):
    if not self.save_pruned:
      raise
    if not tx:
      with self.env.begin(write=False) as tx:
        return self.get_pruned_by_hash(_hash, tx)  
    return tx.get(_hash, db=self.pruned_db)

  def find_by_hash(self, _hash, tx=None):
    '''
      In contrast with get_by_hash, find_by_hash try to find result both in existing and pruned(if saved) dbs.
    '''
    if not tx:
      with self.env.begin(write=False) as tx:
        return self.find_by_hash(_hash, tx)      
    r1 = tx.get(_hash, db=self.leaf_db) 
    if not r1 and self.save_pruned:
     r1 = tx.get(_hash, db=self.pruned_db)
    return r1

  def _set_node(self, level, sequence_num, value, tx):
    tx.put(_(level-1)+_(sequence_num), value, db=self.node_db)

  def num_of_elements(self, tx=None):
    if tx:
      return tx.stat(db=self.order_db)['entries']
    with self.env.begin(write=False) as tx:
      return tx.stat(db=self.order_db)['entries']   

  def _get_max_level(self, tx=None):
    try:
      return math.ceil(math.log(self.num_of_elements(tx=tx),2))
    except ValueError:
      #if num_of_elements ==0, math.log raise ValueError
      raise ValueError("getting root level of empty tree")

  def _update_path(self, level, sequence_num, tx):
    """
      This function should be called when node on level `level` with sequence_num `sequence_num` changes.
      It updates all nodes above
    """
    if level == self._get_max_level() and sequence_num==0:
      #already at the root, nothing to update
      #TODO while there is no reasons to update_path on empty trees, we should check for error in _get_max_level
      pass
    else:
      neighbour_index = (sequence_num//2)*2 if (sequence_num%2) else (sequence_num//2)*2+1
      neighbour = self._get_node(level, neighbour_index, tx)
      we = self._get_node(level, sequence_num, tx)
      if neighbour and we:
        if sequence_num%2:
          new_value = self.sum(neighbour, we)
        else:
          new_value = self.sum(we, neighbour)
      else:
        new_value = we if we else neighbour# just copy value up
      self._set_node(level+1, sequence_num//2, new_value, tx)
      self._update_path(level+1, sequence_num//2, tx)

  def append(self, obj_index=None, obj=None):
    with self.env.begin(write=True) as txn:
      num = txn.stat(db=self.order_db)['entries']
      #TODO actually we probably may use append=True flag for order_db
      txn.put( _(num), bytes(obj_index), db=self.order_db)
      txn.put( bytes(obj_index), _(num), db=self.reverse_order_db)
      txn.put(bytes(obj_index), bytes(obj), db=self.leaf_db)
    with self.env.begin(write=True) as txn:
      self._update_path(0, num, tx=txn)
    

  def remove(self, num, set_of_indexes=None):
    """
     Remove `num_of_elements` from right end.
     If `set_of_elements` specified check before remove that all elements are in set.
    """
    with self.env.begin(write=True) as txn:
      start_n = self.num_of_elements()-1
      cache = {}
      if set_of_indexes:
        for el_n in range(start_n, start_n-num, -1):
          el=txn.get(_(el_n),db=self.order_db)
          cache[el_n] = el
          if not el in set_of_indexes:
            raise #TODO
      removed_objects = []
      for el_n in range(start_n, start_n-num, -1):
        if not el_n in cache:
          el=txn.get(_(el_n),db=self.order_db)
          cache[el_n] = el
        txn.delete( _(el_n), db=self.order_db)
        txn.delete( cache[el_n], db=self.reverse_order_db)
        removed_objects.append(txn.pop( cache[el_n], db=self.leaf_db))
        
        #TODO we can make this much faster for bulk deletion by not updating
        # each path separately
        self._update_path(0, el_n, tx=txn)
      return removed_objects

  def discard(self, _index):
    '''
      Discard leaf, that means delete obj by index(for saving space), but keeps its index.
      Returns object which can be used to revert discarding.
    '''
    #TODO: check wether both childs are discarded (thus we can discard childs and keep only parent index)
    if self.clear_only:
      raise
    with self.env.begin(write=True) as txn:
      num = int.from_bytes(txn.get( bytes(_index), db=self.reverse_order_db), 'big')
      #txn.put( _(num), b"", db=self.order_db)
      obj = txn.pop( bytes(_index), db=self.leaf_db)
      if self.save_pruned:
        txn.put(_(num), bytes(_index), db=self.pruned_db) 
        txn.put(bytes(_index), obj, db=self.pruned_db)       
    with self.env.begin(write=True) as txn:
      self._update_path(0, num, tx=txn)
    return [num, _index, obj]

  def revert_discarding(self, prune_obj):
    '''
      Revert discrding by object which is returned by discard
    '''
    num, obj_index, obj = prune_obj
    with self.env.begin(write=True) as txn:
      txn.put( _(num), bytes(obj_index), db=self.order_db)
      txn.put( bytes(obj_index), _(num), db=self.reverse_order_db)
      txn.put(bytes(obj_index), bytes(obj), db=self.leaf_db) 
      if self.save_pruned:
        txn.pop(_(num), db=self.pruned_db) 
        txn.pop(bytes(obj_index), db=self.pruned_db)        
    with self.env.begin(write=True) as txn:
      self._update_path(0, num, tx=txn)  

  def clear(self, _index):
    '''
      Clear leaf, that means delete information (index and object), 
      but keep place. Returns prune object by which it can be easily unpruned
    '''
    if self.discard_only:
      raise
    with self.env.begin(write=True) as txn:
      num = int.from_bytes(txn.pop( bytes(_index), db=self.reverse_order_db), 'big')
      txn.put( _(num), b"", db=self.order_db)
      obj = txn.pop( bytes(_index), db=self.leaf_db)
      if self.save_pruned:
        txn.put(_(num), bytes(_index), db=self.pruned_db) 
        txn.put(bytes(_index), obj, db=self.pruned_db) 
        txn.put(bytes(_index), _(num), db=self.pruned_ro_db)           
    with self.env.begin(write=True) as txn:
      self._update_path(0, num, tx=txn)
    return [num, _index, obj]

  def revert_clearing(self, prune_obj):
    '''
      Revert clearing by object which returned by clear
    '''
    num, obj_index, obj = prune_obj
    with self.env.begin(write=True) as txn:
      txn.put( _(num), bytes(obj_index), db=self.order_db)
      txn.put( bytes(obj_index), _(num), db=self.reverse_order_db)
      txn.put(bytes(obj_index), bytes(obj), db=self.leaf_db)  
      if self.save_pruned:
        txn.pop(_(num), db=self.pruned_db) 
        txn.pop(bytes(obj_index), db=self.pruned_db) 
        txn.pop(bytes(obj_index), db=self.pruned_ro_db)   
    with self.env.begin(write=True) as txn:
      self._update_path(0, num, tx=txn) 

  def sum(self, x1, x2):
    """
      Should be redefined in subclasses
    """
    pass


  def get_root(self):
    try:
      return self._get_node(self._get_max_level(), 0)
    except ValueError:
      #empty tree (TODO custom exception)
      return b"\x00"*self.default_index_size

  def set_state(self,state):
    with self.env.begin(write=True) as txn:
      txn.put(b'state', state, db=self.leaf_db)


  def get_state(self):
    with self.env.begin(write=False) as txn:
      return txn.get(b'state', db=self.leaf_db)


