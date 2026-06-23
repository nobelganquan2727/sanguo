import pymysql
import os

# Load environment from root folder
_base_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(os.path.dirname(os.path.dirname(_base_dir)), ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

def init_db():
    conn = pymysql.connect(
        host=os.getenv('MYSQL_HOST', 'localhost'),
        user=os.getenv('MYSQL_USER', 'root'),
        password=os.getenv('MYSQL_PASSWORD', '123456'),
        database=os.getenv('MYSQL_DB', 'sanguo')
    )
    
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INT AUTO_INCREMENT PRIMARY KEY,
                event_id VARCHAR(255) NOT NULL,
                event_title VARCHAR(255) NOT NULL,
                field_name VARCHAR(255) NOT NULL,
                proposed_value TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        ''')
    conn.commit()
    conn.close()
    print("MySQL feedback table initialized.")

if __name__ == "__main__":
    init_db()
