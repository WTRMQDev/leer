from leer.core.primitives.header import Header
from leer.core.hash.progpow import progpow_hash, handler as pp_handler
import requests
import json
import base64
from random import randint
from time import time, sleep


HOST = "http://0.0.0.0"
PORT = "9238"

def basic_request(method, params=[]):
   url = "%s:%s/rpc"%(HOST, str(PORT))
   headers = {'content-type': 'application/json'} 
   payload = {
               "method": method,
               "params": params,
               "jsonrpc": "2.0",
               "id": 0,
             }
   response = requests.post( url, data=json.dumps(payload), headers=headers, auth = (INSERT_LOGIN_HERE, INSERT_PASSWORD_HERE))
   result = json.loads(response.text)
   if 'error' in result:
     raise Exception(result['error'])
   return result['result']

def check_solution(height, partial_hash, int_nonce, int_target):
  _hash = progpow_hash(partial_hash+int_nonce.to_bytes(16,'big'))
  if int.from_bytes(_hash, "big") < int_target:
    return True
  return False 

def get_height():
  return basic_request('getheight')

def start_mining():
  while True:
    print("Start mining new block")
    initial_time = time()
    height_check_time = initial_time
    basic_nonce = randint(0, int(256**3))
    block_template = basic_request('getblocktemplate')
    block_template = base64.b64decode(block_template.encode())
    header = Header()
    header.deserialize(block_template)
    print("Got template. Block height %d. Block target %d (* 2**220). Average hashes for block %d. Block timestamp %d"%(header.height,header.target/2**220, 2**256/header.target, header.timestamp)) 
     
    partial_template = block_template[:-16]
    nonce = 0
    step = next_level = 16
    update_block = False
    height, target = header.height, header.target
    partial_hash = header.partial_hash
    solution_found = False
    while not solution_found:
      res = pp_handler.light_search(1, partial_hash, target.to_bytes(32,"big"), start_nonce = basic_nonce+nonce, iterations = next_level, step=step)
      solution_found = res['solution_found']
      if res['solution_found']:
        final_nonce, final_hash = res['nonce'], res['final_hash']
        break
      nonce += next_level
      if time()-height_check_time>5:
        height_check_time = time()
        if height<=get_height():
          print("New block on network")
          update_block = True
          break
      if not nonce%next_level:
        next_level*=2
        print("Nonce reached %d"%nonce)

        
    final_time = time()
    if update_block:
      print("Hashrate %d H/s"%(int(nonce/(final_time-initial_time))))
      continue
    print("Get solution. Nonce = %d (final_nonce %d). Hashrate %d H/s"%(nonce, final_nonce, int(nonce/(final_time-initial_time))))
    solution =partial_template +final_nonce.to_bytes(8,'big')
    encoded_solution = base64.b64encode(solution).decode()
    res = basic_request('validatesolution', [encoded_solution])
    print("Submitted block. Result %s"%res)

if __name__ == '__main__':
  while True:
    try:
      start_mining()
    except Exception as e:
      print("Error occured %s"%(str(e)))
  
