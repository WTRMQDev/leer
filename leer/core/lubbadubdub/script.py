from leer.core.utils import sha256
from leer.core.storage.lookup_utils import excess_lookup, excess_lookup_by_index
from secp256k1_zkp import Point
from leer_vm import execute

def evaluate_scripts(tx, prev_block_props, excess_lookup):
  """
    Check wether all excesses in tx evaluate to True.
  """
  def find_output(commitment):
    pc = commitment.to_pedersen_commitment()
    ser = pc.serialize()
    for o in tx.outputs:
      if ser == o.serialized_apc:
        return o
    return None

  def output_lookup(commitment):
    return bool(find_output(commitment))

  burdens = []
  excesses = tx.additional_excesses + list(tx.updated_excesses.values())
  for excess in excesses:
    burden = []
    result = execute(script = excess.message,
                     prev_block_props = prev_block_props,
                     excess_lookup = excess_lookup,
                     output_lookup = output_lookup,
                     burden = burden)
    if not result:
      return False
    if len(burden):
      for comm, pubkey in burden:
        output = find_output(comm)
        pk = pubkey.to_pubkey()
        if not pk.serialize() == output.address.serialized_pubkey:
          return False
        excess_index = pk.serialize() + sha256(b"\x01\x00"+output.serialized_apc)
        burdens.append((output.serialized_index, excess_index))
  tx.burdens = burdens
  return True

def check_burdens(tx, burden_storage, excesses_storage, rtx):
  excesses = tx.additional_excesses + list(tx.updated_excesses.values())
  eis = [e.index for e in excesses]
  for i in tx.inputs:
    if burden_storage.has(i.serialized_index, rtx=rtx): 
      required_index = burden_storage.get(i.serialized_index, rtx=rtx)
      if not bool(excess_lookup_by_index(required_index, tx=tx, rtx=rtx, excesses_storage =excesses_storage)):
        return False
  return True

def generate_proof_script(output):
  script = b""
  OP_PUSHPOINT = (0x03).to_bytes(1, "big")
  OP_OUTPUTORHASH = (0x27).to_bytes(1, "big")
  OP_TRUE = (0x01).to_bytes(1, "big")
  pubkey_point = Point(output.address.pubkey)
  commitment_point = Point(output.authorized_pedersen_commitment)
  script = OP_PUSHPOINT + pubkey_point.serialize() + OP_PUSHPOINT + commitment_point.serialize() + OP_OUTPUTORHASH + OP_TRUE
  return script
  
