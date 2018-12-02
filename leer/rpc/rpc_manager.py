from aiohttp import web
from jsonrpcserver.aio import methods
from concurrent.futures._base import CancelledError
from asyncio.base_futures import InvalidStateError
import asyncio
import logging
import json
from uuid import uuid4
import base64
from secp256k1_zkp import PrivateKey
from os.path import split as path_split, join
from time import time

class RPCManager():
  #Should be singleton?
  def __init__(self, loop, syncer, config):
    self.host = config['rpc']['host']
    self.port = config['rpc']['port']
    self.loop = loop
    self.syncer = syncer
    self.global_message_queue = self.syncer.queues['RPCManager']
    #self.allowed_clients
    self.requests = {}
    self.up = True
    self.logger = logging.getLogger("RPCManager")

    rpc_manager_location = __file__
    web_wallet_dir = join(path_split(rpc_manager_location)[0], "web_wallet")
    self.app = web.Application(loop=self.loop)
    
    self.app.router.add_static('/',web_wallet_dir)
    self.app.router.add_route('*', '/rpc', self.handle)
    self.server = self.loop.create_server(self.app.make_handler(), self.host, self.port)
    asyncio.ensure_future(self.server, loop=loop)
    asyncio.ensure_future(self.check_queue())

    methods.add(self.ping)
    methods.add(self.getconnectioncount)
    methods.add(self.getheight)
    methods.add(self.getblocktemplate)
    methods.add(self.validatesolution)
    methods.add(self.getbalancestats)
    methods.add(self.getbalancelist)
    methods.add(self.getbalance)
    methods.add(self.sendtoaddress)
    methods.add(self.getnewaddress)
    methods.add(self.dumpprivkey)
    methods.add(self.importprivkey)
    methods.add(self.getsyncstatus)

  async def handle(self, request):
    cors_origin_header = ("Access-Control-Allow-Origin", "*") #TODO should be restricted
    cors_headers_header = ("Access-Control-Allow-Headers", "content-type")
    if request.method=="OPTIONS":
      #preflight
      return web.Response(headers=[cors_origin_header, cors_headers_header])
    try:
      request = await request.text()
      response = await methods.dispatch(request, schema_validation=False)
    except CancelledError:
      return web.Response() #TODO can we set response.wanted to false?
    if response.is_notification:
        return web.Response()
    else:
        return web.json_response(response, status=response.http_status, headers=[cors_origin_header, cors_headers_header])


  async def ping(self):
    return 'pong'

  async def getconnectioncount(self):
    _id = str(uuid4())
    self.syncer.queues['NetworkManager'].put({'action':'get connections num', 'id':_id, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getheight(self):
    _id = str(uuid4())
    self.syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'blockchain height','sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    if answer['result']=='error' or time() - answer['result']['time'] > 120:
      _id = str(uuid4())
      self.syncer.queues['Blockchain'].put({'action':'give tip height', 'id':_id, 'sender': "RPCManager"})
      self.requests[_id]=asyncio.Future()
      answer = await self.requests[_id]      
      self.requests.pop(_id)
      height = answer['result']
    else:
      height = answer['result']['value']
    return height

  async def getblocktemplate(self):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'give block template', 'id':_id, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return base64.b64encode(answer['result']).decode()


  async def validatesolution(self, solution):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'take solved block template', 'id':_id,
                                          'sender': "RPCManager", 'solved template': base64.b64decode(solution.encode())})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getbalancestats(self):
    _id = str(uuid4())
    self.syncer.queues['Wallet'].put({'action':'get confirmed balance stats', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']


  async def getbalancelist(self):
    _id = str(uuid4())
    self.syncer.queues['Wallet'].put({'action':'get confirmed balance list', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getbalance(self):
    _id = str(uuid4())
    self.syncer.queues['Wallet'].put({'action':'get confirmed balance stats', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']['matured']['known_value']

  async def sendtoaddress(self, address, value):
    _id = str(uuid4())
    self.syncer.queues['Wallet'].put({'action':'generate tx template', 'id':_id,
                                          'address': address, 'value': value,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    if answer['result']=='error':
      return answer['error']
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'generate tx by tx template', 'id':_id,
                                          'tx_template': answer['result'],
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getnewaddress(self):
    _id = str(uuid4())
    self.syncer.queues['Wallet'].put({'action':'give new taddress', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def dumpprivkey(self, address):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'give private key', 'id':_id,
                                          'address':address, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def importprivkey(self, privkey):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'take private key', 'id':_id,
                                          'privkey':privkey, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getsyncstatus(self):
    _id = str(uuid4())
    self.syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'blockchain height','sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    blockchain_height_answer = await self.requests[_id]
    self.requests.pop(_id)

    self.syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'best header','sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    best_header_answer = await self.requests[_id]
    self.requests.pop(_id)

    self.syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'best advertised height','sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    best_advertised_answer = await self.requests[_id]
    self.requests.pop(_id)
    
    self.syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'core workload','sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    core_workload_answer = await self.requests[_id]
    self.requests.pop(_id)
    
    response = {}

    if ('error' in [blockchain_height_answer['result'], best_header_answer['result'], best_advertised_answer['result']]) or \
       time() - min([blockchain_height_answer['result']['time'], best_header_answer['result']['time'], best_advertised_answer['result']['time']])>120:
      _id = str(uuid4())
      self.syncer.queues['Blockchain'].put({'action':'give synchronization status', 'id':_id,
                                          'sender': "RPCManager"})
      self.requests[_id]=asyncio.Future()
      answer = await self.requests[_id]
      self.requests.pop(_id)
      response = answer['result']
    else:
      response = {
                  'height': blockchain_height_answer['result']['value'],
                  'best_known_header': best_header_answer['result']['value'],
                  'best_advertised_header': best_advertised_answer['result']['value'],
                  'core_workload': core_workload_answer['result']['value']
                 }
    return response


  '''async def addnode(self, request=None):
    print("1"*100,request)
    _id = str(uuid4())
    self.syncer.queues['NetworkManager'].put({'action':'get connections num', 'id':_id, 'request_source': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']
  '''
 
  async def check_queue(self):
    while self.up:
      while not self.global_message_queue.empty():
        message = self.global_message_queue.get()
        if 'id' in message:
          if message['id'] in self.requests:
            try:
              self.requests[message['id']].set_result(message)
            except InvalidStateError:
              self.requests.pop(message['id'])
              
        else:
          pass # Now RPCManager can only get answers to own requests
      await asyncio.sleep(0.2)
    

def RPCM_launcher(syncer, config):
  loop = asyncio.new_event_loop() #TODO use uvloop 
  asyncio.set_event_loop(loop)
  RPCM = RPCManager(loop, syncer, config)
  loop.run_forever()
