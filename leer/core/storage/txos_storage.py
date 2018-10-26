from leer.core.storage.merkle_storage import MMR
from secp256k1_zkp import PedersenCommitment, PublicKey
from leer.core.storage.default_paths import txo_storage_path
from leer.core.lubbadubdub.ioput import IOput
import os
import hashlib



def _hash(data):
        #TODO move to utils
        m=hashlib.sha256()
        m.update(bytes(data))
        return m.digest()



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
        second_part = _hash(hash1+hash2)
        return first_part+second_part
        

class TXOMMR(MMR):
      def sum(self, x1,x2):
        return _hash(x1+x2)

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

    def __init__(self, path=txo_storage_path):
      self.commitments = CommitmentMMR("commitments", os.path.join(path, "confirmed"), clear_only=False)
      self.txos = TXOMMR("txos", os.path.join(path, "confirmed"), discard_only=True)

    def __getitem__(self, hash_and_pc):
      res = self.txos.get_by_hash(_hash(hash_and_pc))
      if not res:
        raise KeyError(hash_and_pc)
      utxo=IOput()
      utxo.deserialize(res)
      return utxo

    def __setitem__(self, hash_and_pc, utxo):
      #TODO __setitem__ interface should be substituted with append-like interface
      #XXX problem here: commitments indexes should be apc+hash(apc), not hash_and_pc
      #here we should save
      self.txos.append(_hash(hash_and_pc),utxo.serialize())
      self.commitments.append(utxo.commitment_index,b"")

    def append(self, utxo):
      self.txos.append(_hash(utxo.serialized_index), utxo.serialize())
      self.commitments.append(utxo.commitment_index,b"")

    def spend(self, utxo, return_revert_obj=False):
      txos = self.txos.discard(_hash(utxo.serialized_index))
      commitment = self.commitments.clear(utxo.commitment_index)
      if return_revert_obj:
        return (txos, commitment)

    def find(self, hash_and_pc):
      '''
        In contrast with __getitem__ find will try to find even spent
        outputs for other (syncing) nodes.
      '''
      res = self.txos.find_by_hash(_hash(hash_and_pc))
      if not res:
        raise KeyError(hash_and_pc)
      utxo=IOput()
      utxo.deserialize(res)
      return utxo

    def unspend(self, revert_obj):
      (txos, commitment) = revert_obj
      self.txos.revert_discarding(txos)
      self.commitments.revert_clearing(commitment)

    def __contains__(self, serialized_index):
      return bool(self.txos.get_by_hash(_hash(serialized_index)))

    def remove(self,n):
      self.commitments.remove(n)
      ser_removed_outputs = self.txos.remove(n)
      removed_outputs=[]
      for _ser in ser_removed_outputs:
        utxo=IOput()
        utxo.deserialize(_ser)
        removed_outputs.append(utxo)
      return removed_outputs

    def get_commitment_root(self):
      return self.commitments.get_root()

    def get_txo_root(self):
      return self.txos.get_root()

    def get_state(self):
      return self.commitments.get_state()

    def set_state(self, state):
      self.txos.set_state(state)
      self.commitments.set_state(state)

    def find_wo_deser(self, hash_and_pc):
      res = self.txos.find_by_hash(_hash(hash_and_pc))
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


  def __init__(self, storage_space, path):
    if not path in self.__shared_states:
        self.__shared_states[path]={}
    self.__dict__ = self.__shared_states[path]
    self.path = path
    self.confirmed = ConfirmedTXOStorage(self.path)
    self.mempool = self.Interface()
    self.storage_space = storage_space
    self.storage_space.register_txos_storage(self)
      

  def known(self, output_index):
      return (output_index in self.confirmed) or (output_index in self.mempool)

  def confirm(self, output_index):
    utxo = self.mempool.storage.pop(output_index)
    self.confirmed.append(utxo)

  def apply_tx_get_merkles_and_rollback(self, tx):
    rollback_inputs = []
    for _i in tx.inputs:
        rollback_inputs.append(self.confirmed.spend(_i, return_revert_obj=True))
    for _o in tx.outputs:
        self.confirmed.append(_o)
    roots=[self.confirmed.get_commitment_root(), self.confirmed.get_txo_root()]
    for r_i in rollback_inputs:
      self.confirmed.unspend(r_i)
    self.confirmed.remove(len(tx.outputs))
    return roots

  #TODO bad naming. It should be apply block, or block_transaction
  def apply_tx(self, tx, new_state):
    rollback_inputs = []
    for _i in tx.inputs:
        if self.storage_space.utxo_index:
          self.storage_space.utxo_index.remove_utxo(_i)
        rollback_inputs.append(self.confirmed.spend(_i, return_revert_obj=True))
    for _o in tx.outputs:
        if self.storage_space.utxo_index:
          self.storage_space.utxo_index.add_utxo(_o)
        self.confirmed.append(_o)
        self.mempool.remove(_o)
    self.confirmed.set_state(new_state)
    return (rollback_inputs, len(tx.outputs))

  def rollback(self, pruned_inputs, num_of_added_outputs, prev_state):
    for r_i in pruned_inputs:
      if self.storage_space.utxo_index:
        #r_i[0][2] is serialized txo (0 is txo, 2 is serialized object)
        utxo=IOput()
        utxo.deserialize(r_i[0][2])
        self.storage_space.utxo_index.add_utxo(utxo)
      self.confirmed.unspend(r_i)
    outputs_for_mempool = self.confirmed.remove(num_of_added_outputs)
    for _o in outputs_for_mempool:
      self.mempool[_o.serialized_index]=_o
      self.storage_space.utxo_index.remove_utxo(_o)
    self.confirmed.set_state(prev_state)
        

  def find_serialized(self, output_index):
    if output_index in self.mempool:
      return self.mempool[output_index].serialize()
    else:
      return self.confirmed.find_wo_deser(output_index)
    


