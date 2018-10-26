from chacha20poly1305 import ChaCha20Poly1305
from secp256k1_zkp import PrivateKey, PublicKey, PedersenCommitment
from leer.core.lubbadubdub.constants import default_generator

def top_up_nonce(nonce):
    if len(nonce)<12:
      return b"\x00"*(12-len(nonce))+nonce
    else:
      return nonce[-12:]


def encrypt(pubkey, nonce, plaintext):
    '''
      Encrypt plaintext for some pubkey (owner of corresponding privkey can decrypt).
      params:
       pubkey: secp256k1_py PublicKey object
       nonce: 12 bytes nonce, should not be reused
       plaintext: bytes object with arbitrary length.
      
      Inner logic:
        1) generate ephemereal (one time) private_key.
        2) generate shared_secret : ecdh of private_key and receiver's pubkey
        3) symmetricly encrypt plaintext with shared_secret (encryption with ChaCha20Poly1305)
        4) attach ephemereal public_key to ciphertext
    '''
    nonce = top_up_nonce(nonce)
    ephemeral_privkey = PrivateKey()
    shared_key = pubkey.ecdh(ephemeral_privkey.private_key)
    aead = ChaCha20Poly1305(shared_key, 'python')
    res = aead.seal(nonce, plaintext, b'')
    res = ephemeral_privkey.pubkey.serialize() + res
    return res


def decrypt(privkey, nonce, ciphertext):
    nonce = top_up_nonce(nonce)
    pubkey, ciphertext = PublicKey(pubkey=ciphertext[:33], raw=True), ciphertext[33:]
    shared_key = pubkey.ecdh(privkey.private_key)
    aead = ChaCha20Poly1305(shared_key, 'python')
    res = aead.open(nonce, ciphertext, b'')
    if res is None:
      raise Exception("Cant decrypt")
    return res


def compare_supply_and_merkle_roots(total_supply, commitment_root, excesses_root):
  '''
    Each txout (authorized pedersen) commitment is v*G + r*H, where v is value and r is blinding key, G and H - generators.
    Each blinding key is previous blinding key + private_key of address +/- blinding key which should be compensated by additional excesses.
    Thus if we summarized all commitments result should V*G+R*H, where
    V - is supply: sum of all unspend values on blockchain. Note that supply is not equal to all minted coins, 
        since new_outputs_fee retains some coins.
    R - is summ of private keys and private keys of additional excsses. For know excsses are append-only to blockchain, thus R*H is summ of all addresses's pubkeys and all additional excsses. Note, while R is not known, R*H can be calculated from public data.
    This function check that calculated
        V*G (calculated from supply) plus R*H (calculated from excesses and addresses) is equal to summ of commitments V*G+R*H.
  '''
  commitment_summ = PedersenCommitment(commitment=commitment_root[:33], raw=True) 
  excesses_summ = PublicKey(pubkey= excesses_root[:33], raw=True).to_pedersen_commitment()
  supply_pc = PedersenCommitment(blinded_generator = default_generator)
  supply_pc.create(total_supply, b'\x00'*32)
  checker = PedersenCommitment()
  return checker.verify_sum([excesses_summ, supply_pc], [commitment_summ])
  


