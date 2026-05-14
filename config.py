import os

# ─── MySQL Database ───────────────────────────────────────────
MYSQL_HOST     = os.getenv('MYSQL_HOST',     'localhost')
MYSQL_USER     = os.getenv('MYSQL_USER',     'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')   # Set your MySQL password here
MYSQL_DB       = os.getenv('MYSQL_DB',       'portfolio_tracker')

# ─── Google OAuth ─────────────────────────────────────────────
# Get from: https://console.cloud.google.com/ → APIs & Services → Credentials
# Authorized redirect URI: http://localhost:5000/login/google/authorized
GOOGLE_CLIENT_ID     = os.getenv('GOOGLE_CLIENT_ID',     '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')

# ─── GitHub OAuth ─────────────────────────────────────────────
# Get from: https://github.com/settings/developers → OAuth Apps → New OAuth App
# Authorization callback URL: http://localhost:5000/login/github/authorized
GITHUB_CLIENT_ID     = os.getenv('GITHUB_CLIENT_ID',     '')
GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET', '')
