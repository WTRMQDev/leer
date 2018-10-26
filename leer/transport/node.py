import logging
import asyncio
import random

from concurrent.futures import CancelledError

from .network_node import NetworkNode
from .messages import message_id, inv_message_id

class Node(NetworkNode):
  def __init__(self, our_node, params, loop, message_handler, serialized_params=None):
    NetworkNode.__init__(self, our_node, params, loop, serialized_params=serialized_params);
    self.message_handler = message_handler
    self.ping_loop_task = None

  async def on_established_connection(self):
    self.logger.info("Connection is established")
    print("Connection with %s:%s is established"%(self.host, self.port))
    await self.send(inv_message_id["init"] + self.our_node.serialize_params())
    await asyncio.sleep(0.2)
    await self.send(inv_message_id["give nodes"])
    self.ping_loop_task = asyncio.ensure_future(self.ping_loop())

  async def on_closed_connection(self):
    await self.message_handler(self,'close', b'\x00')
    if self.ping_loop_task:
      self.ping_loop_task.cancel()

  async def ping_loop(self):
    try:
      if self.connected:
        await self.send(inv_message_id["ping"])
        await asyncio.sleep(random.randint(5, 10)) #TODO should check pong here?
        asyncio.ensure_future(self.ping_loop())
    except CancelledError:
      pass

  async def handle_message(self,message):
    if len(message)<2:
      pass #TODO DoS protection
    _id,message = bytes(message[:2]), message[2:]
    if not _id in message_id:
      pass #TODO DoS protection
    _type = message_id[_id]
    if _type == "ping":
      await self.send(inv_message_id["pong"])
    if _type == "pong":
      pass
    else:
      await self.message_handler(self,_type, message)

  def __repr__(self):
    return "<Node %s:%s  adv %s:%s>"%(self.host,self.port, self.advertised_host, self.advertised_port)
