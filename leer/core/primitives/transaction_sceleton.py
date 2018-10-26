from collections import OrderedDict

from leer.core.lubbadubdub.constants import default_generator, default_generator_ser, generators, GLOBAL_TEST
from leer.core.lubbadubdub.ioput import IOput
from leer.core.lubbadubdub.address import Excess
from leer.core.parameters.constants import output_creation_fee


class TransactionSceleton:
  def __init__(self, tx=None):
    self.input_indexes = [] 
    self.output_indexes = []
    self.additional_excesses = []
    self.combined_excesses = OrderedDict()
    self.tx = tx
    if tx:
      for _i in tx.inputs:
        self.input_indexes.append(_i.serialized_index)
      for _o in tx.outputs:
        self.output_indexes.append(_o.serialized_index)
      self.additional_excesses = tx.additional_excesses.copy()
    if not GLOBAL_TEST['skip combined excesses']:
      raise NotImplemented

  def serialize(self, rich_format=False, max_size =40000, full_tx = None):
    #TODO we messed up a lot here with storage-space-free sceletons
    # Basically idea was that tx_sceleton is independent from storage_space, however in this case
    # we cannot serialize in rich format: outputs are stored only in storage_space. Moreover tx_scel
    # with all outputs actually contain the same info as tx. Now tx_scel need space only if we want 
    # serialize in rich_format, but since we cannot import build_tx_from_sceleton (cyclic import)
    # we pass full_tx into tx_scel.serialize . Probably whole concept of transaction/transaction_sceleton
    # should be reconsidered. 
    full_tx = full_tx if full_tx else self.tx
    if rich_format and not full_tx:
      raise Exception("Full_tx is required for serialization in rich format")
    serialization_array = [ {True:b"\x01", False:b"\x00"}[rich_format] ]
    serialization_array.append(len(self.input_indexes).to_bytes(2, "big"))
    serialization_array.append(len(self.output_indexes).to_bytes(2, "big"))
    serialization_array.append(len(self.additional_excesses).to_bytes(2, "big"))
    serialization_array+=(self.input_indexes)
    serialization_array+=(self.output_indexes)
    serialization_array+=([ e.serialize() for e in self.additional_excesses])
    tx_scel_size = sum([len(i) for i in serialization_array])
    if rich_format and tx_scel_size<max_size:
      #we start with coinbase, because receiver definetely hasn't this data
      txouts_data = b""
      txouts_count = 0
      tx = full_tx
      if tx.coinbase:
        serialized_coinbase = tx.coinbase.serialize()
        if len(serialized_coinbase)+tx_scel_size<max_size-2:
          txouts_data += serialized_coinbase
          txouts_count +=1
      for _o in tx.outputs:
          if _o.is_coinbase:
            continue
          serialized_output = _o.serialize()
          if tx_scel_size+len(txouts_data)+len(serialized_output)<max_size-2:
            txouts_data += serialized_output
            txouts_count +=1
          else:
            break
      if not txouts_count:
        #we havent enough space even for one output
        serialization_array[0] = b"\x00"
      else:
        serialization_array.append(txouts_count.to_bytes(2,"big"))
        serialization_array.append(txouts_data)

    return b"".join(serialization_array)

  def deserialize(self, serialized):
    self.deserialize_raw(serialized)
      

  def deserialize_raw(self, serialized, storage_space=None):
    if len(serialized)<1:
      raise Exception("Not enough bytes for tx sceleton rich format marker")
    serialized, rich_format = serialized[1:], bool(serialized[0])
    if len(serialized)<2:
      raise Exception("Not enough bytes for tx sceleton inputs len")
    serialized, _len_i = serialized[2:], int.from_bytes(serialized[:2], "big")
    if len(serialized)<2:
      raise Exception("Not enough bytes for tx sceleton outputs len")
    serialized, _len_o = serialized[2:], int.from_bytes(serialized[:2], "big")

    if len(serialized)<2:
      raise Exception("Not enough bytes for tx sceleton additional excesses len")
    serialized, _len_ae = serialized[2:], int.from_bytes(serialized[:2], "big")

    serialized_index_len = IOput().index_len
    for i in range(_len_i):
      if len(serialized)<serialized_index_len:
        raise Exception("Not enough bytes for tx sceleton' input index %d len"%i)
      _input_index, serialized  = serialized[:serialized_index_len], serialized[serialized_index_len:]
      self.input_indexes.append(_input_index)
    for i in range(_len_o):
      if len(serialized)<serialized_index_len:
        raise Exception("Not enough bytes for tx sceleton' output index %d len"%i)
      _output_index, serialized  = serialized[:serialized_index_len], serialized[serialized_index_len:]
      self.output_indexes.append(_output_index)

    for i in range(_len_ae):
      e = Excess()
      serialized  = e.deserialize_raw(serialized)
      self.additional_excesses.append(e)

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
          raise Exception("Unknown output in rich txscel data") 
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
      if not _e.message in output_apcs:
        return False
      else:
        output_apcs.remove(_e.message)
    return True

  def calc_new_outputs_fee(self, is_block_transaction):
    return ( len(self.output_indexes) - len(self.input_indexes) - int(bool(is_block_transaction)) )*output_creation_fee


  def __eq__(self, another_one):
    return self.serialize() == another_one.serialize()

