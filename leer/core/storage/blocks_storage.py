from leer.core.storage.txos_storage import TXOsStorage
from leer.core.primitives.block import Block, ContextBlock
import shutil, os, time, lmdb, math

class BlocksStorage:
  __shared_states = {}
  def __init__(self, storage_space, wtx):
    path = storage_space.path
    if not path in self.__shared_states:
      self.__shared_states[path]={}
    self.__dict__ = self.__shared_states[path]

    self.storage = BlocksDiscStorage(path, env=storage_space.env, wtx=wtx)
    self.storage_space = storage_space
    self.storage_space.register_blocks_storage(self)
    self.download_queue = []
    
  def get(self, _hash, rtx):
    serialized_context_block = self.storage.get_by_hash(_hash, rtx=rtx)
    if not serialized_context_block:
      raise KeyError(_hash)
    block=Block(storage_space=self.storage_space)
    cblock = ContextBlock(block=block)
    cblock.deserialize_raw(serialized_context_block)
    return cblock

  def put(self, _hash, block, wtx):
    self.storage.put(_hash, block.serialize_with_context(), wtx=wtx)

  def has(self, _hash, rtx):
    return self.storage.has(_hash, rtx=rtx)  

  def is_block_downloaded(self, _hash, rtx, auto_download=True):
    asked = False
    result = True
    block = self.get(_hash, rtx=rtx)
    for output in block.transaction_skeleton.output_indexes:
      if not self.storage_space.txos_storage.known(output, rtx=rtx):
        result = False
        if auto_download:
          self._ask_for_txout(output)
          asked = True
    if asked:
      self._ask_for_txouts()#flushing requests
    return result

  def get_rollback_object(self, _hash, rtx):
    serialized_rollback = self.storage.get_rollback_object(_hash, rtx=rtx)
    rb=RollBack()
    rb.deserialize_raw(serialized_rollback)
    return rb

  def pop_rollback_object(self, _hash, wtx):
    serialized_rollback = self.storage.pop_rollback_object(_hash, wtx=wtx)
    rb=RollBack()
    rb.deserialize_raw(serialized_rollback)
    return rb

  def put_rollback_object(self, _hash, rollback, wtx):
    self.storage.put_rollback_object(_hash, rollback.serialize(), wtx=wtx)



  def _ask_for_txout(self, txout):
    if not txout in self.download_queue:
      self.download_queue.append(txout)

  def _ask_for_txouts(self):
    self.ask_for_txouts_hook(self.download_queue)
    self.download_queue = []

  def forget_block(self, _hash, wtx):
    self.storage.delete_block_by_hash(_hash, wtx=wtx)



