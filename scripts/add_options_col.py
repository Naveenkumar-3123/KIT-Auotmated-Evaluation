import sqlite3

con = sqlite3.connect("data/evalai.db")
cur = con.cursor()

# Check questions table
cur.execute("PRAGMA table_info(questions)")
cols = [r[1] for r in cur.fetchall()]
if "options" not in cols:
    cur.execute("ALTER TABLE questions ADD COLUMN options TEXT NOT NULL DEFAULT '[]'")
    print("Added options to questions")

# Check answer_key_diagrams table
cur.execute("PRAGMA table_info(answer_key_diagrams)")
d_cols = [r[1] for r in cur.fetchall()]
print("Current columns in answer_key_diagrams:", d_cols)
if "option_code" not in d_cols:
    cur.execute("ALTER TABLE answer_key_diagrams ADD COLUMN option_code TEXT")
    print("Added option_code to answer_key_diagrams!")

con.commit()
con.close()
print("Migration completed successfully!")
