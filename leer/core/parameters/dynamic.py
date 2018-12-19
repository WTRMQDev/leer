from leer.core.storage.headers_storage import HeadersStorage

from leer.core.utils import encode_target, decode_target

from leer.core.parameters.constants import *
from math import exp, ceil

def next_target(_hash, headers_storage, rtx):
  span = 20
  if not headers_storage.has(_hash, rtx=rtx):
    raise
  header = headers_storage.get(_hash, rtx=rtx)
  if header.height<=span:
    return decode_target(*encode_target(initial_target))
  average_target =0
  runner = header
  for i in range(span):
    average_target +=runner.target/span
    runner = headers_storage.get(runner.prev, rtx=rtx)
  average_period = (header.timestamp - runner.timestamp)/span
  target = average_target * max(min(average_period/block_time, max_target_increase), max_target_decrease)
  if target > minimal_target:
    target = minimal_target
  target = decode_target(*encode_target(target))
  return target

def next_reward(_hash, headers_storage, rtx):
  span = 1024
  if _hash == b"\x00"*32:# 'prev' of genesis
    return max_reward(0)
  if not headers_storage.has(_hash, rtx=rtx):
    raise
  header = headers_storage.get(_hash, rtx=rtx)
  if header.height<=span:
    return max_reward(header.height+1)
  runner = header
  summ = 0
  for i in range(span):
    summ += runner.votedata.miner_subsidy_vote_int
    runner = headers_storage.get(runner.prev, rtx=rtx)
  return int(max_reward(header.height+1) * (summ/(255.*span)))

def max_reward(height):
  return int(initial_reward * exp(-float(height)/reward_decrease_halflife))
