from os.path import *
home = expanduser("~")
base_dir = join(home, ".leer")

def calc_paths(base_dir):
  blockchain = join(base_dir, "blockchain")
  txo_storage_path = join(blockchain, "txos_storage")
  excesses_storage_path = join(blockchain, "excesses_storage")
  headers_storage_path = join(blockchain, "headers_storage")
  blocks_storage_path = join(blockchain, "blocks_storage")

  wallet_path = join(base_dir, "wallet")
  key_manager_path = join(wallet_path, "default_wallet")
  utxo_index_path = join(base_dir, "meta", "utxo_index")

  return txo_storage_path, txo_storage_path, excesses_storage_path,\
         headers_storage_path, blocks_storage_path, wallet_path,\
         key_manager_path, utxo_index_path

txo_storage_path, txo_storage_path, excesses_storage_path,\
headers_storage_path, blocks_storage_path, wallet_path,\
key_manager_path, utxo_index_path = calc_paths(base_dir)
