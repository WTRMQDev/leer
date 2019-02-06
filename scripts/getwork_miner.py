from leer.core.primitives.header import Header
from leer.core.hash.mining_canary import mining_canary_hash_part
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

def check_solution(partial_hash, int_nonce, target):
  _hash = mining_canary_hash_part(partial_hash+int_nonce.to_bytes(16,'big'))
  if int.from_bytes(_hash, "big") < target:
    return True
  return False 

def get_height():
  return basic_request('getheight')

def getwork():
    work = basic_request('getwork')
    partial_hash, temp, target = work
    print(work)
    if partial_hash[:2]=="0x":
      partial_hash = partial_hash[2:]
    if target[:2]=="0x":
      target = target[2:]
    partial_hash, target = bytes.fromhex(partial_hash), bytes.fromhex(target)
    int_target = int.from_bytes(target, "big")
    return partial_hash, int_target

def start_mining():
  while True:
    print("Start mining new block")
    initial_time = time()
    last_update_time = initial_time
    basic_nonce = randint(0, int(256**10))
    partial_hash, int_target = getwork()
    print("Got work. Target %d (* 2**220). Average hashes for block %d."%(int_target/2**220, 2**256/int_target)) 
     
    nonce = 0
    next_level=4096
    update_block = False
    while not check_solution(partial_hash, nonce+basic_nonce, int_target):
      nonce+=1
      if time()-last_update_time>5:
        last_update_time = time()
        partial_hash, int_target = getwork()
      if not nonce%next_level:
        next_level*=2
        print("Nonce reached %d"%nonce)
    final_time = time()
    if update_block:
      print("Hashrate %d H/s"%(int(nonce/(final_time-initial_time))))
      continue
    print("Get solution. Nonce = %d. Hashrate %d H/s"%(nonce, int(nonce/(final_time-initial_time))))
    hex_nonce = "0x"+(nonce+basic_nonce).to_bytes(16, "big").hex()
    partial_hash_hex = "0x"+partial_hash.hex()
    res = basic_request('submitwork', [hex_nonce, partial_hash_hex, "0x"+"00"*32])
    print("Submitted block. Result %s"%res)

if __name__ == '__main__':
  while True:
    try:
      start_mining()
    except Exception as e:
      print("Error occured %s"%(str(e)))
      sleep(2)
