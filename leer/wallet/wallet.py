from time import time, sleep
from leer.wallet.key_manager import KeyManagerClass

from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Address
from leer.core.lubbadubdub.transaction import Transaction

from uuid import uuid4
import logging
import base64
     


logger = logging.getLogger("Wallet")

def wallet(syncer, config):
  '''
    Wallet is synchronous service which holds private keys and information about 
    owned outputs. It provides information for transactions and block templates
    generation.
  '''
  def get_height(timeout=2.5):
    _id = str(uuid4())
    syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'blockchain height','sender': "Wallet"})
    message_queue = syncer.queues['Wallet']
    start_time = time()
    result = None
    while True:
      put_back = [] #We wait for specific message, all others will wait for being processed
      while not message_queue.empty():
        message = message_queue.get()
        if (not 'id' in message)  or (not message['id']==_id):
          put_back.append(message)
          continue
        result = message['result']
        break
      for message in put_back:
        message_queue.put(message)
      if result:
        break
      sleep(0.01)
      if time()-start_time>timeout:
        raise KeyError
    if result=='error':
      raise KeyError
    return result['value']

  notification_cache = {}
  def notify(key, value, timestamp=None):
    if (key in notification_cache) and (notification_cache[key]['value'] == value) and (time()-notification_cache[key]['timestamp'])<5:
      return #Do not spam notifications with the same values
    message = {}
    message['id'] = uuid4()
    message['sender'] = "Wallet"
    if not timestamp:
      timestamp = time()
    message['time'] = timestamp
    message['action']="set"
    message['key']=key
    message['value']=value
    syncer.queues["Notifications"].put(message)
    notification_cache[key] = {'value':value, 'timestamp':timestamp}


  message_queue = syncer.queues['Wallet']
  _path = config['location']['wallet']
  km = KeyManagerClass(path=_path)
  notify('last wallet update', time())
  while True:
    sleep(0.01)
    while not message_queue.empty():
      message = message_queue.get()
      logger.info("Process message %s"% message)
      if not 'action' in message:
        continue
      if message['action']=="process new block":
        tx = Transaction(txos_storage=None, excesses_storage=None)
        tx.deserialize(message['tx'], rtx=None, skip_verification=True) #skip_verification allows us to not provide rtx
        block_height = message['height']
        last_time_updated = None
        for index in tx.inputs:
          if km.is_unspent(index): #Note it is not check whether output is unspent or not, we check that output is marked as our and unspent in our wallet
            km.spend_output(index, block_height)
            last_time_updated = time()
        for _o in tx.outputs:
          if km.is_owned_pubkey(_o.address.pubkey.serialize()):
            km.add_output(_o, block_height)
            last_time_updated = time()
        if last_time_updated:
          notify('last wallet update', last_time_updated)
      if message['action']=="process rollback":
        rollback = message['rollback_object']
        block_height = message['block_height']
        km.rollback(block_height)
        last_time_updated = time()
        notify('last wallet update', last_time_updated)
      if message['action']=="process indexed outputs": #during private key import correspondent outputs will be processed again
        pass
      if message['action']=="give new taddress":
        address = km.new_address()
        response = {"id": message["id"], "result": address.to_text()}
        syncer.queues[message['sender']].put(response)
      if message['action']=="give new address":
        address = km.new_address()
        response = {"id": message["id"], "result": address.serialize()}
        syncer.queues[message['sender']].put(response)
      if message['action']=="get confirmed balance stats":
        response = {"id": message["id"]}
        try:
          height = get_height()
          stats = km.get_confirmed_balance_stats(height)
          response["result"] = stats
        except KeyError:
          response["result"] = "error: core_loop didn't set height yet"
        except Exception as e:
          response["result"] = "error: " +str(e)
        syncer.queues[message['sender']].put(response)
      if message['action']=="get confirmed balance list":
        response = {"id": message["id"]}
        try:
          height = get_height()
          stats = km.get_confirmed_balance_list(height)
          response["result"] = stats
        except KeyError:
          response["result"] = "error: core_loop didn't set height yet"
        except Exception as e:
          response["result"] = "error: " +str(e)
        syncer.queues[message['sender']].put(response)
      if message['action']=="give private key":
        pass
      if message['action']=="take private key":
        pass
      if message['action']=="generate tx template":
        response = {"id": message["id"]}
        value  = int(message["value"])
        taddress = message["address"]
        a = Address()
        a.from_text(taddress)
        try:
          current_height = get_height()
        except KeyError:
           response["result"] = "error"
           response["error"] = "core_loop didn't set height yet"
           syncer.queues[message['sender']].put(response)
           continue
        except Exception as e:
           response["result"] = "error"
           response["error"] = str(e)
           syncer.queues[message['sender']].put(response)
           continue
        _list = km.get_confirmed_balance_list(current_height)
        list_to_spend = []
        summ = 0 
        utxos = []
        for address in _list:
            for texted_index in _list[address]:
              if summ>value+100000000: #TODO fee here
                continue
              if isinstance(_list[address][texted_index], int):
                _index = base64.b64decode(texted_index.encode())
                utxos.append(_index)
                summ+=_list[address][texted_index]
        if summ < value:
            response["result"] = "error"
            response["error"] = "Not enough matured coins"
            syncer.queues[message['sender']].put(response)
            continue
        
        tx_template = { 'priv_by_pub': {}, 'change address': km.new_address().serialize(), 'utxos':utxos,
                        'address': a.serialize(), 'value': value }
        for utxo in utxos:
          pub,priv = km.priv_and_pub_by_output_index(utxo)
          tx_template['priv_by_pub'][pub]=priv
        
        response["result"]=tx_template
        syncer.queues[message['sender']].put(response)
      if message['action']=="stop":
        return

    

