default_config =   {
                     'relay_fee_per_kb': 3000
                   }


class FeePolicyChecker:
  
  def __init__(self, config = default_config):
    self.relay_fee_per_kb = int(config['relay_fee_per_kb'])

  def check_tx(self,tx):
    size = len(tx.serialize())
    if tx.coinbase:
      size -= 2 #len of len of output
      size -= len(tx.coinbase.serialize())
    if int((size/1000.)*self.relay_fee_per_kb)>tx.relay_fee:
      return False
    return True
    

