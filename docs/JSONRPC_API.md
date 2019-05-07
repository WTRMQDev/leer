# JSON RPC API:

## Methods 

1. ping - (no params) - return `pong`
2. getconnectioncount - (no params) - return integer connection_num
3. getheight - (no params) - return integer current blockchain tip height (may not coinside with header tip)
4. getblocktemplate - (no params) - return b64 encoded header of new block with zeroed nonce field
5. getwork - (no params) - return array `[partial_hash, seed_hash, target, height]` of new block, all parameters encoded as hex-numbers with `0x` prefix
6. submitwork - (`hex_nonce, partial_hash_hex, ignored_field` encoded as proposed in getwork) - return string, either `Accepted`, or error description
7. validatesolution - (`b64_encoded_header_with_solution`) - return string, either `Accepted`, or error description
8. getbalancestats - 
9. getbalancelist
10. getbalance
11. sendtoaddress
12. getnewaddress
13. dumpprivkey
14. importprivkey
15. getsyncstatus
16. getblock
17. getnodes
18. connecttonode
19. gettransactions
20. getversion
21. shutdown
