from hashlib import sha256
import progpow
handler = progpow.ProgPowHandler(max_contexts_num=3)
_progpow_hash = handler.hash

def partial_hash(_bytes):
    seed1 = _bytes
    m1 = sha256()
    m1.update(seed1)
    return m1.digest()


def progpow_hash(header_height, serialized_header_without_nonce, nonce_bytes):
    ph = partial_hash(serialized_header_without_nonce)
    return _progpow_hash(header_height, ph, int.from_bytes(nonce_bytes, "big"))

