from leer.core.storage.merkle_storage import MMR
import shutil, os, time

class MMRTest1(MMR):
  def sum(self,x,y):
   return bytes("(%s+%s)"%(x.decode('utf-8'),y.decode('utf-8')),'ascii')


def basic_test():
  #((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))
  #0        1        2        3        4        5        6        7        8        9        
  # \      /          \      /          \      /          \      /          \      /
  #  (0+1)             (2+3)              (4+5)            (6+7)              (8+9)
  #       \            /                  \                 /                  |
  #        ((0+1)+(2+3))                      ((4+5)+(6+7))                  (8+9)
  #              \                                  /                          |
  #                (((0+1)+(2+3))+((4+5)+(6+7)))                             (8+9)
  #                                \                                        /
  #                                   ((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))
  a=MMRTest1("test2","~/.leer/storage/test")
  for i in range(10):
    a.append(bytes(str(i),'ascii'), bytes(str(i),'ascii'))

  assert a.get_root()==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  print("basic_test OK")

def wipe_test_dirs():
  shutil.rmtree("~/.leer/storage/test", True)

def test_rebuild_from_disc():
  a=MMRTest1("test1","~/.leer/storage/test")
  for i in range(10):
    a.append(bytes(str(i),'ascii'),bytes(str(i),'ascii'))

  assert a.get_root()==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  b=MMRTest1("test1","~/.leer/storage/test")
  assert b.get_root()==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  print("rebuild_from_disc OK")


def test_remove_elements():
  a=MMRTest1("test3","~/.leer/storage/test")
  for i in range(10):
    a.append(bytes(str(i),'ascii'),bytes(str(i),'ascii'))

  assert a.get_root()==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  a.remove(1)
  assert a.get_root()==b'((((0+1)+(2+3))+((4+5)+(6+7)))+8)'

  #This whole construction is nasty, should be done with proper exceptions
  bad =False
  try: 
    a.remove(1, {b'3'})
    bad = True
  except:
    pass
  if bad:
    raise

  a.append(bytes(str(9),'ascii'),bytes(str(i),'ascii'))
  assert a.get_root()==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  a.remove(4)
  assert a.get_root()==b'(((0+1)+(2+3))+(4+5))'
  a.append(bytes('a','ascii'),bytes(str(i),'ascii'))
  a.append(bytes('b','ascii'),bytes(str(i),'ascii'))
  a.append(bytes('c','ascii'),bytes(str(i),'ascii'))
  assert a.get_root()==b'((((0+1)+(2+3))+((4+5)+(a+b)))+c)'
  print("test_element_removal OK")



def test_prune_elements():
  a=MMRTest1("test4","~/.leer/storage/test")
  for i in range(10):
    a.append(bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))
  full_root = b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  assert a.get_root()==full_root
  cleared_objects=[]
  for i in range(3,6):
    cleared_objects.append(a.clear(bytes(str(i),'ascii')))
  assert a.get_root()==b'((((0+1)+2)+(6+7))+(8+9))'
  print("test_element_clearing OK")
  for _o in cleared_objects[:-1]:
    a.revert_clearing(_o)
  assert a.get_root()==b'((((0+1)+(2+3))+(4+(6+7)))+(8+9))'
  a.revert_clearing(cleared_objects[-1])
  assert a.get_root()==full_root
  print("test_element_revert_clearing OK")

  a=MMRTest1("test5","~/.leer/storage/test")
  for i in range(10):
    a.append(bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))

  assert a.get_root()==full_root
  discarded_objects=[]
  for i in range(3,6):
    discarded_objects.append(a.discard(bytes(str(i),'ascii')))
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'))
    if i in list(range(3,6)):
      assert el==None
    else:
      assert el==bytes(str(i)*2,'ascii')
  assert a.get_root()==full_root
  print("test_element_discarding OK")
  for _o in discarded_objects[:-1]:
    a.revert_discarding(_o)
  assert a.get_root()==full_root
  a.revert_discarding(cleared_objects[-1])
  assert a.get_root()==full_root
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'))
    assert el==bytes(str(i)*2,'ascii')
  print("test_element_revert_discarding OK")


def test_save_pruned_db():
  a=MMRTest1("test6","~/.leer/storage/test", save_pruned=True)
  for i in range(10):
    a.append(bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))
  full_root = b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  assert a.get_root()==full_root
  cleared_objects=[]
  for i in range(3,6):
    cleared_objects.append(a.clear(bytes(str(i),'ascii')))
  assert a.get_root()==b'((((0+1)+2)+(6+7))+(8+9))'
  for i in range(3,6):
    assert a.get_pruned_by_hash(bytes(str(i),'ascii'))==bytes(str(i)*2,'ascii')
  print("test_pruned_in_pruned_db_clear OK")
  for _o in cleared_objects[:-1]:
    a.revert_clearing(_o)
  assert a.get_root()==b'((((0+1)+(2+3))+(4+(6+7)))+(8+9))'
  a.revert_clearing(cleared_objects[-1])
  assert a.get_root()==full_root
  for i in range(3,6):
    assert a.get_pruned_by_hash(bytes(str(i),'ascii'))==None
  print("test_pruned_not_in_pruned_db_afeter_revert_clearing OK")

  a=MMRTest1("test7","~/.leer/storage/test")
  for i in range(10):
    a.append(bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))

  assert a.get_root()==full_root
  discarded_objects=[]
  for i in range(3,6):
    discarded_objects.append(a.discard(bytes(str(i),'ascii')))
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'))
    if i in list(range(3,6)):
      assert el==None
    else:
      assert el==bytes(str(i)*2,'ascii')
  assert a.get_root()==full_root
  print("test_pruned_in_pruned_db_clear OK")
  for _o in discarded_objects[:-1]:
    a.revert_discarding(_o)
  assert a.get_root()==full_root
  a.revert_discarding(cleared_objects[-1])
  assert a.get_root()==full_root
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'))
    assert el==bytes(str(i)*2,'ascii')
  print("test_element_revert_discarding OK")


def test_state_assignment():
  a=MMRTest1("test7","~/.leer/storage/test", save_pruned=True)
  assert a.get_state()==None
  new_state = b"\x33"*32
  a.set_state(new_state)
  assert new_state == a.get_state()
  print("test_state_assignment ok")


def bench(n=10000):
  tm=time.time()
  a=MMRTest1("test1","~/.leer/storage/test")
  for i in range(n):
    a.append(bytes(str(i),'ascii'),bytes(str(i),'ascii'))

  assert a.get_root()==b"("*5
  print("Initial filling of %d take %f sec"%(n, time.time()-tm))
  
  tm=time.time()
  b=MMRTest1("test1","~/.leer/storage/test")
  assert b.get_root()==b"("*5
  print("Reload take of %d take %f sec"%(n, time.time()-tm))


def merkle_test():
  wipe_test_dirs()
  basic_test()
  test_rebuild_from_disc()
  test_remove_elements()
  test_prune_elements()
  test_save_pruned_db()
  test_state_assignment()
  wipe_test_dirs()

