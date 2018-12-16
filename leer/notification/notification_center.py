from time import time, sleep

def notification_center_launcher(syncer, config):
  '''
    Notification center is generally memcache. It has no inner logic and thus is synchronous
  '''
  message_queue = syncer.queues['Notifications']
  keyvalue = {}
  while True:
    sleep(0.001)
    while not message_queue.empty():
      message = message_queue.get()
      if not 'action' in message:
        continue
      if not message['action'] in ['set', 'get']:
        continue
      if not 'time' in message:
        message['time'] = time()
      if message['action']=="set":
        result = None
        try:
          keyvalue[message['key']]={'value':message['value'], 'time':message['time']}
          result = True
        except KeyError as e:
          result = False
          error = e
        if ('id' in message) and ('sender' in message):
          if result:
            syncer.queues[message['sender']].put({'id':message['id'], 'result':'set'})
          else:
            syncer.queues[message['sender']].put({'id':message['id'], 'result':'error', 'error':str(e)})
      if message['action']=="get":
        error=None
        if (not 'id' in message) or (not 'sender' in message):
          continue
        try:
          result = keyvalue[message['key']]
        except KeyError as e:
          result = None
          error = e
        if result:
            syncer.queues[message['sender']].put({'id':message['id'], 'result':result})
        else:
            syncer.queues[message['sender']].put({'id':message['id'], 'result':'error', 'error':str(error)})
      if message['action']=="stop":
        return
