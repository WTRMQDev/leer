from functools import partial
class CoreContext:
  """
    CoreContext contains resources which are required during delegation of core processing
    It contains storage_space, core logger, nodes list, send_notification and send_message interfaces.
  """

  def __init__(self, storage_space, logger, nodes, send_notification, send_message, config):
    self.storage_space = storage_space
    self.logger = logger
    self.nodes = nodes
    self.notify = send_notification 
    self.send_to = send_message
    self.send_to_nm = partial(self.send_to, "NetworkManager")
    self.config = config

