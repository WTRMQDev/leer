message_id = {
b"\x00\x00": "init",
b"\x00\x01": "ping",
b"\x00\x02": "pong",
b"\x00\x03": "give nodes",
b"\x00\x04": "take nodes",
b"\x00\x05": "give next headers",
b"\x00\x06": "take the headers",
b"\x00\x07": "give blocks",
b"\x00\x08": "take the blocks",
b"\x00\x09": "give the txos",
b"\x00\x0a": "take the txos",
b"\x00\x0b": "give outputs",
b"\x00\x0c": "take TBM transaction",
b"\x00\x0d": "give TBM transaction",
b"\x00\x0e": "take tip info",
b"\x00\x0f": "find common root",
b"\x00\x10": "find common root response"
}

inv_message_id = {v: k for k, v in message_id.items()}
