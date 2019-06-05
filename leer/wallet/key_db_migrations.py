migrations = []

def apply_migrations(cursor):
  current = get_current_stage(cursor)
  for stage, migration in migrations:
    if stage<current:
      continue
    migration(cursor)

def get_current_stage(cursor):
  try:
    cursor.execute("SELECT value from metadata where key='migration_stage'")
    return float(cursor.fetchone()[0])
  except sqlite3.OperationalError as e:
    if "no such table" in str(e):
      return 0
   

def init_database(cursor):
  cursor.execute("CREATE TABLE metadata (key text, value text)")
  cursor.execute("CREATE TABLE keys (id integer PRIMARY KEY AUTOINCREMENT, pubkey text KEY, privkey text, outputs text, created_at integer, updated_at integer, pool boolean)")
  cursor.execute("CREATE TABLE outputs (id integer PRIMARY KEY AUTOINCREMENT, output text KEY, pubkey text, value text, lock_height text, created_height text KEY, spent_height text KEY, ser_blinding_key text, ser_apc text, taddress text KEY, spent boolean, updated_at integer)")
  cursor.execute("INSERT INTO metadata values ('migration_stage','1')")

migrations.append( (1, init_database) )

