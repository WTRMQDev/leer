from leer.core.primitives.header import Header
from leer.core.hash.progpow import seed_hash as progpow_seed_hash
from leer.core.core_operations.sending_metadata import notify_all_nodes_about_new_tip

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
    core.send_to_subprocess(message["sender"], {"id": message["id"], "result":ser_head})
  except Exception as e:
    core.send_to_subprocess(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
    core.logger.error("Can not generate block `%s`"%(str(e)), exc_info=True)


def give_mining_work(message, wtx, core):
  try:
    ensure_mining_address(core)
    assert_mining_conditions(rtx=wtx, core=core)
    partial_header_hash, target, height = core.storage_space.mempool_tx.give_mining_work(core.mining_address, wtx=wtx)
    seed_hash = progpow_seed_hash(height)
    core.send_to_subprocess(message["sender"], {"id": message["id"], 
              "result":{'partial_hash':partial_header_hash.hex(), 
                        'seed_hash':seed_hash.hex(),
                        'target':target.hex(),
                        'height':height
                       }})
  except Exception as e:
    core.send_to_subprocess(message["sender"], {"id": message["id"], "result":"error", "error":str(e)})
    core.logger.error("Can not generate block `%s`"%(str(e)), exc_info=True)

def add_solved_block(block, wtx, core):
    mempool, headerchain, blockchain = core.storage_space.mempool_tx, \
                                       core.storage_space.headers_manager, \
                                       core.storage_space.blockchain
    if block.header.height <= blockchain.current_height(rtx=wtx):
      return "stale"
    initial_tip = blockchain.current_tip(rtx=wtx)
    headerchain.add_header(block.header, wtx=wtx)
    headerchain.context_validation(block.header.hash, rtx=wtx)
    block.non_context_verify(rtx=wtx)
    blockchain.add_block(block, wtx=wtx)
    after_tip = blockchain.current_tip(rtx=wtx)
    our_height = blockchain.current_height(rtx=wtx)
    best_known_header = headerchain.best_header_height
    core.notify("best header", best_known_header)
    core.notify("blockchain height", our_height)
    if not after_tip==initial_tip:
      notify_all_nodes_about_new_tip(core.nodes, rtx=wtx, core=core) #XXX
    return "accepted"


def process_solution(solution_type, message, wtx, core):
  try:
    if solution_type == "block template":
      header = Header()
      header.deserialize(message["solved template"])
      solved_block = core.storage_space.mempool_tx.get_block_by_header_solution(header)
    elif solution_type == "work":
      nonce, partial_work = message['nonce'], message['partial_hash']
      solved_block =  core.storage_space.mempool_tx.work_block_assoc[partial_work]
      solved_block.header.nonce = nonce
    result = add_solved_block(solved_block, wtx, core)
    if result == "stale":
      core.send_to_subprocess(message["sender"], {"id": message["id"], "result": "Stale"})
      core.logger.error("Stale work submitted: height %d"%(header.height))
      return
    elif result == "accepted":
      core.send_to_subprocess(message["sender"], {"id": message["id"], "result": "Accepted"})
  except Exception as e:
    core.logger.error("Wrong block solution %s"%str(e))
    core.send_to_subprocess(message["sender"], {"id": message["id"], "error": str(e), 'result':'error'})

def take_solved_block_template(message, wtx, core):
  process_solution("block template", message, wtx, core)

def take_mining_work(message, wtx, core):
  process_solution("work", message, wtx, core)

mining_operations = {"give block template":give_block_template,\
                     "give mining work":give_mining_work,\
                     "take solved block template":take_solved_block_template,\
                     "take mining work":take_mining_work\
                    }

