from hashlib import sha256
import progpow
import functools


handlers = {}

def check_handlers(version):
  if not version in handlers:
    if not version in ["0.9.2", "0.9.3"]:
      raise Exception("Unknown hash version")
    handlers[version] = progpow.ProgPowHandler(max_contexts_num=3, version=version)

@functools.lru_cache(maxsize=256)
def partial_hash(_bytes):
    seed1 = _bytes
    m1 = sha256()
    m1.update(seed1)
    return m1.digest()

@functools.lru_cache(maxsize=256)
def progpow_hash(header_height, serialized_header_without_nonce, nonce_bytes, version="0.9.2"):
    check_handlers(version)
    ph = partial_hash(serialized_header_without_nonce)
    return handlers[version].hash(header_height, ph, int.from_bytes(nonce_bytes, "big"))

@functools.lru_cache(maxsize=5)
def seed_hash(header_height, version="0.9.2"):
  check_handlers(version)
  return handlers[version].give_seed(header_height)
