from hashlib import sha256
import progpow
import functools


handler = progpow.ProgPowHandler(max_contexts_num=3)
_progpow_hash = handler.hash

@functools.lru_cache(maxsize=256)
def partial_hash(_bytes):
    seed1 = _bytes
    m1 = sha256()
    m1.update(seed1)
    return m1.digest()

@functools.lru_cache(maxsize=256)
def progpow_hash(header_height, serialized_header_without_nonce, nonce_bytes):
    ph = partial_hash(serialized_header_without_nonce)
    return _progpow_hash(header_height, ph, int.from_bytes(nonce_bytes, "big"))

@functools.lru_cache(maxsize=5)
def seed_hash(header_height):
  return handler.give_seed(header_height)
