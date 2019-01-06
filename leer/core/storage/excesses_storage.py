from leer.core.storage.merkle_storage import MMR
from secp256k1_zkp import PedersenCommitment, PublicKey
from leer.core.lubbadubdub.address import Excess
import hashlib
import os
from leer.core.utils import sha256

class ExcessMMR(MMR):
      def sum(self, x1,x2):
        # each index is 33 bytes for commitments and 32 for hash
        pubkey1, hash1 = x1[:33], x1[33:65]
        pubkey2, hash2 = x2[:33], x2[33:65]
        pubkey1, pubkey2 = PublicKey(pubkey=pubkey1, raw=True), PublicKey(pubkey=pubkey2, raw=True)
        # consider pubkey1+pubkey2
        pk= PublicKey()
        pk.combine([pubkey1.public_key, pubkey2.public_key])
        first_part = pk.serialize()
        second_part = sha256(hash1+hash2)
        return first_part+second_part




class ExcessesStorage():
    '''
      Excesses tree:
        Each excess leaf obj is serialized excess, leaf index is excess_index.
    '''
    __shared_states = {}

    def __init__(self, storage_space, wtx):
      path = storage_space.path
      if not path in self.__shared_states:
        self.__shared_states[path]={}
      self.__dict__ = self.__shared_states[path]
      self.excesses = ExcessMMR("excesses", path, wtx=wtx, env=storage_space.env, clear_only=False)
      self.storage_space = storage_space
      storage_space.register_excesses_storage(self)
      
    def append_utxo(self, utxo, wtx):
      return self.excesses.append(wtx=wtx, obj_index=utxo.address.index, obj=b"")

    def append_additional_excess(self, excess, wtx):
      self.excesses.append_unique(wtx=wtx, obj_index=excess.index, obj=excess.serialize())

    def update_spent_address_with_excess(self, num_index, new_excess, wtx):
       new_excess_index = new_excess.index
       serialized_excess = new_excess.serialize()
       return self.update_spent_address_with_serialized_excess(num_index, new_excess_index, serialized_excess, wtx)

    def update_spent_address_with_serialized_excess(self, num_index_ser, new_excess_index, serialized_excess, wtx):
       old_excess_index, old_excess = self.excesses.update_index_by_num_unique(wtx, num_index_ser, new_excess_index, serialized_excess)
       if not new_excess_index[:33]==old_excess_index[:33]: #First 33 bytes - serialized pubkey
         raise Exception("Wrong excess update") #Never should get here, since tx is already checked, but this check is cheap
       return num_index_ser, old_excess_index, old_excess
      

    #def __contains__(self, serialized_index, ):
    #  return bool(self.excesses.get_by_hash(serialized_index))

    def has_index(self, serialized_index, rtx):
      return bool(self.excesses.get_by_hash(serialized_index, rtx=rtx))

    def get_by_index(self, serialized_index, rtx):
      serialized_excess = self.excesses.get_by_hash(serialized_index, rtx=rtx)
      if not serialized_excess:
        return None
      e = Excess()
      e.deserialize_raw(serialized_excess)
      return e

    def remove(self, n, wtx):
      self.excesses.remove(n, wtx=wtx)

    def get_root(self, rtx):
      return self.excesses.get_root(rtx=rtx)

    def apply_tx_get_merkles_and_rollback(self, tx, wtx):
      initial_state = self.get_state(rtx=wtx)
      initial_root = self.get_root(rtx=wtx)
      num_of_added_excesses, rollback_updates = self.apply_tx(tx, b"Excess validation temporal state", wtx)
      root = self.get_root(rtx=wtx)
      self.rollback(num_of_added_excesses, initial_state, rollback_updates, wtx)
      assert initial_root==self.get_root(rtx=wtx), "Database was corrupted during excesses apply_tx_get_merkles_and_rollback"
      return root

    #TODO bad naming. It should be apply block, or block_transaction
    def apply_tx(self, tx, new_state, wtx):
      for _o in tx.outputs:
          num = self.append_utxo(_o, wtx=wtx)
          _o.address_excess_num_index = num #storing num_index of stored address excess
      for _e in tx.additional_excesses:
          self.append_additional_excess(_e, wtx=wtx)
      rollback_updates = []
      for _i in tx.inputs:
          ind= _i.serialized_index
          rb = self.update_spent_address_with_excess(_i.address_excess_num_index, tx.updated_excesses[ind], wtx=wtx)
          rollback_updates.append(rb)
      self.set_state(new_state, wtx=wtx)
      return len(tx.additional_excesses)+len(tx.outputs), rollback_updates

    def rollback(self, num_of_added_excesses, prev_state, rollback_updates, wtx):
      self.excesses.remove(num_of_added_excesses, wtx=wtx)
      self.set_state(prev_state, wtx=wtx)
      for rb in rollback_updates:
        self.update_spent_address_with_serialized_excess(rb[0], rb[1], rb[2], wtx=wtx)

    def get_state(self, rtx):
      return self.excesses.get_state(rtx=rtx)

    def set_state(self, state, wtx):
      self.excesses.set_state(state, wtx=wtx)
