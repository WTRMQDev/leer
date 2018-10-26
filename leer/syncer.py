import multiprocessing

class Syncer:
  'This class holds all sync objects'
  queue_ids = ['NetworkManager', 'Blockchain', 'RPCManager']
  def __init__(self, chains_ids=[], file_paths=[]):
   self.file_locks = {}
   for file_path in file_paths:
     self.file_locks[file_path]=multiprocessing.Lock()
   self.queues = {i: multiprocessing.Queue() for i in Syncer.queue_ids}

