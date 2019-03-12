leer
=====

Experimental cryptocurrency written in python; implements LubbaDubDub technology to conceal transacted volume.

**Leer is in beta-testing phase. Coins on testnet will NOT have any value and will NOT be transferred to mainnet.**

## Requirements
Currently works only on linux.

* Python 3.5+
* pip
* g++, cffi, build-essential for `lmdb` package

## Installation
`pip3 install leer`

## Run node
Download [config.json](https://github.com/WTRMQDev/leer/blob/master/scripts/example_config.json) and adjust config (file extension doesn't matter). It is necessary to insert login and password in double quotes into config.

Run node: open terminal and run `python3 -m leer path/to/config`

After start web interface will be available on configured rpc port (open in browser address `host:port`, for default config it is `127.0.0.1:9238`).

## Run testnet miner
Download [miner script](https://github.com/WTRMQDev/leer/blob/master/scripts/miner.py), adjust config (host and port) and run.
