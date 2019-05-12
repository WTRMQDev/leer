from leer.core.primitives.block import Block
from leer.core.parameters.constants import serialized_genesis_block

def init_blockchain(storage_space, wtx, logger):
  '''
    If blockchain is empty this function will set genesis.
  '''
  genesis = Block(storage_space = storage_space)
  genesis.deserialize(serialized_genesis_block)
  storage_space.headers_manager.set_genesis(genesis.header, wtx=wtx)
  if storage_space.blockchain.current_height(rtx=wtx)<0:
    storage_space.headers_manager.context_validation(genesis.header.hash, rtx=wtx)
    genesis.non_context_verify(rtx=wtx)
    storage_space.blockchain.add_block(genesis, wtx=wtx)
  else:
    storage_space.headers_manager.best_tip = (storage_space.blockchain.current_tip(rtx=wtx), storage_space.blockchain.current_height(rtx=wtx) )
    logger.info("Best header tip from blockchain state %d"%storage_space.headers_manager.best_tip[1])
    #greedy search
    current_tip = storage_space.headers_manager.best_tip[0]
    while True:
      try:
        header = storage_space.headers_storage.get(current_tip, rtx=wtx)
      except KeyError:
        break
      new_current_tip=current_tip
      if len(header.descendants):
        for d in header.descendants:
          dh = storage_space.headers_storage.get(d, rtx=wtx)
          if not dh.invalid:
            new_current_tip = d
            break
      if not new_current_tip == current_tip:
        current_tip=new_current_tip
      else:
        break
    storage_space.headers_manager.best_tip = (current_tip, storage_space.headers_storage.get(current_tip, rtx=wtx).height)
    logger.info("Best header tip after greedy search %d"%storage_space.headers_manager.best_tip[1])


def validate_state(storage_space, rtx, logger):
  if storage_space.blockchain.current_height(rtx=rtx)<1:
    return
  tip = storage_space.blockchain.current_tip(rtx=rtx)
  header = storage_space.headers_storage.get(tip, rtx=rtx)
  last_block_merkles = header.merkles
  state_merkles = [storage_space.txos_storage.confirmed.get_commitment_root(rtx=rtx), \
                   storage_space.txos_storage.confirmed.get_txo_root(rtx=rtx), \
                   storage_space.excesses_storage.get_root(rtx=rtx)]
  try:
    assert last_block_merkles == state_merkles
  except Exception as e:
    logger.error("State is screwed: state merkles are not coinside with last applyed block merkles. Consider full resync.\n %s\n %s\n Block num: %d"%(last_block_merkles, state_merkles, header.height))
    raise e

def set_ask_for_blocks_hook(blockchain, requests_cache):
  def f(block_hashes):
    if not isinstance(block_hashes, list):
      block_hashes=[block_hashes] #There is only one block
    requests_cache["blocks"]+=block_hashes
  blockchain.ask_for_blocks_hook = f

def set_ask_for_txouts_hook(block_storage, requests_cache):
  def f(txouts):
    requests_cache["txouts"]+=txouts
  block_storage.ask_for_txouts_hook = f

