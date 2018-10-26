from aiohttp import web
from jsonrpcserver.aio import methods
from concurrent.futures._base import CancelledError
import asyncio
import logging
import json
from uuid import uuid4
import base64
from secp256k1_zkp import PrivateKey
from os.path import split as path_split, join

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
    request = await request.text()
    response = await methods.dispatch(request, schema_validation=False)
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
    self.syncer.queues['Blockchain'].put({'action':'give tip height', 'id':_id, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

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
    self.syncer.queues['Blockchain'].put({'action':'get confirmed balance stats', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']


  async def getbalancelist(self):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'get confirmed balance list', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getbalance(self):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'get confirmed balance stats', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']['matured']['known_value']

  async def sendtoaddress(self, address, value):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'send to address', 'id':_id,
                                          'address': address, 'value': value,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getnewaddress(self):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'give new address', 'id':_id,
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
    self.syncer.queues['Blockchain'].put({'action':'give synchronization status', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']


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
        print(message)
        if 'id' in message:
          if message['id'] in self.requests:
            self.requests[message['id']].set_result(message)
        else:
          pass # Now RPCManager can only get answers to own requests
      await asyncio.sleep(0.2)
    

def RPCM_launcher(syncer, config):
  loop = asyncio.new_event_loop() #TODO use uvloop 
  asyncio.set_event_loop(loop)
  RPCM = RPCManager(loop, syncer, config)
  loop.run_forever()
