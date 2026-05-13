import mysql.connector
import os
from config import MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD

try:
    print(f"Connecting to MySQL at {MYSQL_HOST} with user {MYSQL_USER}...")
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD
    )
    cursor = conn.cursor()
    
    with open('database/schema.sql', 'r') as f:
        sql = f.read()
    
    # Simple split by semicolon. Note: This assumes no semicolons inside strings in schema.sql
    statements = sql.split(';')
    for statement in statements:
        if statement.strip():
            cursor.execute(statement)
            print(f"Executed: {statement[:50]}...")
            
    conn.commit()
    cursor.close()
    conn.close()
    print("Database initialized successfully.")
except Exception as e:
    print(f"Error initializing database: {e}")
