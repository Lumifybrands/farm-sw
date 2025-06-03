import sqlite3

db_path = 'app.db'  # Change if needed

conn = sqlite3.connect('instance/bismi_farm.db')
cursor = conn.cursor()

cursor.execute("ALTER TABLE batch_update_feeds ADD COLUMN price_at_time FLOAT DEFAULT 0.0;")
cursor.execute("ALTER TABLE batch_update_feeds ADD COLUMN total_cost FLOAT DEFAULT 0.0;")
conn.commit()
conn.close()
print("Columns added.")