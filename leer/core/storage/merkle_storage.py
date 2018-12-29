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
    clear(index) - delete obj with `index`, however keep its place (any other elements occupies
                  after this operation the same places). Hash of place becomes
                  equal None: no matter how summ of indexes is redefined in subclasses
                  `None`+`smth`=`smth`, `None`+`None`=`None`. This operation is used for
                  unspent outputs tree.
    discard(index) - delete obj, but keeps its index. This operation is used for txos tree.

  Special value is leaf db with index `b'state'. It is used to store identifier of current MMR state on disc.
    `set_state` and `get_state` write and read this value
  """
  def __init__(self, name, dir_path, env, wtx, waterline_depth=16, default_index_size=65, discard_only=False, clear_only=False, save_pruned=True):
    self.index={}
    self.dir_path = dir_path
    self.name = bytes(name.encode("utf-8"))
    self.default_index_size = default_index_size
    self.discard_only = discard_only
    self.clear_only = clear_only
    self.save_pruned = save_pruned # Do not really delete data from db for debug purposes


    self.env = env
    self.leaf_db = self.env.open_db(self.name+b'leaf_db', txn=wtx)
    self.node_db = self.env.open_db(self.name+b'node_db', txn=wtx)
    self.order_db = self.env.open_db(self.name+b'order_db', txn=wtx)
    self.reverse_order_db = self.env.open_db(self.name+b'reverse_order_db', txn=wtx, dupsort=True)
    if self.save_pruned:
        self.pruned_db = self.env.open_db(self.name+b'pruned_db', txn=wtx)
        self.pruned_ro_db = self.env.open_db(self.name+b'pruned_ro_db', txn=wtx, dupsort=True)

  def _get_node(self, level, sequence_num, rtx):
    if level==0:
          return rtx.get( _(sequence_num), db=self.order_db)
    else:
        return rtx.get(_(level-1)+_(sequence_num), db=self.node_db)

  def get_by_hash(self, _hash, rtx):
    return rtx.get(_hash, db=self.leaf_db)

  def fuzzy_search(self, _hash, rtx):
    cursor = rtx.cursor(db=self.leaf_db)
    is_set = cursor.set_range(_hash)
    if not is_set:
      return None
    return cursor.item()

  def get_pruned_by_hash(self, _hash, rtx):
    if not self.save_pruned:
      raise
    return rtx.get(_hash, db=self.pruned_db)

  def find_by_hash(self, _hash, rtx):
    '''
      In contrast with get_by_hash, find_by_hash tries to find result both in existing and pruned(if saved) dbs.
    '''
    r1 = rtx.get(_hash, db=self.leaf_db) 
    if not r1 and self.save_pruned:
     r1 = rtx.get(_hash, db=self.pruned_db)
    return r1

  def _set_node(self, level, sequence_num, value, wtx):
    wtx.put(_(level-1)+_(sequence_num), value, db=self.node_db)

  def _del_node(self, level, sequence_num, wtx):
    wtx.delete(_(level-1)+_(sequence_num), db=self.node_db)

  def num_of_elements(self, rtx):
    return rtx.stat(db=self.order_db)['entries']

  def _get_max_level(self, rtx):
    try:
      return math.ceil(math.log(self.num_of_elements(rtx=rtx),2))
    except ValueError:
      #if num_of_elements ==0, math.log raise ValueError
      raise ValueError("getting root level of empty tree")

  def _update_path(self, level, sequence_num, wtx):
    """
      This function should be called when node on level `level` with sequence_num `sequence_num` changes.
      It updates all nodes above
    """
    try:
      mxlvl = self._get_max_level(rtx=wtx)
    except ValueError:
      return
    if level == mxlvl and sequence_num==0:
      #already at the root, nothing to update
      pass
    else:
      neighbour_index = (sequence_num//2)*2 if (sequence_num%2) else (sequence_num//2)*2+1
      neighbour = self._get_node(level, neighbour_index, rtx=wtx)
      we = self._get_node(level, sequence_num, rtx=wtx)
      if neighbour and we:
        if sequence_num%2:
          new_value = self.sum(neighbour, we)
        else:
          new_value = self.sum(we, neighbour)
      else:
        new_value = we if we else neighbour# just copy value up
      self._set_node(level+1, sequence_num//2, new_value, wtx=wtx)
      self._update_path(level+1, sequence_num//2, wtx=wtx)

  def append(self, wtx, obj_index=None, obj=None):
      num = wtx.stat(db=self.order_db)['entries']
      #TODO actually we probably may use append=True flag for order_db
      wtx.put( _(num), bytes(obj_index), db=self.order_db)
      wtx.put( bytes(obj_index), _(num), db=self.reverse_order_db)
      wtx.put(bytes(obj_index), bytes(obj), db=self.leaf_db)
      self._update_path(0, num, wtx=wtx)
      return _(num)

  def has_index(self, rtx, obj_index):
      index = rtx.get( bytes(obj_index), db=self.reverse_order_db)
      return bool(index)

  def append_unique(self, wtx, obj_index=None, obj=None):
      index = wtx.get( bytes(obj_index), db=self.reverse_order_db)
      if index:
        raise KeyError("Not unique")
      self.append(wtx=wtx, obj_index=obj_index, obj=obj)

  def update_index_by_num(self, wtx, num_index_ser, obj_index, obj):
      old_index = wtx.get( num_index_ser, db=self.order_db)
      wtx.put( num_index_ser, bytes(obj_index), db=self.order_db)
      wtx.delete( bytes(old_index), num_index_ser, db=self.reverse_order_db)
      wtx.put( bytes(obj_index), num_index_ser, db=self.reverse_order_db)
      old_obj = wtx.pop(bytes(old_index), db=self.leaf_db)
      wtx.put(bytes(obj_index), bytes(obj) , db=self.leaf_db)
      self._update_path(0, int.from_bytes(num_index_ser,"big"), wtx=wtx)
      return old_index, old_obj

  def update_index_by_num_unique(self, wtx, num_index_ser, obj_index, obj):
      nindex = wtx.get( bytes(obj_index), db=self.reverse_order_db)
      if nindex:
        raise KeyError("Not unique")
      return self.update_index_by_num(wtx, num_index_ser, obj_index, obj)

      
    

  def remove(self, num, wtx, set_of_indexes=None):
    """
     Remove `num_of_elements` from right end.
     If `set_of_elements` specified check before remove that all elements are in set.
    """
    start_n = self.num_of_elements(rtx=wtx)-1
    mxlvl = self._get_max_level(rtx=wtx) 
    cache = {}
    if set_of_indexes:
        for el_n in range(start_n, start_n-num, -1):
          el=wtx.get(_(el_n),db=self.order_db)
          cache[el_n] = el
          if not el in set_of_indexes:
            raise #TODO
    removed_objects = []
    el_n = start_n
    for el_n in range(start_n, start_n-num, -1):
        if not el_n in cache:
          el=wtx.get(_(el_n),db=self.order_db)
          cache[el_n] = el
        wtx.delete( _(el_n), db=self.order_db)
        wtx.delete( cache[el_n], _(el_n), db=self.reverse_order_db)
        removed_objects.append(wtx.pop( cache[el_n], db=self.leaf_db))
        #TODO we can make this much faster for bulk deletion by not updating
        # each path separately
        for l in range(1,mxlvl+1):
          self._del_node(l, el_n//(2**l), wtx=wtx) 
    self._update_path(0, el_n-1, wtx=wtx)
    return removed_objects

  def discard(self, _index, wtx):
    '''
      Discard leaf, that means delete obj by index(for saving space), but keep its index.
      Returns object which can be used to revert discarding.
    '''
    #TODO: check wether both children are discarded (thus we can discard childs and keep only parent index)
    if self.clear_only:
      raise
    num = int.from_bytes(wtx.get( bytes(_index), db=self.reverse_order_db), 'big')
    #wtx.put( _(num), b"", db=self.order_db)
    obj = wtx.pop( bytes(_index), db=self.leaf_db)
    if self.save_pruned:
        wtx.put(_(num), bytes(_index), db=self.pruned_db) 
        wtx.put(bytes(_index), obj, db=self.pruned_db)       
    self._update_path(0, num, wtx=wtx)
    return [num, _index, obj]

  def revert_discarding(self, prune_obj, wtx):
    '''
      Revert discarding by object which is returned by discard
    '''
    num, obj_index, obj = prune_obj
    wtx.put( _(num), bytes(obj_index), db=self.order_db)
    wtx.put( bytes(obj_index), _(num), db=self.reverse_order_db)
    wtx.put(bytes(obj_index), bytes(obj), db=self.leaf_db) 
    if self.save_pruned:
        wtx.pop(_(num), db=self.pruned_db) 
        wtx.pop(bytes(obj_index), db=self.pruned_db)        
    self._update_path(0, num, wtx=wtx)  

  def clear(self, _index, wtx):
    '''
      Clear leaf, that means delete information (index and object), 
      but keep place. Returns prune object by which it can be easily unpruned
    '''
    if self.discard_only:
      raise
    num = int.from_bytes(wtx.pop( bytes(_index), db=self.reverse_order_db), 'big')
    wtx.put( _(num), b"", db=self.order_db)
    obj = wtx.pop( bytes(_index), db=self.leaf_db)
    if self.save_pruned:
        wtx.put(_(num), bytes(_index), db=self.pruned_db) 
        wtx.put(bytes(_index), obj, db=self.pruned_db) 
        wtx.put(bytes(_index), _(num), db=self.pruned_ro_db)           
    self._update_path(0, num, wtx=wtx)
    return [num, _index, obj]

  def revert_clearing(self, prune_obj, wtx):
    '''
      revert_clearing takes object which clear function returns and reverts clear operation.
    '''
    num, obj_index, obj = prune_obj
    wtx.put( _(num), bytes(obj_index), db=self.order_db)
    wtx.put( bytes(obj_index), _(num), db=self.reverse_order_db)
    wtx.put(bytes(obj_index), bytes(obj), db=self.leaf_db)  
    if self.save_pruned:
        wtx.pop(_(num), db=self.pruned_db) 
        wtx.pop(bytes(obj_index), db=self.pruned_db) 
        wtx.pop(bytes(obj_index), db=self.pruned_ro_db)   
    self._update_path(0, num, wtx=wtx) 

  def sum(self, x1, x2):
    """
      Should be redefined in subclasses
    """
    pass


  def get_root(self, rtx):
    try:
      return self._get_node(self._get_max_level(rtx=rtx), 0, rtx=rtx)
    except ValueError:
      #empty tree (TODO custom exception)
      return b"\x00"*self.default_index_size

  def set_state(self, state, wtx):
    wtx.put(b'state', state, db=self.leaf_db)


  def get_state(self, rtx):
    return rtx.get(b'state', db=self.leaf_db)


