import asyncio
import logging
import sys
from asyncio import CancelledError

from secp256k1_zkp import PrivateKey, PublicKey

from lnoise import Key, HandshakeState, PartialData
from .messages import inv_message_id
from leer.version import NETSTATUS, CODENAME, VERSION

async def tripple_read(r):
    message = await r(65536)
    if not len(message):
      message = await r(65536)
    if not len(message):
      message = await r(65536)
    return message


class NetworkNode:
  def __init__(self, our_node, params, loop, serialized_params=None):
    if serialized_params:
      params = self.deserialize_params(serialized_params)
    self.host = params['network']['host']
    self.port = params['network']['port']
    self.advertised_host = params['network'].get('advertised_host', self.host)
    self.advertised_port = params['network'].get('advertised_port', self.port)
    self.static_key = params.get('static_key', None)
    self.advertised_static_key = params.get('advertised_static_key', self.static_key)
    self.static_full_key = params.get('static_full_key', None) #This option is only for our node
    if self.static_full_key and not self.static_key:
      self.static_key = self.static_full_key.key.pubkey
    self.ephemeral_key = Key() #generating new key on the fly
    self.our_node = our_node
    self.loop = loop
    self.listening_loop_task = None
    self.connected= False
    self.reader, self.writer = None, None
    self.handshake=HandshakeState()
    if self.our_node:
      self.logger=logging.getLogger(__name__+" Node(%s,%s from (%s))"%(str(self.host),str(self.port),str(self.our_node.port)))
    else:
      self.logger=logging.getLogger(__name__+" Node(%s,%s our_node)"%(str(self.host),str(self.port)))
      self.version = " ".join([NETSTATUS, VERSION, CODENAME ])
    self.partial_data = None

  def serialize_params(self):
    ser_host = str(self.advertised_host).encode("utf-8")
    ser_port = str(self.advertised_port).encode("utf-8")
    ser_static_key = self.static_key.serialize()
    result = b""
    result += len(ser_host).to_bytes(1, "big") + ser_host +\
              len(ser_port).to_bytes(1, "big") + ser_port +\
              len(ser_static_key).to_bytes(1, "big") + ser_static_key
    if not self.version:
      return result
    ser_version = self.version.encode("utf-8")
    if len(ser_version)>255:
     ser_version = ser_version[:255]
    result += len(ser_version).to_bytes(1,"big") + ser_version
    return result

  def deserialize_params(self, serialized_params, remote=False):
    try:
      len_ser_host, r = serialized_params[0], serialized_params[1:]
      ser_host, r = r[0:len_ser_host], r[len_ser_host:]
      len_ser_port, r = r[0], r[1:]
      ser_port, r = r[0:len_ser_port], r[len_ser_port:]
      len_ser_key, r = r[0], r[1:]
      ser_key, r = r[0:len_ser_key], r[len_ser_key:]
      ser_version = None
      if len(r): #Version is optional
        len_ser_version, r = r[0], r[1:]
        ser_version, r = r[0:len_ser_version], r[len_ser_version:]
    except:
      raise Exception("Incorrect serialized params") #TODO handle exceptions more precisely
    if remote:
      self.advertised_host = ser_host.decode('utf-8')
      self.advertised_port = int(ser_port.decode('utf-8')) # TODO try-except here
      self.advertised_static_key = PublicKey(bytes(ser_key), raw=True)
      try:
        self.version = ser_version.decode('utf8')
      except (AttributeError, UnicodeDecodeError) as e:
        self.version = 'unknown'
    else:
      return {'network':{'host':ser_host.decode('utf-8'), 'port':int(ser_port.decode('utf-8'))}, 'static_key':PublicKey(bytes(ser_key), raw=True)}

  async def connect(self):
    '''
      Note: to open connection we already should know remote static key 
    '''
    self.logger.debug("Trying to connect")
    if self.connected:
      raise
    try:
      self.reader, self.writer = await asyncio.open_connection(self.host, self.port, loop=self.loop)
    except (ConnectionRefusedError,TimeoutError, OSError) as e:
      # TODO somehow instead of ConnectionRefused, OSError(Multiple exceptions) happens
      # should be cleared
      self.logger.info("Node (%s:%s) is not reachable `%s`"%(self.host, self.port, str(e)))
      self._on_closed_connection()
      return
    except Exception as e:
      self._on_closed_connection(error=e)
      return
    self.handshake.initialize('Noise_XK', prologue=b'leer', s=self.our_node.static_full_key, e=self.our_node.ephemeral_key, rs=self.static_key, re=None, initiator=True)
    try:
      await self.do_handshake()
    except Exception as e:
      exc_type, exc_value, exc_traceback = sys.exc_info()
      self.logger.info("Close connection due to error in handshake `%s`"%(str(e)), exc_info=True)
      self._on_closed_connection(error=e)
    

  async def accept_connection(self, reader, writer):
    if self.connected:
      raise
    self.logger.debug("Trying to accept connection")
    self.reader, self.writer = reader, writer
    if self.reader.at_eof():
      return
    self.handshake.initialize('Noise_XK', prologue=b'leer', s=self.our_node.static_full_key, e=self.our_node.ephemeral_key, rs=None, re=None, initiator=False)
    #self.connected = True
    try:
      await self.do_handshake()
    except Exception as e:
      exc_type, exc_value, exc_traceback = sys.exc_info()
      self.logger.info("Close connection due to error in handshake `%s`"%(str(e)), exc_info=True)
      self._on_closed_connection(error=e)

  async def do_handshake(self):
    if not self.handshake.state in [self.handshake.STATES.WAITING_TO_WRITE, self.handshake.STATES.WAITING_TO_READ]:#wait to read or write
      raise
    elif self.handshake.state==self.handshake.STATES.WAITING_TO_WRITE:
        message = self.handshake.write_message(b"")
        self.writer.write(message)
        await self.writer.drain()
    elif self.handshake.state==self.handshake.STATES.WAITING_TO_READ:
        mb=[]
        message = await tripple_read(self.reader.read)
        self.handshake.read_message(message, [])
    if not self.handshake.state==self.handshake.STATES.ESTABLISHED:
      await self.do_handshake()
    else:
      self.static_key = self.handshake.rs
      self.advertised_static_key = self.static_key #can be overwritten by `init` message
      self.listening_loop_task = asyncio.ensure_future(self.listening_loop())
      asyncio.ensure_future(self.on_established_connection())
      self.connected = True

  async def listening_loop(self):
    try:
      while self.connected:
        if not self.handshake.state==self.handshake.STATES.ESTABLISHED:
            await asyncio.sleep(1)
            continue
        data = await self.reader.read(65536) 
        if (not data) or self.writer.transport.is_closing():
          self._on_closed_connection()
          break
        else:
            try:
                data = self.partial_data + data if self.partial_data else data              
                self.partial_data = None
                while len(data):
                  message, data = self.handshake.session.decode(data)
                  if message in [inv_message_id["ping"], inv_message_id["pong"]]:
                    self.logger.debug("Got message %s"%(str(message)))
                  else:
                    if len(message)<24:
                      self.logger.info("Got message %s"%(str(message)))
                    else:
                      self.logger.info("Got message with len %d"%(len(message)))
                      self.logger.debug("Message content %s"%(str(message)))
                  result = await self.handle_message(message)
            except PartialData:
              self.partial_data=data
            except CancelledError:
              return
            except Exception as e:
                self._on_closed_connection(error=e)
    except CancelledError:
      pass

  async def send(self,message):
    try:
      message = message
      while not (self.handshake.state==self.handshake.STATES.ESTABLISHED):
        await asyncio.sleep(1)
      while self.writer._protocol._drain_waiter:
        await asyncio.sleep(0.03) #wait for previous send to complete
      encoded_message = self.handshake.session.encode(message)
      self.writer._transport.set_write_buffer_limits(high=0)
      self.writer.write(encoded_message)
      await self.writer.drain()
    except ConnectionResetError as e:
      self._on_closed_connection(error=e)
      return False
    except Exception as e:
      self.logger.info("Exception during send")
      self._on_closed_connection(error=e)
      return False
    return True

  async def on_established_connection(self):
    '''
      This method is expected to be overwritten by subclass
    '''
    pass

  def _on_closed_connection(self, error=None):
    self.connected = False
    if not error:
      self.logger.info("Connection is closed, stop listening_loop")
    else:
      self.logger.info("Close connection due to error: `%s`"%(str(error)))
    if self.listening_loop_task:
      self.listening_loop_task.cancel()
    if self.writer:
      if not self.writer.transport.is_closing():
        self.writer.close()
    self.handshake=HandshakeState()
    asyncio.ensure_future(self.on_closed_connection())

  async def on_closed_connection(self):
    '''
      This method is expected to be overwritten by subclass
    '''
    pass

  async def handle_message(self, message):
    '''
      This method is expected to be overwritten by subclass
    '''
    pass
