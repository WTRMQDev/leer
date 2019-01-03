from leer.core.storage.merkle_storage import MMR
from leer.core.storage.key_value_storage import KeyValueStorage
from secp256k1_zkp import PedersenCommitment, PublicKey
from leer.core.lubbadubdub.ioput import IOput
from leer.core.utils import sha256
import os




class CommitmentMMR(MMR):
      def sum(self, x1,x2):
        # each index is 33 bytes for commitments and 32 for hash
        comm1, hash1 = x1[:33], x1[33:65]
        comm2, hash2 = x2[:33], x2[33:65]
        comm1, comm2 = PedersenCommitment(commitment=comm1, raw=True), PedersenCommitment(commitment=comm2, raw=True)
        #XXX we definetely need sum of pedersen commitments on libsecp256 level.
        pk= PublicKey()
        pk.combine([comm1.to_public_key().public_key, comm2.to_public_key().public_key])
        sm = pk.to_pedersen_commitment()
        first_part = sm.serialize()
        second_part = sha256(hash1+hash2)
        return first_part+second_part

class TXOMMR(MMR):
      def sum(self, x1,x2):
        return sha256(x1+x2)

class ConfirmedTXOStorage:
    '''
      Storage for all TXOs which are already in blocks.
      It is double MMR tree: first for commitments only, second for full txout
      Commitment tree:
        Each commitment leaf obj is `b""` and commitment leaf index is `bytes(serialized_apc)+bytes(hash(serialized_apc))`.
        Summ of two nodes in commitment tree = bytes(serialized_apc1+serialized_apc1)+hash(hash(serialized_apc)+hash(serialized_apc)),
        where commitments are summed as points on curve and summ of hashes is concantenation.

      Txout tree:
        Each txout leaf obj is serialized ioput, leaf index is hash(ioput_index).
        Summ of two nodes is hash of concantenation

    '''

    def __init__(self, path, env, wtx):
      self.commitments = CommitmentMMR("commitments", path, clear_only=False, env=env, wtx=wtx)
      self.txos = TXOMMR("txos", path, discard_only=True, env=env, wtx=wtx)
      self.burden = KeyValueStorage(name="burden", env=env, wtx=wtx)

    def get(self, hash_and_pc, rtx):
      res = self.txos.get_by_hash(sha256(hash_and_pc), rtx=rtx)
      if not res:
        raise KeyError(hash_and_pc)
      utxo=IOput()
      utxo.deserialize_with_context(res)
      utxo.set_verified_and_correct() #Trust saved outputs
      return utxo

    #TODO Full method removement is postponed till comments inside will be resolved
    #def __setitem__(self, hash_and_pc, utxo):
    #  #TODO __setitem__ interface should be substituted with append-like interface
    #  #XXX problem here: commitments indexes should be apc+hash(apc), not hash_and_pc
    #  #here we should save
    #  self.txos.append(_hash(hash_and_pc),utxo.serialize())
    #  self.commitments.append(utxo.commitment_index,b"")

    def append(self, utxo, wtx):
      assert utxo.verify() #Should be fast since cached
      assert utxo.address_excess_num_index
      self.txos.append(wtx=wtx, obj_index=sha256(utxo.serialized_index), obj=utxo.serialize_with_context())
      self.commitments.append_unique(wtx=wtx, obj_index=utxo.commitment_index, obj=b"")

    def spend(self, utxo, wtx, return_revert_obj=False):
      txos = self.txos.discard(sha256(utxo.serialized_index), wtx=wtx)
      commitment = self.commitments.clear(utxo.commitment_index, wtx=wtx)
      if return_revert_obj:
        return (txos, commitment)

    def find(self, hash_and_pc, rtx):
      '''
        In contrast with __getitem__ find will try to find even spent
        outputs for other (syncing) nodes.
      '''
      res = self.txos.find_by_hash(sha256(hash_and_pc), rtx=rtx)
      if not res:
        raise KeyError(hash_and_pc)
      utxo=IOput()
      utxo.deserialize_with_context(res)
      utxo.set_verified_and_correct() #Trust saved outputs
      return utxo

    def unspend(self, revert_obj, wtx):
      (txos, commitment) = revert_obj
      self.txos.revert_discarding(txos, wtx=wtx)
      self.commitments.revert_clearing(commitment, wtx=wtx)

    def has(self, serialized_index, rtx):
      return bool(self.txos.get_by_hash(sha256(serialized_index), rtx=rtx))

    def remove(self,n, wtx):
      self.commitments.remove(n,wtx=wtx)
      ser_removed_outputs = self.txos.remove(n,wtx=wtx)
      removed_outputs=[]
      for _ser in ser_removed_outputs:
        utxo=IOput()
        utxo.deserialize_with_context(_ser)
        removed_outputs.append(utxo)
      return removed_outputs

    def get_commitment_root(self, rtx):
      return self.commitments.get_root(rtx=rtx)

    def get_txo_root(self, rtx):
      return self.txos.get_root(rtx=rtx)

    def get_state(self, rtx):
      return self.commitments.get_state(rtx=rtx)

    def set_state(self, state, wtx):
      self.txos.set_state(state, wtx=wtx)
      self.commitments.set_state(state, wtx=wtx)

    def find_wo_deser(self, hash_and_pc, rtx):
      res = self.txos.find_by_hash(sha256(hash_and_pc), rtx=rtx)
      if not res:
        raise KeyError(hash_and_pc)
      return res


