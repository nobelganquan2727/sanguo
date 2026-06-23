import os
import sqlite3

_base_dir = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(os.path.dirname(os.path.dirname(_base_dir)), 'feedback.db')

def init_db():
    conn = sqlite3.connect(_db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            proposed_value TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
