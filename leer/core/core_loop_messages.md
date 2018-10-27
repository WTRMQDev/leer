#Intro
Different threads interact with each other using queues which are stored by Syncer object.
This document describes message format which is recognized by core_loop (thread which work with blockchain).

#Basic Message structure
Each message is python dictionary.
## Mandatory fields
1. `action` - string. Describe required action.
2. `sender` - string, one of `['NetworkManager', 'Blockchain', 'RPCManager']`. Describe thread which sent message.
3. `id` - string or integer. `id` is used for matching request and response.
For some `actions` optional field may be included into message.


##Actions list
1. `take the headers`: `headers` field should contain binary data for serialized headers, `source` field should contain information about node which provided headers (we may want to ask for blocks or ban for DoS). After message processing core_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK` or `FAIL`, `id` set to the same as in initial message. If `status` is `FAIL` optional field `DOS-score` with integer may be presented.

2. `take the blocks`: `blocks` field should contain binary data for serialized blocks, `source` field should contain information about node which provided blocks (we may want to ask for blocks or ban for DoS). Note, blocks may be serialized in "Rich block format" and contain (some) utxo. After message processing core_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK` or `FAIL`, `id` set to the same as in initial message. If `status` is `FAIL` optional field `DOS-score` with integer may be presented.

3. `take the utxos`: `utxos` field should contain binary data for serialized utxos, `source` field should contain information about node which provided utxos (we may want to ask for blocks or ban for DoS). After message processing core_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK` or `FAIL`, `id` set to the same as in initial message. If `status` is `FAIL` optional field `DOS-score` with integer may be presented.

5. `take the tx sceleton`: `tx_sceleton` field should contain binary data for serialized tx sceleton, `source` field should contain information about node which provided tx (we may want to ask for blocks or ban for DoS). After message processing core_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK` or `FAIL`, `id` set to the same as in initial message. If `status` is `FAIL` optional field `DOS-score` with integer value may be presented.

6. `give block`: `block_hash` field should be 32-bytes long binary stream (python type: bytes). After message processing core_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK` or `FAIL`, `id` set to the same as in initial message. If `status` is `OK` optional field `block` with bytes should be presented.

7. `give txout`: `txout_hash` field should be 65-bytes long binary stream (python type: bytes). After message processing core_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK` or `FAIL`, `id` set to the same as in initial message. If `status` is `OK` optional field `txout` with bytes should be presented.

8. `give actual tx sceleton`: (no additional fields). After message processing core\_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK`, `id` set to the same as in initial message. `tx_sceleton` should contain tx which merge all known transactions.

9. `give block template`: (no additional fields). After message processing core\_loop emitsmessage to `sender` queue with `action` set to `response`, `status` set to `OK`, `id` set to the same as in initial message. `block_template` should contain serialized header for fresh block where coinbase-address is owned by wallet.

10. `check block download status`

11. `take tip info` 
