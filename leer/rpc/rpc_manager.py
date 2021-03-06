from aiohttp import web
from aiohttp_remotes import BasicAuth, setup
from jsonrpcserver.aio import methods
from jsonrpcserver.exceptions import ServerError

from concurrent.futures._base import CancelledError
try:
  from asyncio.base_futures import InvalidStateError
except ImportError:
  from asyncio.futures import InvalidStateError

import asyncio
import logging
import json
from uuid import uuid4
import base64
from secp256k1_zkp import PrivateKey
from os.path import split as path_split, join
from time import time

from jsonrpcserver.dispatcher import request_logger, response_logger
from aiohttp.web import access_logger

from leer import version
request_logger.setLevel(logging.ERROR)
response_logger.setLevel(logging.ERROR)
access_logger.setLevel(logging.ERROR)

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
    default_log_level = logging.INFO;
    if "logging" in config:#debug, info, warning, error, critical
      loglevels = { "debug":logging.DEBUG, "info":logging.INFO, "warning":logging.WARNING, "error":logging.ERROR, "critical":logging.CRITICAL}
      if "base" in config["logging"] and config["logging"]["base"] in loglevels:
        self.logger.setLevel(loglevels[config["logging"]["base"]])
      if "rpc" in config["logging"] and config["logging"]["rpc"] in loglevels:
        #its ok to rewrite
        self.logger.setLevel(loglevels[config["logging"]["rpc"]])

    rpc_manager_location = __file__
    web_wallet_dir = join(path_split(rpc_manager_location)[0], "web_wallet")
    self.app = web.Application(loop=self.loop)
    self.loop.run_until_complete(setup(self.app, BasicAuth(config['rpc']['login'],config['rpc']['password'], "realm", white_paths=['/'])))
    
    self.app.router.add_route('*', '/rpc', self.handle)
    self.app.router.add_route('*', '/', self.handle_root)
    self.app.router.add_static('/',web_wallet_dir)
    self.server = self.loop.create_server(self.app.make_handler(), self.host, self.port)
    asyncio.ensure_future(self.server, loop=loop)
    asyncio.ensure_future(self.check_queue())

    methods.add(self.ping)
    methods.add(self.getconnectioncount)
    methods.add(self.getheight)
    methods.add(self.getblocktemplate)
    methods.add(self.getwork)
    methods.add(self.submitwork)
    methods.add(self.validatesolution)
    methods.add(self.getbalancestats)
    methods.add(self.getbalancelist)
    methods.add(self.getbalance)
    methods.add(self.sendtoaddress)
    methods.add(self.getnewaddress)
    methods.add(self.dumpprivkey)
    methods.add(self.importprivkey)
    methods.add(self.getsyncstatus)
    methods.add(self.getblock)
    methods.add(self.getnodes)
    methods.add(self.connecttonode)
    methods.add(self.gettransactions)
    methods.add(self.getversion)
    methods.add(self.shutdown)


    methods.add(self.eth_getWork)
    methods.add(self.eth_submitWork)
    methods.add(self.eth_getBlockByNumber)
    self.no_auth_methods = ["eth_getWork", "eth_submitWork", "eth_getBlockByNumber"]

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

  async def handle_root(self, request):
    try:
      request_text = await request.text()
      if request_text=="":
        response = web.HTTPSeeOther("/index.html")
        return response
      else:
        try:
          rqst = json.loads(request_text)
          assert rqst["method"] in self.no_auth_methods
          response = await methods.dispatch(request_text, schema_validation=False)
          return web.json_response(response, status=response.http_status)
        except:
          return web.Response(request)
    except CancelledError:
      return web.Response() #TODO can we set response.wanted to false?    

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
    res = answer['result']
    if not res=="error":
      return base64.b64encode(res).decode()
    else:
      exc = ServerError()
      exc.message = answer["error"]
      raise exc

  async def getwork(self):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'give mining work', 'id':_id, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    if not answer["result"]=="error":
      res = ["0x"+answer["result"]["partial_hash"].upper(),\
             "0x"+answer["result"]["seed_hash"].upper(),\
             "0x"+(answer["result"]["target"]).upper(),\
             "0x"+answer["result"]["height"].to_bytes(8, "big").hex().upper()]
      return res
    else:
      return answer["error"]

  async def submitwork(self, hex_nonce, partial_hash_hex, compatibility_field):
    _id = str(uuid4())
    if "0x"==hex_nonce[:2]:
     hex_nonce = hex_nonce[2:]
    if "0x"==partial_hash_hex[:2]:
     partial_hash_hex = partial_hash_hex[2:]
    nonce = int(hex_nonce, 16).to_bytes(8, "big")
    partial_hash = bytes.fromhex(partial_hash_hex)
    self.syncer.queues['Blockchain'].put({'action':'take mining work', 'id':_id, 'sender': "RPCManager",
                                          'nonce':nonce, 'partial_hash':partial_hash})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    if answer["result"]=="error":
      return answer["error"]
    return answer['result']

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
    self.syncer.queues['Wallet'].put({'action':'generate tx', 'id':_id,
                                          'address': address, 'value': value,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    if answer['result']=='error':
      return answer['error']
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'add tx to mempool', 'id':_id,
                                          'tx': answer['result'],
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
    self.syncer.queues['Wallet'].put({'action':'give private key', 'id':_id,
                                          'address':address, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    tprivkey = base64.b64encode(answer['result']).decode()
    return tprivkey

  async def importprivkey(self, tprivkey, rescan=True): #TODO DOESN'T WORK
    _id = str(uuid4())
    privkey = base64.b64decode(tprivkey)
    self.syncer.queues['Wallet'].put({'action':'take private key', 'id':_id,
                                          'privkey':privkey, "rescan": rescan, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def getblock(self, block_num):
    _id = str(uuid4())
    self.syncer.queues['Blockchain'].put({'action':'give block info', 'id':_id,
                                          'block_num':block_num, 'sender': "RPCManager"})
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
    
    self.syncer.queues['Notifications'].put({'action':'get', 'id':_id, 'key': 'last wallet update','sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    last_wallet_update_answer = await self.requests[_id]
    self.requests.pop(_id)
    last_wallet_update = 0
    if not last_wallet_update_answer['result']=='error':
      last_wallet_update = last_wallet_update_answer['result']['value']
 
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
    response['last_wallet_update'] = last_wallet_update;
    return response


  async def getnodes(self):
    _id = str(uuid4())
    self.syncer.queues['NetworkManager'].put({'action':'give my node', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    res = []
    if 'error' in answer['result']:
      return answer['result']
    for hp in answer['result']:
      host, port = hp
      static_key = base64.b64encode(answer['result'][hp]).decode()
      res.append({'host':str(host), 'port':port, 'static_key':static_key})

    _id = str(uuid4())
    self.syncer.queues['NetworkManager'].put({'action':'give nodes list', 'id':_id,
                                          'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    if 'error' in answer['result']:
      return answer['result']
    for hp in answer['result']:
      host, port = hp
      static_key = base64.b64encode(answer['result'][hp]['pubkey']).decode()
      version = answer['result'][hp]['version']
      res.append({'host':str(host), 'port':str(port), 'static_key':static_key, 'version':version})
    return res

  async def connecttonode(self, node_str):
    _id = str(uuid4())
    (hp,sk)=node_str.split("@")
    host, port = hp.split(":")
    pub = base64.b64decode(sk.encode())
    self.syncer.queues['NetworkManager'].put({'action':'open connection', 'host':host,
         'port':port, 'static_key':pub, 'id':_id, 'sender': "RPCManager"})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  async def gettransactions(self, num):
    _id = str(uuid4())
    self.syncer.queues['Wallet'].put({'action':'give last transactions info', 'id':_id,
                                      'sender': "RPCManager", 'num':int(num)})
    self.requests[_id]=asyncio.Future()
    answer = await self.requests[_id]
    self.requests.pop(_id)
    return answer['result']

  #Ethereum compatibility
  async def eth_getWork(self):
    _hash, seed, target, height = await self.getwork()
    # GPU miners work very bad with low diff target
    #dirty hack, to made minimal target 1m
    if int(target[2:9], 16)>3:
      target = "0x0000003"+target[9:]
    return _hash, seed, target, height 

  async def eth_submitWork(self,hex_nonce, partial_hash_hex, mix_digest):
    res = await self.submitwork(hex_nonce, partial_hash_hex, mix_digest)
    return res=="Accepted"

  async def eth_getBlockByNumber(self, tag):
    '''
      Only returns block_number and difficulty in hex format.
    '''
    if not tag=='pending':
      return "Works only for pending tag"
    partial, seed, target, height = await self.getwork()
    difficulty = 2**256//int(target[2:], 16)
    return {'number':height.to_bytes(8, "big").hex(), 'difficulty':difficulty.to_bytes(8, "big").hex()}

  async def getversion(self):
    leer_version, leer_codename = version.VERSION, version.CODENAME
    return {'version':leer_version, 'codename':leer_codename}
    
  async def shutdown(self):
    self.syncer.queues['Blockchain'].put({'action':'shutdown', 'sender': "RPCManager"})
    return "Prepairing shutdown"
    
 
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
          elif message["action"] == "stop":
            self.logger.info("RPC server stops")
            self.loop.stop()    
        else:
          pass 
      await asyncio.sleep(0.2)
    

def RPCM_launcher(syncer, config):
  loop = asyncio.new_event_loop() #TODO use uvloop 
  asyncio.set_event_loop(loop)
  RPCM = RPCManager(loop, syncer, config)
  loop.run_forever()
