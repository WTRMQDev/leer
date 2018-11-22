from time import time, sleep
from leer.wallet.key_manager import KeyManagerClass
def wallet(syncer, config):
  '''
    Wallet is synchronous service which holds private keys and information about 
    owned outputs. It provides information for transactions and block templates
    generation.
  '''
  message_queue = syncer.queues['Wallet']
  _path = config['location']['wallet_path']
  km = KeyManagerClass(_path)
  while True:
    sleep(0.01)
    while not message_queue.empty():
      message = message_queue.get()
      if not 'action' in message:
        continue
      if message['action']=="process new block":
        pass
      if message['action']=="process rollback":
        pass
      if message['action']=="process indexed outputs": #during private key import correspondent outputs will be processed again
        pass
      if message['action']=="give new address raw object"
        pass
      if message['action']=="give new address"
        pass
      if message['action']=="get confirmed balance stats"
        pass
      if message['action']=="get confirmed balance list"
        pass
      if message['action']=="give private key"
        pass
      if message['action']=="take private key"
        pass
      if message['action']=="send to address"
        pass
      if message['action']=="give new address"
        pass
    

