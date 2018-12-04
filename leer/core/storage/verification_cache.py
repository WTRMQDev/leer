from leer.core.utils import ObliviousDictionary

class VerificationCache:
  '''
   Verification cache is in memory cache for storing (non-context and semi-non-context) validity 
   of different objects.
   Two type of keys may be presented:
     tuple for semi-non-context checks. Second element of tuple is trated as block_number. If something
      was valid at height h, it should be valid at any height h' such as h'>=h. If something was not valid
      at height h, it should not be valid at any height h' such as h'<=h.
     anything else, in this case verification cache is just oblivious dictionary
  '''
  def __init__(self):
    self.od = ObliviousDictionary(3600)

  def __getitem__(self, _index):
    if isinstance(_index, tuple):
      _index, check_block = _index
      is_valid, has_block = self.od[_index]
      if is_valid and check_block>=has_block: #Once valid, always valid
        return True
      if (not is_valid) and (check_block<=has_block): #If not valid at block x, not valid for all blocks before x
        return False
      raise KeyError #Generally cant say anything
    else:
      return self.od[_index]

  def __setitem__(self, _index, _object):
    if isinstance(_index, tuple):
      _index, check_block = _index
      self.od[_index]=(_object, check_block)
    else:
      self.od[_index]=_object


verification_cache = VerificationCache()
