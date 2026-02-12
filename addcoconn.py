import sqlite3

DB = "delivery.db"
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("SELECT * FROM clients")
rows = c.fetchall()
for r in rows:
    print(r)

conn.close()
