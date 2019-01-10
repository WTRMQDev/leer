from leer.core.storage.merkle_storage import MMR
import shutil, os, time, lmdb

class MMRTest1(MMR):
  def sum(self,x,y):
   return bytes("(%s+%s)"%(x.decode('utf-8'),y.decode('utf-8')),'ascii')

env = None
def create_db():
  global env
  path = "~/.testleer/"
  if not os.path.exists(path): 
      os.makedirs(path) #TODO catch
  env = lmdb.open(path, map_size = 1000000, max_dbs=70)   


def wipe_test_dirs():
  shutil.rmtree("~/.testleer/", True)

def basic_test(env, wtx):
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
  a=MMRTest1("test2","~/.testleer/", env, wtx)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'), bytes(str(i),'ascii'))

  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  print("basic_test OK")


def test_rebuild_from_disc(env, wtx):
  a=MMRTest1("test1","~/.testleer/", env, wtx)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i),'ascii'))

  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  b=MMRTest1("test1","~/.testleer/", env, wtx)
  assert b.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  print("rebuild_from_disc OK")


def test_remove_elements(env, wtx):
  a=MMRTest1("test3","~/.testleer/", env, wtx)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i),'ascii'))

  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  a.remove(1, wtx=wtx)
  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+8)'

  #This whole construction is nasty, should be done with proper exceptions
  bad =False
  try: 
    a.remove(1, wtx=wtx, set_of_indexes={b'3'})
    bad = True
  except:
    pass
  if bad:
    raise

  a.append(wtx, bytes(str(9),'ascii'),bytes(str(i),'ascii'))
  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  a.remove(4, wtx=wtx)
  assert a.get_root(rtx=wtx)==b'(((0+1)+(2+3))+(4+5))'
  a.append(wtx, bytes('a','ascii'),bytes(str(i),'ascii'))
  a.append(wtx, bytes('b','ascii'),bytes(str(i),'ascii'))
  a.append(wtx, bytes('c','ascii'),bytes(str(i),'ascii'))
  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(a+b)))+c)'
  print("test_element_removal OK")



def test_prune_elements(env, wtx):
  a=MMRTest1("test4","~/.testleer/", env, wtx)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))
  full_root = b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  assert a.get_root(rtx=wtx)==full_root
  cleared_objects=[]
  for i in range(3,6):
    cleared_objects.append(a.clear(bytes(str(i),'ascii'), wtx=wtx))
  assert a.get_root(rtx=wtx)==b'((((0+1)+2)+(6+7))+(8+9))'
  print("test_element_clearing OK")
  for _o in cleared_objects[:-1]:
    a.revert_clearing(_o, wtx=wtx)
  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+(4+(6+7)))+(8+9))'
  a.revert_clearing(cleared_objects[-1], wtx=wtx)
  assert a.get_root(rtx=wtx)==full_root
  print("test_element_revert_clearing OK")

  a=MMRTest1("test5","~/.testleer/", env, wtx)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))

  assert a.get_root(rtx=wtx)==full_root
  discarded_objects=[]
  for i in range(3,6):
    discarded_objects.append(a.discard(bytes(str(i),'ascii'), wtx=wtx))
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'), rtx=wtx)
    if i in list(range(3,6)):
      assert el==None
    else:
      assert el==bytes(str(i)*2,'ascii')
  assert a.get_root(rtx=wtx)==full_root
  print("test_element_discarding OK")
  for _o in discarded_objects[:-1]:
    a.revert_discarding(_o, wtx=wtx)
  assert a.get_root(rtx=wtx)==full_root
  a.revert_discarding(cleared_objects[-1], wtx=wtx)
  assert a.get_root(rtx=wtx)==full_root
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'), rtx=wtx)
    assert el==bytes(str(i)*2,'ascii')
  print("test_element_revert_discarding OK")


