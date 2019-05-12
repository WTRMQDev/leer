from uuid import uuid4

def send_next_headers_request(from_hash, num, node, send):
  send({"action":"give next headers", "num":num, "from":from_hash, 
                                       "id" : str(uuid4()), "node": node  })
