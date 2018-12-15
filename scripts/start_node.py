import asyncio
import logging
import sys

from urllib.request import urlopen
from functools import partial

from secp256k1_zkp import PrivateKey, PublicKey
from leer.syncer import Syncer
from leer.transport.network_manager import NM_launcher
from leer.rpc.rpc_manager import RPCM_launcher
from leer.core.core_loop import core_loop
from leer.notification.notification_center import notification_center_launcher
from leer.wallet.wallet import wallet as wallet_launcher
import multiprocessing
import time

from os.path import *
from os import urandom, path, makedirs

logging.basicConfig(level=logging.ERROR, format='%(asctime)s %(name)s %(levelname)s:%(message)s')

def get_public_IP():
    data = str(urlopen('http://checkip.dyndns.com/').read())
    pat="Current IP Address: "
    data = data[data.find(pat)+len(pat):]
    data = data.split("<")[0]
    return data

def get_static_key():
  comment =\
  '''
    P2p protocol which leer uses requires private key for encrypting communication.
    This key should be known prior communication. Nevertheless, this key is independent
    of any wallet or blockchain cryptography.
  '''
  try:
    with open(join(expanduser("~"), ".leertest/p2p_key"), "r") as f:
      for l in f.readlines():
        if not len(l) or l[0]=="#":
          continue
        key = int(l)
  except IOError:
    if not path.isdir(join(expanduser("~"), ".leertest")):
      makedirs(join(expanduser("~"), ".leertest"))
    key = int.from_bytes(urandom(32), "big")
    with open(join(expanduser("~"), ".leertest/p2p_key"), "w") as f:
      comment = "\n".join(["#"+i for i in comment.split("\n")])
      f.write(comment+'\n')
      f.write("%d"%key)
  return key
    


config = {
           'p2p':{
                    'host':'0.0.0.0', 
                    'port': 8888, 
                    'lspriv': get_static_key(),
                    'advertised_host': get_public_IP()
                 },
           'rpc':{
                    'host':'0.0.0.0', 
                    'port': 9238,
                    'login': INSERT_LOGIN_HERE,
                    'password': INSERT_PASSWORD_HERE
                 },
           'location': {
                         'basedir': join(expanduser("~"), ".leertest2") ,
                         'wallet': join(expanduser("~"), ".leertestwallet2")
                       },
           'bootstrap_nodes': [
                                {
                                  'host':'95.179.147.141',
                                  'port':'8888',
                                  'pub':b'\x03g*?\x08\xfa\xf8>!\xf7f&r\xb0zo\xe7\xe9`\x08W\xfd \rt6\xb3ks\xa2\xd6\x06e'
                                },
                                {
                                  'host':'185.10.68.161',
                                  'port':'8888',
                                  'pub':b'\x026\xa0\xb6\xcb\x08\xe3m\x85\xfdn?\x9e\x05\x8a\xf4ouq\x98\xef`Zx\xae\xedV\xc6\x9d\xfd-s\xe4'
                                }

                              ],
           'wallet' : True 
                       
         }



async def start_server(config, delay_before_connect=5):
    syncer=Syncer()
    nm = multiprocessing.Process(target=NM_launcher, args=(syncer, config))
    nm.start()
    rpcm = multiprocessing.Process(target=RPCM_launcher, args=(syncer, config))
    rpcm.start()
    core = multiprocessing.Process(target=core_loop, args=(syncer, config))
    core.start()
    await asyncio.sleep(delay_before_connect)
    notifications = multiprocessing.Process(target=notification_center_launcher, args=(syncer, config))
    notifications.start()
    wallet = multiprocessing.Process(target=wallet_launcher, args=(syncer, config))
    wallet.start()
    for node in config['bootstrap_nodes']:
      #print("Require connection from %d to %d: %s:%s:%s"%(server_id, node, 'localhost', p2p_port_by_id(node), pub_key_by_id(node)))
      syncer.queues['NetworkManager'].put(
        {'action':'open connection', 
         'host':node['host'],
         'port':node['port'],
         'static_key':node['pub'], 
         'id':int((time.time()*1e5)%1e5),
         'sender': "RPC"})
    while True:
      await asyncio.sleep(1)



loop = asyncio.get_event_loop()
asyncio.ensure_future(start_server(config))
loop.run_forever()

