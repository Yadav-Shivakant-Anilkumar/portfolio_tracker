"""
init_db.py - Portfolio Tracker: Fresh Database Initializer
----------------------------------------------------------
Run this script ONCE to (re)create the entire database schema.

WARNING: Running with FORCE_DROP=True will DELETE all existing data.
         Set it to False to only create missing tables.

Usage:
    python init_db.py
"""
import sys
import io
import os
import mysql.connector

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from config import MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB

# -------------------------------------------------------
# Set to True to DROP the database and start completely fresh.
# Set to False to only create tables that are missing.
# -------------------------------------------------------
FORCE_DROP = True


def run_init():
    print("=" * 55)
    print("  Portfolio Tracker - Database Initializer")
    print("=" * 55)
    print(f"  Host     : {MYSQL_HOST}")
    print(f"  User     : {MYSQL_USER}")
    print(f"  Database : {MYSQL_DB}")
    print(f"  Mode     : {'FRESH INSTALL (DROP + RECREATE)' if FORCE_DROP else 'SAFE (CREATE IF NOT EXISTS)'}")
    print("=" * 55)

    try:
        # Connect without a specific DB so we can manage the database itself
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            autocommit=True,
            use_pure=True          # Required for MySQL 8.0 caching_sha2_password auth
        )
        cursor = conn.cursor()

        if FORCE_DROP:
            confirm = input(f"\n[!] This will DELETE all data in '{MYSQL_DB}'. Type 'yes' to confirm: ").strip().lower()
            if confirm != 'yes':
                print("Aborted. No changes made.")
                cursor.close()
                conn.close()
                sys.exit(0)

            print(f"\n  Dropping database '{MYSQL_DB}' if it exists...")
            cursor.execute(f"DROP DATABASE IF EXISTS `{MYSQL_DB}`")
            print(f"  [OK] Dropped '{MYSQL_DB}'")

        # Read and execute the schema file
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'schema.sql')
        if not os.path.exists(schema_path):
            print(f"\n  [ERROR] Schema file not found at: {schema_path}")
            sys.exit(1)

        with open(schema_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        # Split by semicolon, skip empty/comment-only blocks
        statements = [
            s.strip() for s in sql_content.split(';')
            if s.strip() and not s.strip().startswith('--')
        ]

        print(f"\n  Executing {len(statements)} SQL statement(s)...\n")
        for i, stmt in enumerate(statements, 1):
            try:
                cursor.execute(stmt)
                first_line = stmt.splitlines()[0][:70]
                print(f"  [{i:02d}] [OK] {first_line}")
            except mysql.connector.Error as e:
                print(f"  [{i:02d}] [ERR] {e}")
                print(f"         Statement: {stmt[:100]}")
                raise

        conn.commit()
        cursor.close()
        conn.close()

        print("\n" + "=" * 55)
        print("  [SUCCESS] Database initialized successfully!")
        print("=" * 55)
        print("\n  Next steps:")
        print("  1. Run: python app.py")
        print("  2. Open http://localhost:5000 in your browser.\n")

    except mysql.connector.Error as e:
        print(f"\n  [ERROR] MySQL connection failed: {e}")
        print("\n  Tip: Open config.py and set MYSQL_PASSWORD to your MySQL root password.")
        print("  If using XAMPP with no password, leave it as empty string ''.\n")
        sys.exit(1)


if __name__ == '__main__':
    run_init()