def test_save_pruned_db(env, wtx):
  a=MMRTest1("test6","~/.testleer/", env, wtx, save_pruned=True)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))
  full_root = b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  assert a.get_root(rtx=wtx)==full_root
  cleared_objects=[]
  for i in range(3,6):
    cleared_objects.append(a.clear(bytes(str(i),'ascii'), wtx=wtx))
  assert a.get_root(rtx=wtx)==b'((((0+1)+2)+(6+7))+(8+9))'
  for i in range(3,6):
    assert a.get_pruned_by_hash(bytes(str(i),'ascii'),rtx=wtx)==bytes(str(i)*2,'ascii')
  print("test_pruned_in_pruned_db_clear OK")
  for _o in cleared_objects[:-1]:
    a.revert_clearing(_o, wtx=wtx)
  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+(4+(6+7)))+(8+9))'
  a.revert_clearing(cleared_objects[-1], wtx=wtx)
  assert a.get_root(rtx=wtx)==full_root
  for i in range(3,6):
    assert a.get_pruned_by_hash(bytes(str(i),'ascii'), rtx=wtx)==None
  print("test_pruned_not_in_pruned_db_afeter_revert_clearing OK")

  a=MMRTest1("test7","~/.testleer/", env, wtx)
  for i in range(10):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i)*2,'ascii'))

  assert a.get_root(rtx=wtx)==full_root
  discarded_objects=[]
  for i in range(3,6):
    discarded_objects.append(a.discard(bytes(str(i),'ascii'), wtx=wtx))
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'), rtx=wtx)
    if i in list(range(3,6)):
      assert el==None
    else:
      assert el==bytes(str(i)*2,'ascii')
  assert a.get_root(rtx=wtx)==full_root
  print("test_pruned_in_pruned_db_clear OK")
  for _o in discarded_objects[:-1]:
    a.revert_discarding(_o, wtx=wtx)
  assert a.get_root(rtx=wtx)==full_root
  a.revert_discarding(cleared_objects[-1], wtx=wtx)
  assert a.get_root(rtx=wtx)==full_root
  for i in range(10):
    el=a.get_by_hash(bytes(str(i),'ascii'),rtx=wtx)
    assert el==bytes(str(i)*2,'ascii')
  print("test_element_revert_discarding OK")


def test_state_assignment(env, wtx):
  a=MMRTest1("test7","~/.testleer/", env, wtx, save_pruned=True)
  assert a.get_state(rtx=wtx)==None
  new_state = b"\x33"*32
  a.set_state(new_state, wtx=wtx)
  assert new_state == a.get_state(rtx=wtx)
  print("test_state_assignment OK")


def test_unique(env, wtx):
  a=MMRTest1("unique","~/.testleer/", env, wtx, save_pruned=True)
  for i in range(10):
    a.append_unique(wtx, bytes(str(i),'ascii'), b"e1ee7 "+bytes(str(i),'ascii'))
  assert a.get_root(rtx=wtx)==b'((((0+1)+(2+3))+((4+5)+(6+7)))+(8+9))'
  try:
    a.append_unique(wtx, bytes(str(8),'ascii'), bytes(str(8),'ascii'))
    raise Exception
  except KeyError:
    pass
  assert a.has_index(rtx=wtx, obj_index=bytes(str(8),'ascii'))
  assert not a.has_index(rtx=wtx, obj_index=bytes(str(12),'ascii'))
  a.update_index(wtx, 2, b"e")
  assert a.get_root(rtx=wtx)==b'((((0+1)+(e+3))+((4+5)+(6+7)))+(8+9))'
  assert not a.has_index(rtx=wtx, obj_index=bytes(str(2),'ascii'))
  assert a.has_index(rtx=wtx, obj_index=b"e")
  assert a.get_by_hash(b"e", rtx=wtx) == b"e1ee7 2"
  print("test_unique OK")
  



def bench(env, wtx, n=10000):
  tm=time.time()
  a=MMRTest1("test1","~/.testleer/", env, wtx)
  for i in range(n):
    a.append(wtx, bytes(str(i),'ascii'),bytes(str(i),'ascii'))

  assert a.get_root(rtx=wtx)==b"("*5
  print("Initial filling of %d take %f sec"%(n, time.time()-tm))
  
  tm=time.time()
  b=MMRTest1("test1","~/.testleer/", env, wtx)
  assert b.get_root(rtx=wtx)==b"("*5
  print("Reload take of %d take %f sec"%(n, time.time()-tm))


def merkle_test():
  wipe_test_dirs()
  create_db()
  with env.begin(write=True) as wtx:
    basic_test(env, wtx)
    test_rebuild_from_disc(env, wtx)
    test_remove_elements(env, wtx)
    test_prune_elements(env, wtx)
    test_save_pruned_db(env, wtx)
    test_state_assignment(env, wtx)
    test_unique(env, wtx)
  wipe_test_dirs()

