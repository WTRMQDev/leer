import asyncio
import logging
import time


from secp256k1_zkp import PrivateKey, PublicKey

from .node import Node
from lnoise import Key
logger = logging.getLogger(__name__)
from .messages import message_id, inv_message_id
from uuid import uuid4


class NetworkManager:
  def __init__(self, loop, syncer, config):
    self.loop = loop
    self.config = config 
    self.syncer = syncer
    self.global_message_queue = syncer.queues['NetworkManager']
    self.load_from_disc()
    #for node in self.nodes.values():
    #  self.connect_to(node)
    self.loop.call_soon(self.check_global_message_queue)
    self.nodes={}
    self.reconnect_list = {}
    self.server = asyncio.start_server(self.handle_connection, config['p2p']['host'], config['p2p']['port'], loop=loop)
    self.tasks = []
    self.up = True
    asyncio.ensure_future(self.server, loop=loop)
    asyncio.ensure_future(self.reconnect_loop(), loop=loop)

  def load_from_disc(self):
    lspriv=self.config['p2p']['lspriv']
    s=Key(key=PrivateKey(lspriv.to_bytes(32,'big'), raw=True))
    our_node_params = { 'network': {'host': self.config['p2p']['host'], 'port':self.config['p2p']['port']}, 'static_full_key':s}
    self.our_node = Node(None, our_node_params, self.loop, None)
    #other = { 'network': {'IP':None, 'port':None}, 'lightning':{'id':None, 'static_key':Key().pubkey()}}
    self.nodes={}

  def save_to_disc(self):
    pass #TODO

  async def connect_to(self, host_port_tuple, static_key=None):
    if not host_port_tuple in self.nodes:
      if not static_key:
        raise Exception("Cannot connect to new node without static key")
      host, port = host_port_tuple
      new_node_params = { 'network': {'host':host, 'port':port}, 'static_key':static_key}
      node = Node(self.our_node, new_node_params, self.loop, self.handle_message)
      await node.connect()

  async def handle_connection(self, reader, writer):
    extra_info = writer.get_extra_info('peername')
    host, port = extra_info[:2]
    print("New connection from %s %s"%(str(host), str(port)))
    params = {'network':{'host':host, 'port':port}}
    new_node = Node(self.our_node, params, self.loop, self.handle_message)
    await new_node.accept_connection(reader, writer)

  async def handle_message(self, node, _type, message):

    if _type == "close": # TODO explanation that message can be thrown by Node-object itself in on_disconnect
      if message[0] == 0:
        if (node.host, node.port) in self.nodes:
          self.nodes.pop((node.host, node.port))
        #accidental disconnet, set to reconnect
        node_params = (node.advertised_host, node.advertised_port)
        if not node_params in self.reconnect_list:
          if node.advertised_static_key: #we can't reconnect without static key
            self.reconnect_list[node_params] = {'static_key':node.advertised_static_key, 'last_try_time':time.time(), 'try':0}
        else:
          self.reconnect_list[node_params]['last_try_time']=time.time()
          self.reconnect_list[node_params]['try']+=1 
        if node_params in self.nodes:
          self.nodes.pop(node_params)

    if _type == "init":
      node.deserialize_params(message, remote=True)
      self.nodes[(node.host, node.port)]=node 
      if (node.advertised_host, node.advertised_port) in self.reconnect_list:
        self.reconnect_list.pop((node.advertised_host, node.advertised_port))
        #XXX possible attack here: if attacker want to exclude node (segment)
        # from network (s)he DDoS this node, and then reconnect to all other
        # nodes atacked node was connected. If (s)he will will advertise attacked
        # node host and port as it's own, disconnected nodes will not try to
        # reconnect. At the same time if attacker simulate multiple connections
        # to attacked node from previously connected nodes(again advertising fake
        # host and port), attacked node will not try to reconnect to disconnected
        # nodes either. It is difficult attack, which requires enormous DDoS
        # abilities, knowing of network topology, absence of fresh coming nodes.
        # Nevertheless this issue should be revisited

    if _type == "give nodes":
      node_list_to_send = []
      for k,v in self.nodes.items():
        if not v==node: 
          node_list_to_send.append(v.serialize_params())
      message = b"\x00\04"+len(node_list_to_send).to_bytes(2, "big") #TODO move byte operation unde node interface
      for node_to_send in node_list_to_send:
        message += len(node_to_send).to_bytes(2, "big") + node_to_send
      await node.send(message) 

    if _type == "take nodes":
      try:
        node_list_len, r = message[:2], message[2:]
        node_list_len = int.from_bytes(node_list_len, "big")
        nodes=[]

        local_in_connection=[]
        try:
          # Node appears in known_nodes only after `init` message
          # So if information about node will reach us multiple times before
          # first successfull connection, we will try to connect to it multiple times
          # self.in_connection is used to prohibit such behavior
          self.in_connection
        except:
          self.in_connection = []

        for i in range(node_list_len):
          _node_len, r = r[:2], r[2:]
          _node_len = int.from_bytes(_node_len, "big")
          _node, r =  r[:_node_len], r[_node_len:]
          new_node = Node(self.our_node, None, self.loop, self.handle_message, serialized_params=_node)
          #nodes.append(new_node.connect())
          if not (new_node.host, new_node.port) in self.get_known_nodes():
            if not (new_node.host, new_node.port) in self.in_connection: 
              if not (new_node.host, new_node.port) == (self.our_node.host, self.our_node.port):
                if not new_node.static_key.serialize() == self.our_node.static_key.serialize(): # mirror replay
                  #await new_node.connect()
                  task = new_node.connect()
                  nodes.append(task)
                  self.in_connection.append((new_node.host, new_node.port))
                  local_in_connection.append((new_node.host, new_node.port))
        if len(nodes):     
          await asyncio.wait(nodes)
          for _node in local_in_connection:
            self.in_connection.remove(_node)
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "give next headers":
      try:
        _ser_num, from_hash = message[:2], message[2:32+2]
        num = int.from_bytes(_ser_num,"big")
        self.syncer.queues["Blockchain"].put({'action': "give next headers",
                                              'id':str(uuid4()), "num": num, 
                                              "from": bytes(from_hash), "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "take the headers":
      try:
        _ser_num, headers = message[:2], message[2:]
        num = int.from_bytes(_ser_num,"big")
        self.syncer.queues["Blockchain"].put({'action': 'take the headers',
                                              'id':str(uuid4()), "num": num, 
                                              "headers": bytes(headers), "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "give blocks":
      try:
        _ser_num, block_hashes = message[:2], message[2:]
        num = int.from_bytes(_ser_num,"big")
        self.syncer.queues["Blockchain"].put({'action': 'give blocks',
                                              'id':str(uuid4()), "num": num, 
                                              "block_hashes": bytes(block_hashes), "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "take the blocks":
      try:
        _ser_num, blocks = message[:2], message[2:]
        num = int.from_bytes(_ser_num,"big")
        self.syncer.queues["Blockchain"].put({'action': 'take the blocks',
                                              'id':str(uuid4()), "num": num, 
                                              "blocks": bytes(blocks), "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "give the txos":
      try:
        _ser_num, txos_hashes = message[:2], message[2:]
        num = int.from_bytes(_ser_num,"big")
        self.syncer.queues["Blockchain"].put({'action': 'give txos',
                                              'id':str(uuid4()), "num": num, 
                                              "txos_hashes": bytes(txos_hashes), "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "take the txos":
      try:
        _ser_num, message = message[:2], message[2:]
        num = int.from_bytes(_ser_num,"big")
        txos_hashes, txos_lengths, txos = message[:num*65], message[num*65:num*65+num*2], message[num*65+num*2:] 
        self.syncer.queues["Blockchain"].put({'action': 'take the txos',
                                              'id':str(uuid4()), "num": num, 
                                              "txos_hashes": bytes(txos_hashes), "txos_lengths": bytes(txos_lengths),
                                              "txos": bytes(txos), "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection


    if _type == "take tip info":
      try:
        _ser_height, message = message[:4], message[4:]
        tip, prev_hash, message = message[:32], message[32:64], message[64:]
        _ser_td = message[:32]
        height, total_difficulty = int.from_bytes(_ser_height, "big"), int.from_bytes(_ser_td, "big"), 
        self.syncer.queues["Blockchain"].put({'action': 'take tip info',
                                              'id':str(uuid4()), "height": height, "prev_hash": bytes(prev_hash),
                                              "tip":bytes(tip), "total_difficulty":total_difficulty, "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "find common root":
      try:
        self.syncer.queues["Blockchain"].put({'action': 'find common root',
                                              'id':str(uuid4()), "serialized_header": bytes(message),
                                              "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "find common root response":
      try:
        header_hash, serialized_len, message = message[:32], message[32:33], message[33:]
        _len = int.from_bytes(serialized_len, "big") # SHouldn't we just use message[32] ?
        known_headers = message[:_len]
        self.syncer.queues["Blockchain"].put({'action': 'find common root response',
                                              'id':str(uuid4()), "header_hash": bytes(header_hash),
                                              'flags_num':_len, "known_headers": bytes(known_headers),
                                              "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "take TBM transaction":
      try:
        serialized_mode, serialized_sceleton = message[:2], message[2:]
        self.syncer.queues["Blockchain"].put({'action': 'take TBM transaction',
                                              'id':str(uuid4()), "tx_scel": bytes(serialized_sceleton),
                                              "mode": int.from_bytes(serialized_mode, "big"),
                                              "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection

    if _type == "give TBM transaction":
      try:
        self.syncer.queues["Blockchain"].put({'action': 'give TBM transaction',
                                              "node":(node.host, node.port), 'sender':"NetworkManager"})
      except Exception as e:
        print("exception nm", e)
        pass #TODO DoS protection





  def get_known_nodes(self):
    nodes = [(node.advertised_host,node.advertised_port) for k,node in self.nodes.items()]
    nodes = nodes+list(self.nodes)
    return set(nodes)
    

  def check_global_message_queue(self):
      while not self.global_message_queue.empty():
          message = self.global_message_queue.get()
          action = message['action']
          if action == "open connection":
              host, port, static_key = message['host'], message['port'], PublicKey(message['static_key'], raw=True)
              coro = self.connect_to( (host, port), static_key=static_key)
              asyncio.ensure_future(coro, loop=self.loop)
          if action == "get connections num":
              _id = message['id']
              request_source = message['sender'] 
              self.syncer.queues[request_source].put({'id':_id, 'result':len(self.nodes)})

          if action == "give nodes list":
              _id = message['id']
              request_source = message['sender'] 
              self.syncer.queues[request_source].put({'id':_id, 'result':list(self.nodes.keys())})

          if action == "take the headers":
            num, headers, node_params = message["num"], message["headers"], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["take the headers"]
            message_to_send += num.to_bytes(2,"big")
            message_to_send += headers
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "take the blocks":
            num, blocks, node_params = message["num"], message["blocks"], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["take the blocks"]
            message_to_send += num.to_bytes(2,"big")
            message_to_send += blocks
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "take the txos":
            num, txos, txos_hashes, txos_lengths, node_params = message["num"], message["txos"], message["txos_hashes"], message["txos_lengths"], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["take the txos"]
            message_to_send += num.to_bytes(2,"big")
            message_to_send += txos_hashes
            message_to_send += txos_lengths
            message_to_send += txos
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "give blocks":
            num, blocks_hashes, node_params = message["num"], message["block_hashes"], message["node"]
            if not node_params in self.nodes:
              continue   
            message_to_send = inv_message_id["give blocks"]
            message_to_send += num.to_bytes(2,"big")
            message_to_send += blocks_hashes
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "give next headers":
            num, from_hash, node_params = message["num"], message["from"], message["node"]
            if not node_params in self.nodes:
              continue   
            message_to_send = inv_message_id["give next headers"]
            message_to_send += num.to_bytes(2,"big")
            message_to_send += from_hash
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "give txos":
            num, txos_hashes, node_params = message["num"], message["txos_hashes"], message["node"]
            if not node_params in self.nodes:
              continue   
            message_to_send = inv_message_id["give the txos"]
            message_to_send += num.to_bytes(2,"big")
            message_to_send += txos_hashes
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)            
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "take tip info":
            logger.info("Take tip info")
            height, tip, prev_hash, total_difficulty, node_params = message["height"], message["tip"], message["prev_hash"], message["total_difficulty"], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["take tip info"]
            message_to_send += height.to_bytes(4,"big")
            message_to_send += tip
            message_to_send += prev_hash
            message_to_send += total_difficulty.to_bytes(32,"big")
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "find common root":
            serialized_header, node_params = message["serialized_header"], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["find common root"]
            message_to_send += serialized_header
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)            
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})
          if action == "find common root response":
            header_hash, known_headers, _len, node_params = message["header_hash"], message["known_headers"], message['flags_num'], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["find common root response"]
            message_to_send += header_hash
            message_to_send += _len.to_bytes(1,"big")
            message_to_send += known_headers
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)            
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})

          if action == "take TBM transaction":
            mode, serialized_tx_scel, node_params = message["mode"], message["tx_scel"], message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["take TBM transaction"]
            message_to_send += mode.to_bytes(2,"big")
            message_to_send += serialized_tx_scel
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)            
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})

          if action == "give TBM transaction":
            node_params = message["node"]
            if not node_params in self.nodes:
              continue
            message_to_send = inv_message_id["give TBM transaction"]
            coro = self.nodes[node_params].send(message_to_send)
            asyncio.ensure_future(coro, loop=self.loop)            
            self.syncer.queues[message['sender']].put({'id':message['id'], 'result':'processed'})

          '''if action == "send ping":
              for node in self.nodes:
                coro = node.send( "ping 0")
                asyncio.ensure_future(coro, loop=self.loop)'''
      if self.up:
        self.loop.call_later(0.5, self.check_global_message_queue)
    
  async def reconnect_loop(self):
    def try_num_to_delay(try_num):
      return 2#TODO for tests
      if try_num==0:
        return 0
      delay = 300*(2**try_num)
      if delay > 6*3600:
        delay = 6*3600
      return delay
    while self.up:
      for node_params in self.reconnect_list:
        ltt = self.reconnect_list[node_params]['last_try_time']
        t = self.reconnect_list[node_params]['try']
        if time.time()>ltt+try_num_to_delay(t):
          asyncio.ensure_future(self.connect_to( node_params, static_key=self.reconnect_list[node_params]['static_key']))
      await asyncio.sleep(5)



def NM_launcher(syncer, config):
  loop = asyncio.new_event_loop()
  asyncio.set_event_loop(loop)
  NM = NetworkManager(loop, syncer, config)
  loop.run_forever()
  

