from leer.core.storage.merkle_storage import MMR
from secp256k1_zkp import PedersenCommitment, PublicKey
from leer.core.storage.default_paths import excesses_storage_path
import hashlib
import os


def _hash(data):
        #TODO move to utils
        m=hashlib.sha256()
        m.update(data)
        return m.digest()

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
        second_part = _hash(hash1+hash2)
        return first_part+second_part




class ExcessesStorage():
    '''
      Excesses tree:
        Each excess leaf obj is serialized excess, leaf index is excess_index.
    '''
    __shared_states = {}

    def __init__(self, storage_space, path):
      if not path in self.__shared_states:
        self.__shared_states[path]={}
      self.__dict__ = self.__shared_states[path]
      self.excesses = ExcessMMR("excesses", os.path.join(path, "confirmed"), clear_only=False)
      self.storage_space = storage_space
      storage_space.register_excesses_storage(self)
      
    def append_utxo(self, utxo):
      self.excesses.append(utxo.address.index, b"")


    def append_additional_excess(self, excess):
      self.excesses.append(excess.index, excess.serialize())

    def __contains__(self, serialized_index):
      return bool(self.excesses.get_by_hash(serialized_index))

    def remove(self,n):
      self.excesses.remove(n)

    def get_root(self):
      return self.excesses.get_root()

    def apply_tx_get_merkles_and_rollback(self, tx):
      for _o in tx.outputs:
          self.append_utxo(_o)
      for _e in tx.additional_excesses:
          self.append_additional_excess(_e)

      root = self.get_root()

      self.excesses.remove(len(tx.additional_excesses)+len(tx.outputs))
      return root

    #TODO bad naming. It should be apply block, or block_transaction
    def apply_tx(self, tx, new_state):
      for _o in tx.outputs:
          self.append_utxo(_o)
      for _e in tx.additional_excesses:
          self.append_additional_excess(_e)
      self.set_state(new_state)
      return len(tx.additional_excesses)+len(tx.outputs)

    def rollback(self, num_of_added_excesses, prev_state):
      self.excesses.remove(num_of_added_excesses)
      self.set_state(prev_state)

    def get_state(self):
      return self.excesses.get_state()

    def set_state(self, state):
      self.excesses.set_state(state)
