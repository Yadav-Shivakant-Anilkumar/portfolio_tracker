import os

# ─── MySQL Database ───────────────────────────────────────────
MYSQL_HOST     = os.getenv('MYSQL_HOST',     'localhost')
MYSQL_USER     = os.getenv('MYSQL_USER',     'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')   # Set your MySQL password here
MYSQL_DB       = os.getenv('MYSQL_DB',       'portfolio_tracker')

