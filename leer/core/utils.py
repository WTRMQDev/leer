class DOSException(Exception):
  pass

def encode_target(target):
    for order in range(255,1,-1):
      if target//(2**order):
        break
    order=order
    significand = float(target)/(2**order)-1 # 1 is hidden bit
    significand = int(significand*256)
    if significand >= 256:
      significand = 255
    return significand, order

def decode_target(significand, order):
  target = int((1+significand/256.)*(2**order))
  if target>=2**256:
    target = 2**256-1 
  return target
    



def test_encode_decode():
  import random
  for i in range(10000):
    target = random.randint(0,2**256-1)
    d_e_target = decode_target(*encode_target( target) )
    diff = abs( float(d_e_target)/target -1)
    if diff>1/256.:
      print(target, diff, diff*256)


from time import time

class ObliviousDictionary:
  '''
    Oblivious Dictionary works as usual dictionary but forgets items after sink_delay.
    Note: erasing obsolete items happens only during touchin ObliviousDictionary object.
  '''
  def __init__(self, sink_delay):
    self.sink_delay = sink_delay
    self.inner_dict = {}
    self.trigger_time_list = [] #Should be sorted

  def __getitem__(self, _index):
    self.__check_trigers()
    return self.inner_dict[_index]

  def __setitem__(self, _index, _object):
    self.__check_trigers()
    self.inner_dict[_index]=_object
    self.trigger_time_list.append((time()+self.sink_delay, _index))

  def __contains__(self, _index): 
    #TODO This method probably should be deleted, we easily get to situation, 
    # when we checked that smth is in dict, but when we try to get it, it's gone
    # better sorry than ask
    return _index in self.inner_dict

  def __len__(self):
    self.__check_trigers()
    return len(self.inner_dict)

  def __check_trigers(self):
    now = time()
    n=0
    for tm, key in self.trigger_time_list:
      if tm<now:
        self.inner_dict.pop(key)
        n+=1
      else:
         break #trigger_time_list is sorted
    self.trigger_time_list=self.trigger_time_list[n:]


import hashlib
def sha256(data):
        m=hashlib.sha256()
        m.update(bytes(data))
        return m.digest()
