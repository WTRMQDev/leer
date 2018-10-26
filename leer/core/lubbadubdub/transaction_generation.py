
#we want to send v coins to address A


tx = Transaction()


inputs=[]
for _input in inputs:
  tx.push_input(_input)

tx.add_destination((A,v))
tx.generate()

