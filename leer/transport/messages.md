# List of inner messages consumed by NetworkManager


1. `take the blocks` 
 a. `num`: blocks number - `int`
 b. `blocks`: serialized blocks - `bytes`, one block after the other
 c. `node`: node params - `str`

2. `give next headers`
 a. `num`: num of requested headers - `int`
 b. `from`: from which headers headers are requested - `bytes` hash
 c. `node`: node params - `str`

3. `take the headers`
 a. `num`: headers number - `int`
 b. `headers`: serialized headers - `bytes`, one header after the other
 c. `node`: node params - `str`

4. `take the txos`
 a. `num`: number of txos - `int`
 b. `txos`: serialized txos - `bytes`, one txo after the other
 c. `txos_hashes`: hashes of txos - `bytes`, one hash after the other
 d. `txos_lengths`: length of txos - `bytes`, one length (serialized as 2bytes big-endian) after the other
 e. `node`: node params - `str`

5. `take tip info`
 a. `height`: height of top block - `int`
 b. `tip`: hash of top block - `bytes` hash
 c. `prev_hash`: hash of previous block - `bytes` hash
 d. `total_difficulty`: total difficulty of the chain - `int`
 e. `node`: node params - `str`

6. `find common root`
 a. `serialized_header`: serialized header for which node want to find common root - `bytes`
 b. `node`: node params - `str`

7. `find common root response`
 a. `header_hash` : hash of the header sent in `find common root` message - `bytes`
 b. `known_headers`: flags about hashes contained in received header popow - `bytes`, one flag (serialized as 1byte) after the other
 c. `flags_num`: number of flags in `known_headers` - `int`
 d. `node`: node params - `str`

8. `give blocks`
 a. `block_hashes`: hashes of blocks - `bytes`, one hash after the other
 b. `num`: number of requested blocks - `int`
 c. `node`: node params - `str`

9. `give txos`
 a. `txos_hashes`: hashes (65bytes len) of txouts - `bytes`, one hash after the other
 b. `num`: number of requested txos - `int`
 c. `node`: node params - `str`