class TXOsStorage:

  class Interface:

    def __init__(self):
      self.storage = {}

    def __getitem__(self, hash_and_pc):
      if not hash_and_pc in self.storage:
        raise KeyError(hash_and_pc)
      return self.storage[hash_and_pc]

    def __setitem__(self, hash_and_pc, utxo):
      #TODO __setitem__ interface should be substituted with append-like interface
      #here we should save
      self.storage[hash_and_pc]=utxo

    def remove(self, utxo):
      self.remove_by_index(utxo.serialized_index)

    def remove_by_index(self, _index):
      self.storage.pop(_index)

    def __contains__(self, utxo):
      return utxo in self.storage  

    def flush(self):
      self.storage = {}


  __shared_states = {}


  def __init__(self, storage_space, wtx):
    path = storage_space.path
    if not path in self.__shared_states:
        self.__shared_states[path]={}
    self.__dict__ = self.__shared_states[path]
    self.path = path
    self.confirmed = ConfirmedTXOStorage(self.path, env=storage_space.env, wtx=wtx)
    self.mempool = self.Interface()
    self.storage_space = storage_space
    self.storage_space.register_txos_storage(self)
      

  def known(self, output_index, rtx):
      return self.confirmed.has(output_index, rtx=rtx) or (output_index in self.mempool)

  def confirm(self, output_index, wtx):
    utxo = self.mempool.storage.pop(output_index)
    self.confirmed.append(utxo, wtx=wtx)

  def apply_tx_get_merkles_and_rollback(self, tx, wtx):
    rollback_inputs = []
    for _i in tx.inputs:
        rollback_inputs.append(self.confirmed.spend(_i, wtx=wtx, return_revert_obj=True))
    for _o in tx.outputs:
        self.confirmed.append(_o, wtx=wtx)
    roots=[self.confirmed.get_commitment_root(rtx=wtx), self.confirmed.get_txo_root(rtx=wtx)]
    for r_i in rollback_inputs:
      self.confirmed.unspend(r_i, wtx=wtx)
    self.confirmed.remove(len(tx.outputs), wtx=wtx)
    return roots

  #TODO bad naming. It should be apply block, or block_transaction
  def apply_tx(self, tx, new_state, wtx):
    rollback_inputs = []
    for _i in tx.inputs:
        if self.storage_space.utxo_index:
          self.storage_space.utxo_index.remove_utxo(_i, wtx=wtx)
        rollback_inputs.append(self.confirmed.spend(_i, return_revert_obj=True, wtx=wtx))
    for _o in tx.outputs:
        if self.storage_space.utxo_index:
          self.storage_space.utxo_index.add_utxo(_o, wtx=wtx)
        self.confirmed.append(_o, wtx=wtx)
        self.mempool.remove(_o)
    self.confirmed.set_state(new_state, wtx=wtx)
    return (rollback_inputs, len(tx.outputs))

  def rollback(self, pruned_inputs, num_of_added_outputs, prev_state, wtx):
    for r_i in pruned_inputs:
      if self.storage_space.utxo_index:
        #r_i[0][2] is serialized txo (0 is txo, 2 is serialized object)
        utxo=IOput()
        utxo.deserialize(r_i[0][2])
        self.storage_space.utxo_index.add_utxo(utxo, wtx=wtx)
      self.confirmed.unspend(r_i, wtx=wtx)
    outputs_for_mempool = self.confirmed.remove(num_of_added_outputs, wtx=wtx)
    for _o in outputs_for_mempool:
      self.mempool[_o.serialized_index]=_o
      if self.storage_space.utxo_index:
        self.storage_space.utxo_index.remove_utxo(_o, wtx=wtx)
    self.confirmed.set_state(prev_state, wtx=wtx)
        

  def find_serialized(self, output_index, rtx):
    if output_index in self.mempool:
      return self.mempool[output_index].serialize()
    else:
      found = self.confirmed.find_wo_deser(output_index, rtx=rtx)
      if found:
        found=found[:-5] #We store ioputs with context, which we cut before relaying
      return found

  def find(self, output_index, rtx):
    if output_index in self.mempool:
      return self.mempool[output_index]
    else:
      return self.confirmed.find(output_index, rtx=rtx)


    