class RollBack:
  def __init__(self):
    self.pruned_inputs = [] #revert objects
    self.num_of_added_outputs = None
    self.num_of_added_excesses = None
    self.prev_state = None
    self.updated_excesses = []
    self.burdens = []

  def serialize_bytes(self, _bytes):
    return len(_bytes).to_bytes(2,"big")+_bytes

  def deserialize_bytes_raw(self, serialized):
    _slen, serialized = serialized[:2], serialized[2:]
    _len = int.from_bytes(_slen, "big")
    _bytes, serialized = serialized[:_len], serialized[_len:]
    return _bytes, serialized

  def serialize(self):
    # each pruned input is (TXOS[num, _index, obj], Commitment[num, _index, obj])
    # num is serialized 5bytes integer, other members have arbitrary size
    serialized_pruned_inputs=b""
    serialized_pruned_inputs+=len(self.pruned_inputs).to_bytes(2,"big")
    for _t, _c in self.pruned_inputs:
      for _i in [_t,_c]:
        num, _index, obj = _i
        serialized_pruned_inputs += num.to_bytes(5,"big") + self.serialize_bytes(_index) + self.serialize_bytes(obj)

    serialized_excess_updates=b""
    serialized_excess_updates+=len(self.updated_excesses).to_bytes(2,"big")
    for update in self.updated_excesses:
      num, _index, obj = update
      serialized_excess_updates += num + self.serialize_bytes(_index) + self.serialize_bytes(obj)

    serialized_nums = self.num_of_added_outputs.to_bytes(2,"big") + self.num_of_added_excesses.to_bytes(2,"big")
    serialized_burdens_len = len(self.burdens).to_bytes(2,"big")
    serialized_burdens = serialized_burdens_len + b"".join([i[0] for i in self.burdens])
    version=b"\x01"
    serialized_state_id = self.serialize_bytes(self.prev_state)
    summary_len = len(serialized_pruned_inputs)+len(serialized_nums) + len(serialized_burdens)+len(version)+len(serialized_state_id) + len(serialized_excess_updates)
    serialized = summary_len.to_bytes(4,"big") + \
                 version + \
                 serialized_pruned_inputs + \
                 serialized_nums + \
                 serialized_excess_updates + \
                 serialized_burdens + \
                 serialized_state_id
    return serialized

  def deserialize_raw(self, serialized):
    _slen, serialized = serialized[:4], serialized[4:]
    _len = int.from_bytes(_slen, "big")
    data, residue = serialized[:_len], serialized[_len:]
    version, data = data[:1], data[1:]
    if not version==b"\x01":
      raise
    _s_pruned_inputs_num, data = data[:2], data[2:]
    pruned_inputs_num = int.from_bytes(_s_pruned_inputs_num, "big")
    for i in range(pruned_inputs_num):
      _snum, data = data[:5], data[5:]
      _num = int.from_bytes(_snum, "big")
      _index, data = self.deserialize_bytes_raw(data)
      _obj, data = self.deserialize_bytes_raw(data)
      _txout = [_num,_index,_obj]
      _snum, data = data[:5], data[5:]
      _num = int.from_bytes(_snum, "big")
      _index, data = self.deserialize_bytes_raw(data)
      _obj, data = self.deserialize_bytes_raw(data)
      _comm = [_num,_index,_obj]
      self.pruned_inputs.append([_txout, _comm])
    _no, _ne, data = data[:2], data[2:4], data[4:]
    self.num_of_added_outputs = int.from_bytes(_no,"big")
    self.num_of_added_excesses = int.from_bytes(_ne, "big")
    _s_updates_num, data = data[:2], data[2:]
    updates_num = int.from_bytes(_s_updates_num, "big")
    for i in range(updates_num):
      _snum, data = data[:5], data[5:]
      _index, data = self.deserialize_bytes_raw(data)
      _obj, data = self.deserialize_bytes_raw(data)
      self.updated_excesses.append(_snum, _index, _obj)
    _s_burdens_num, data = data[:2], data[2:]
    burdens_num = int.from_bytes(_s_burdens_num, "big")
    for i in range(burdens_num):
      next_burden, data= data[:65], data[65:]
      self.burdens.append((next_burden, None))
    self.prev_state, data = self.deserialize_bytes_raw(data)
    return residue


class BlocksDiscStorage:
  def __init__(self, dir_path, env, wtx):
    self.dir_path = dir_path

    self.env = env
    self.main_db = self.env.open_db(b'blocks_main_db', txn=wtx, dupsort=False) # block_hash -> serialized_contextblock
    self.revert_db = self.env.open_db(b'blocks_revert_db', txn=wtx, dupsort=False) # block_hash -> object_for_reverting

  def put(self, _hash, serialized_block, wtx):
    p1=wtx.put( bytes(_hash), bytes(serialized_block), db=self.main_db, dupdata=False, overwrite=True)

  def update(self, _hash, serialized_block, wtx):
    wtx.put(bytes(_hash), bytes(serialized_block), db=self.main_db, dupdata=False, overwrite=True)

  def get_by_hash(self, _hash, rtx):
    return rtx.get(bytes(_hash), db=self.main_db)

  def get_rollback_object(self, _hash, rtx):
    return rtx.get(bytes(_hash), db=self.revert_db)

  def pop_rollback_object(self, _hash, wtx):
    return wtx.pop(bytes(_hash), db=self.revert_db)

  def put_rollback_object(self, _hash, serialized_rollback_object, wtx):
    return wtx.put(bytes(_hash), bytes(serialized_rollback_object), db=self.revert_db)

  def has(self, _hash, rtx):
    return bool(self.get_by_hash(_hash, rtx=rtx))

  def delete_block_by_hash(self, _hash, wtx):
    wtx.delete( bytes(_hash), db=self.main_db)
    
  

