from collections import OrderedDict

from leer.core.lubbadubdub.constants import default_generator, default_generator_ser, generators, GLOBAL_TEST
from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Excess
from leer.core.parameters.constants import output_creation_fee


class TransactionSkeleton:
  def __init__(self, tx=None):
    self.input_indexes = [] 
    self.output_indexes = []
    self.output_relay_fees = []
    self.additional_excesses = []
    self.updated_excesses = {}
    self.combined_excesses = OrderedDict()
    self.mixer_offset = 0
    self.tx = tx
    if tx:
      for _i in tx.inputs:
        self.input_indexes.append(_i.serialized_index)
      for _o in tx.outputs:
        self.output_indexes.append(_o.serialized_index)
        self.output_relay_fees.append(_o.relay_fee)
      self.additional_excesses = tx.additional_excesses.copy()
      self.updated_excesses = tx.updated_excesses.copy()
      self.mixer_offset = tx.mixer_offset
      
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented

  def serialize(self, rich_format=False, max_size =40000, full_tx = None):
    #TODO we messed up a lot here with storage-space-free skeletons
    # Basically idea was that tx_skeleton is independent from storage_space, however in this case
    # we cannot serialize in rich format: outputs are stored only in storage_space. Moreover tx_skel
    # with all outputs actually contains the same info as tx. Now tx_skel needs space only if we want 
    # to serialize in rich_format, but since we cannot import build_tx_from_skeleton (cyclic import)
    # we pass full_tx into tx_skel.serialize . Probably the whole concept of 
    # transaction/transaction_skeleton should be reconsidered. 
    full_tx = full_tx if full_tx else self.tx
    if rich_format and not full_tx:
      raise Exception("Full_tx is required for serialization in rich format")
    serialization_array = []
    version = 1
    version_byte = ((version<<1)+int(rich_format)).to_bytes(1,"big") #lowest bit sets rich/not_rich format. Other bits are used for version
    serialization_array.append(version_byte)
    serialization_array.append(len(self.input_indexes).to_bytes(2, "big"))
    serialization_array.append(len(self.output_indexes).to_bytes(2, "big"))
    serialization_array.append(len(self.additional_excesses).to_bytes(2, "big"))
    serialization_array+=(self.input_indexes)
    serialization_array+=(self.output_indexes)
    serialization_array+=[i.to_bytes(4, "big") for i in self.output_relay_fees]
    serialization_array+=([ e.serialize() for e in self.additional_excesses])
    serialization_array+=([ self.updated_excesses[i].serialize() for i in self.input_indexes])
    serialization_array+=[self.mixer_offset.to_bytes(32,"big")]
    tx_skel_size = sum([len(i) for i in serialization_array])
    if rich_format and tx_skel_size<max_size:
      #we start with coinbase, because receiver definetely doesn't have this data
      txouts_data = b""
      txouts_count = 0
      tx = full_tx
      if tx.coinbase:
        serialized_coinbase = tx.coinbase.serialize()
        if len(serialized_coinbase)+tx_skel_size<max_size-2:
          txouts_data += serialized_coinbase
          txouts_count +=1
      for _o in tx.outputs:
          if _o.is_coinbase:
            continue
          serialized_output = _o.serialize()
          if tx_skel_size+len(txouts_data)+len(serialized_output)<max_size-2:
            txouts_data += serialized_output
            txouts_count +=1
          else:
            break
      if not txouts_count:
        #we don't have enough space even for one output
        serialization_array[0] = (version<<1).to_bytes(1,"big")
      else:
        serialization_array.append(txouts_count.to_bytes(2,"big"))
        serialization_array.append(txouts_data)

    return b"".join(serialization_array)

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)
      

  def deserialize_raw(self, serialized, storage_space=None):
    if len(serialized)<1:
      raise Exception("Not enough bytes for tx skeleton version marker")
    serialized, ser_version = serialized[1:], serialized[0]
    rich_format = ser_version & 1
    version = ser_version >> 1
    if not version in [0,1]:
      raise Exception("Unknown tx_sceleton version")
    if len(serialized)<2:
      raise Exception("Not enough bytes for tx skeleton inputs len")
    serialized, _len_i = serialized[2:], int.from_bytes(serialized[:2], "big")
    if len(serialized)<2:
      raise Exception("Not enough bytes for tx skeleton outputs len")
    serialized, _len_o = serialized[2:], int.from_bytes(serialized[:2], "big")

    if len(serialized)<2:
      raise Exception("Not enough bytes for tx skeleton additional excesses len")
    serialized, _len_ae = serialized[2:], int.from_bytes(serialized[:2], "big")

    serialized_index_len = IOput().index_len
    for i in range(_len_i):
      if len(serialized)<serialized_index_len:
        raise Exception("Not enough bytes for tx skeleton' input index %d len"%i)
      _input_index, serialized  = serialized[:serialized_index_len], serialized[serialized_index_len:]
      self.input_indexes.append(_input_index)
    for i in range(_len_o):
      if len(serialized)<serialized_index_len:
        raise Exception("Not enough bytes for tx skeleton' output index %d len"%i)
      _output_index, serialized  = serialized[:serialized_index_len], serialized[serialized_index_len:]
      self.output_indexes.append(_output_index)

    if version>=1:
      for i in range(_len_o):
        if len(serialized)<4:
          raise Exception("Not enough bytes for tx skeleton' output relay fee %d len"%i)
        ser_relay_fee, serialized  = serialized[:4], serialized[4:]
        self.output_relay_fees.append(int.from_bytes(ser_relay_fee, "big"))

    for i in range(_len_ae):
      e = Excess()
      serialized  = e.deserialize_raw(serialized)
      self.additional_excesses.append(e)
    for i in range(_len_i):
      e = Excess()
      serialized  = e.deserialize_raw(serialized)
      self.updated_excesses[self.input_indexes[i]]=e
    if len(serialized)<32:
      raise Exception("Not enough bytes for mixer offset")
    self.mixer_offset, serialized = int.from_bytes(serialized[:32], "big"), serialized[32:]

    if not self.verify():
      #TODO consider renmaing verify to validate_excesses or make exception text more general
      raise Exception("Additional excesses are not signed properly")

    if rich_format and storage_space:
      txouts_num_serialized, serialized = serialized[:2], serialized[2:]
      txouts_num = int.from_bytes(txouts_num_serialized, "big")
      for _ in range(txouts_num):
        output = IOput()
        serialized = output.deserialize_raw(serialized)
        if not (output.serialized_index in self.output_indexes):
          raise Exception("Unknown output in rich txskel data") 
        storage_space.txos_storage.mempool[output.serialized_index]=output


    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented
    return serialized

  def verify(self):
    '''
      Additional excess should sign one of output apc.
      Each output can be signed only once.
    '''
    output_apcs = []
    for _o in self.output_indexes:
      output_apcs.append(_o[:33])
    for _e in self.additional_excesses:
      pass
      #if not _e.message in output_apcs:
      #  return False
      #else:
      #  output_apcs.remove(_e.message)
    return True

  def calc_new_outputs_fee(self, is_block_transaction):
    return ( len(self.output_indexes) - len(self.input_indexes) - int(bool(is_block_transaction)) )*output_creation_fee

  @property
  def relay_fee(self):
    return sum(self.output_relay_fees)

  def __eq__(self, another_one):
    return self.serialize() == another_one.serialize()

