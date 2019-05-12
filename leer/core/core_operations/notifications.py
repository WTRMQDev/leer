from uuid import uuid4
from time import time

def set_notify_wallet_hook(blockchain, wallet_message_queue):
    def notify_wallet(reason, *args):
      message={'sender':"Blockchain"}
      #no id: notification
      if reason == "apply":
        message['action'] = "process new block"
        message['tx'] = args[0].serialize()
        message['height'] = args[1]      
      elif reason == "rollback":
        message['action'] = "process rollback"
        message['rollback_object'] = args[0].serialize()
        message['block_height'] = args[1]
      else:
        pass
      wallet_message_queue.put(message)
    blockchain.notify_wallet = notify_wallet 

set_value_cache = {} #We do not clean set_value_cache and its maximal size bounded by number distinct parameters we set
def set_value_to_queue(queue, sender, key, value, timestamp=None):
    if (key in set_value_cache) and (set_value_cache[key]['value'] == value) and (time()-set_value_cache[key]['timestamp'])<5:
      return #Do not spam  with the same values
    message = {}
    message['id'] = uuid4()
    message['sender'] = sender
    if not timestamp:
      timestamp = time()
    message['time'] = timestamp
    message['action']="set"
    message['key']=key
    message['value']=value
    queue.put(message)
    set_value_cache[key] = {'value':value, 'timestamp':timestamp}
