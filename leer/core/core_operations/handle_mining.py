def assert_mining_conditions(rtx, core):
  if "mining" in core.config and "conditions" in core.config["mining"]:
    if "connected" in core.config["mining"]["conditions"]:
      if not len(core.nodes):
        raise Exception("Cant start mining with zero connections")
    if "synced_headers" in core.config["mining"]["conditions"]:
      best_block, best_header = core.storage_space.blockchain.current_height(rtx),\
                                core.storage_space.headers_manager.best_header_height
      if best_block<best_header:
        raise Exception("Cant start mining while best block %d worse than best known header %d"%(best_block, best_header))
    if "synced_advertised" in core.config["mining"]["conditions"]:
      best_block, best_advertised_height = core.storage_space.blockchain.current_height(rtx),\
                                           max([core.nodes[node]["height"] for node in core.nodes if "height" in core.nodes[node]])
      if best_block<best_advertised_height:
        raise Exception("Cant start mining while best block %d worse than best advertised block %d"%(best_block, best_advertised_height))

def ensure_mining_address(core):
    try:
      assert core.mining_address
    except:
      core.mining_address = core.get_new_address()  

def give_block_template(message, wtx, core):
  try:
    ensure_mining_address(core)
    assert_mining_conditions(rtx=wtx, core=core)
    block = core.storage_space.mempool_tx.give_block_template(core.mining_address, wtx=wtx)
    ser_head = block.header.serialize()
    core.send_to(message["sender"], {"id": message["id"], "result":ser_head})
  except Exception as e:
    core.send_to(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
    core.logger.error("Can not generate block `%s`"%(str(e)), exc_info=True)


def give_mining_work(message, wtx, core):
  try:
    ensure_mining_address(core)
    assert_mining_conditions(rtx=wtx, core=core)
    partial_header_hash, target, height = storage_space.mempool_tx.give_mining_work(mining_address, wtx=wtx)
    seed_hash = progpow_seed_hash(height)
    core.send_to(message["sender"], {"id": message["id"], 
              "result":{'partial_hash':partial_header_hash.hex(), 
                        'seed_hash':seed_hash.hex(),
                        'target':target.hex(),
                        'height':height
                       }})
  except Exception as e:
    core.send_to(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
    core.logger.error("Can not generate block `%s`"%(str(e)), exc_info=True)
