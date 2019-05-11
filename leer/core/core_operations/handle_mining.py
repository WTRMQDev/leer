def assert_mining_conditions(config, nodes, storage_space, rtx):
  if "mining" in config and "conditions" in config["mining"]:
    if "connected" in config["mining"]["conditions"]:
      if not len(nodes):
        raise Exception("Cant start mining with zero connections")
    if "synced_headers" in config["mining"]["conditions"]:
      best_block, best_header = storage_space.blockchain.current_height(rtx),\
                                storage_space.headers_manager.best_header_height
      if best_block<best_header:
        raise Exception("Cant start mining while best block %d worse than best known header %d"%(best_block, best_header))
    if "synced_advertised" in config["mining"]["conditions"]:
      best_block, best_advertised_height = storage_space.blockchain.current_height(rtx),\
                                           max([nodes[node]["height"] for node in nodes if "height" in nodes[node]])
      if best_block<best_advertised_height:
        raise Exception("Cant start mining while best block %d worse than best advertised block %d"%(best_block, best_advertised_height))

