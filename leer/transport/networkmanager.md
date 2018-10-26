# NetworkNode
Class which represent node in the network and handle transport level communication with that node: open connection, handshake, read and send.

# Node
Class that is inherited from NetworkNode, implement high-level logic

# NetworkManager
Singleton-object which handle set of nodes. Read from syncer.queues['NM'], list of processed commands listed in messages.md

