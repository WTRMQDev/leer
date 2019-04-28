import asyncio
import logging
import sys
import multiprocessing
import time
import base64
import json
import re

from os.path import *
from os import urandom, path, makedirs
from urllib.request import urlopen

from secp256k1_zkp import PrivateKey, PublicKey
from leer.syncer import Syncer
from leer.transport.network_manager import NM_launcher
from leer.rpc.rpc_manager import RPCM_launcher
from leer.core.core_loop import core_loop
from leer.notification.notification_center import notification_center_launcher
from leer.wallet.wallet import wallet as wallet_launcher


def commentjson_loads(text, **kwargs):
    '''
      (c) -> https://github.com/vaidik/commentjson/
      We do not have commentjson as dependency to decrease exposure
    '''
    regex = r'\s*(#|\/{2}).*$'
    regex_inline = r'(:?(?:\s)*([A-Za-z\d\.{}]*)|((?<=\").*\"),?)(?:\s)*(((#|(\/{2})).*)|)$'
    lines = text.split('\n')
    for index, line in enumerate(lines):
        if re.search(regex, line):
            if re.search(r'^' + regex, line, re.IGNORECASE):
                lines[index] = ""
            elif re.search(regex_inline, line):
                lines[index] = re.sub(regex_inline, r'\1', line)
    minified = '\n'.join(lines)
    try:
      return json.loads(minified, **kwargs)    
    except Exception as e:
     err = str(e)
     have_line = err.find("line")
     if have_line>0:
       n = int(err[have_line+5:].split(" ")[0])
       print("Error in line `%s`"%lines[n])
       raise Exception("Problem with config")
     else:
       raise e

def get_public_IP():
    data = str(urlopen('http://checkip.dyndns.com/').read())
    pat="Current IP Address: "
    data = data[data.find(pat)+len(pat):]
    data = data.split("<")[0]
    return data

def get_static_key(filename):
  comment =\
  '''
    P2p protocol which leer uses requires private key for encrypting communication.
    This key should be known prior communication. Nevertheless, this key is independent
    of any wallet or blockchain cryptography.
  '''
  try:
    with open(filename, "r") as f:
      for l in f.readlines():
        if not len(l) or l[0]=="#":
          continue
        key = int(l)
  except IOError:
    raise
    #if not path.isdir(filename):
    #  makedirs(join(expanduser("~"), ".leertest"))
    key = int.from_bytes(urandom(32), "big")
    with open(filename, "w") as f:
      comment = "\n".join(["#"+i for i in comment.split("\n")])
      f.write(comment+'\n')
      f.write("%d"%key)
  return key



def main(config):
  logging.basicConfig(level=logging.ERROR, format='%(asctime)s %(name)s %(levelname)s:%(message)s')
  
  if "advertised_host" in config["p2p"] and config["p2p"]["advertised_host"] == "autodetect":
     config["p2p"]["advertised_host"] = get_public_IP()
  config["p2p"]["lspriv"]=get_static_key(expanduser(config["p2p"]["lspriv_file"]))
  if "location" in config:
    for t in config["location"]:
      config["location"][t] = expanduser(config["location"][t])
  for node in config.get("bootstrap_nodes",[]):
    node["pub"]= base64.b64decode(node["pub"])

  async def start_server(config, loop, delay_before_connect=5):
    syncer=Syncer()
    processes = []
    nm = multiprocessing.Process(target=NM_launcher, args=(syncer, config))
    nm.start()
    rpcm = multiprocessing.Process(target=RPCM_launcher, args=(syncer, config))
    rpcm.start()
    core = multiprocessing.Process(target=core_loop, args=(syncer, config))
    core.start()
    await asyncio.sleep(delay_before_connect)
    notifications = multiprocessing.Process(target=notification_center_launcher, args=(syncer, config))
    notifications.start()
    processes = [nm, rpcm, core, notifications]
    if "wallet" in config and config["wallet"]:
      wallet = multiprocessing.Process(target=wallet_launcher, args=(syncer, config))
      wallet.start()
      processes.append(wallet)
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
      for p in processes:
        if p.is_alive():
          continue
      loop.stop()
      return
      
  
  loop = asyncio.get_event_loop()
  asyncio.ensure_future(start_server(config, loop))
  loop.run_forever()




if __name__ == '__main__':
    relativ_config_path = sys.argv[1]
    config = None
    with open(relativ_config_path, "r") as f:
      raw_config = f.read()
      config = commentjson_loads(raw_config)  
    # execute only if run as the entry point into the program
    main(config)



