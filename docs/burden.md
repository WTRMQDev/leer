#Rules for burden:
* OUTPUTORHASH burden can be created only in tx which contains OUTPUT (if it already contains excess burden will not be created).
* Pubkey contained in OUTPUTORHASH should coinside with address pubkey of corresponding OUTPUT.
* Excess which closes burden is excsess with corresponding pubkey and message equal to `b"\x01\x00"+OUTPUT.apc`
* Excess which closes burden may arise as 'updated excess', but it is not necessary
* Burden storage is key-value `output_index` -> `excess_deterministic_index`: when output is spent excess should be added.
