def assert_mining_conditions(config, rtx, core):
  if "mining" in config and "conditions" in config["mining"]:
    if "connected" in config["mining"]["conditions"]:
      if not len(core.nodes):
        raise Exception("Cant start mining with zero connections")
    if "synced_headers" in config["mining"]["conditions"]:
      best_block, best_header = core.storage_space.blockchain.current_height(rtx),\
                                core.storage_space.headers_manager.best_header_height
      if best_block<best_header:
        raise Exception("Cant start mining while best block %d worse than best known header %d"%(best_block, best_header))
    if "synced_advertised" in config["mining"]["conditions"]:
      best_block, best_advertised_height = core.storage_space.blockchain.current_height(rtx),\
                                           max([core.nodes[node]["height"] for node in core.nodes if "height" in core.nodes[node]])
      if best_block<best_advertised_height:
        raise Exception("Cant start mining while best block %d worse than best advertised block %d"%(best_block, best_advertised_height))

