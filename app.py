from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.contrib.github import make_github_blueprint, github
from flask_dance.consumer import oauth_authorized
import config
from datetime import datetime
import json
import os
import requests
from datetime import timedelta

# ─────────────────────────────────────────────────
# Live Price Helper & Caching
# ─────────────────────────────────────────────────
def get_live_price(symbol: str) -> float:
    """Fetch live market price with DB caching.
    Check cache first; if expired (>15m), fetch via yfinance."""
    sym = symbol.upper()
    
    # 1. Check DB Cache
    if mysql:
        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "SELECT last_price, fetched_at FROM price_cache WHERE asset_symbol = %s",
                [sym]
            )
            row = cur.fetchone()
            if row:
                price, fetched_at = row[0], row[1]
                # Cache valid for 15 minutes
                if datetime.now() - fetched_at < timedelta(minutes=15):
                    cur.close()
                    return float(price)
            cur.close()
        except Exception as e:
            print(f"Cache read error: {e}")

    # 2. Fetch from YFinance
    # Map common crypto tickers to yfinance format
    crypto_map = {'BTC': 'BTC-USD', 'ETH': 'ETH-USD', 'SOL': 'SOL-USD',
                  'BNB': 'BNB-USD', 'ADA': 'ADA-USD', 'XRP': 'XRP-USD'}
    ticker_sym = crypto_map.get(sym, sym)
    
    price = 0.0
    try:
        import yfinance as yf
        t = yf.Ticker(ticker_sym)
        # Using fast_info for speed
        info = t.fast_info
        price = float(info.last_price or 0)
        
        # If last_price fails, try history
        if price <= 0:
            hist = t.history(period="1d")
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])

        # 3. Update DB Cache
        if price > 0 and mysql:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO price_cache (asset_symbol, last_price, fetched_at)
                VALUES (%s, %s, NOW())
                ON DUPLICATE KEY UPDATE last_price=%s, fetched_at=NOW()
            """, (sym, price, price))
            mysql.connection.commit()
            cur.close()

    except Exception as e:
        print(f"yfinance error for {sym}: {e}")
    
    return price

@app.route('/api/search_assets')
@login_required
def search_assets():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return json.dumps([])

    try:
        # Using Yahoo Finance's query2 search endpoint
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        results = []
        for quote in data.get('quotes', []):
            # We only care about Stocks, Crypto, ETFs
            quote_type = quote.get('quoteType', '')
            if quote_type not in ['EQUITY', 'CRYPTOCURRENCY', 'ETF', 'MUTUALFUND']:
                continue
                
            results.append({
                'symbol': quote.get('symbol'),
                'name': quote.get('shortname') or quote.get('longname') or quote.get('symbol'),
                'category': quote_type.lower(),
                'exchange': quote.get('exchDisp')
            })
            
        return json.dumps(results[:10]) # Limit to top 10
    except Exception as e:
        print(f"Search API error: {e}")
        return json.dumps([])

@app.route('/api/get_price/<symbol>')
@login_required
def get_price_api(symbol):
    price = get_live_price(symbol)
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    return json.dumps({'price': price, 'symbol': currency_symbol})

CURRENCY_SYMBOLS = {'INR': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£', 'BTC': '₿'}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vaultfolio_super_secret_key_change_in_prod")
# Required for OAuth over HTTP in development (NEVER use in production)
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

# MySQL Config
app.config['MYSQL_HOST']     = config.MYSQL_HOST
app.config['MYSQL_USER']     = config.MYSQL_USER
app.config['MYSQL_PASSWORD'] = config.MYSQL_PASSWORD
app.config['MYSQL_DB']       = config.MYSQL_DB

try:
    mysql = MySQL(app)
except Exception as e:
    print(f"Error initializing MySQL: {e}")
    mysql = None

# ─────────────────────────────────────────────────
# OAuth Blueprints  (Google & GitHub)
# ─────────────────────────────────────────────────
google_bp = make_google_blueprint(
    client_id     = config.GOOGLE_CLIENT_ID,
    client_secret = config.GOOGLE_CLIENT_SECRET,
    scope         = ['openid', 'https://www.googleapis.com/auth/userinfo.email',
                     'https://www.googleapis.com/auth/userinfo.profile'],
    redirect_to   = 'google_oauth_callback',
)
github_bp = make_github_blueprint(
    client_id     = config.GITHUB_CLIENT_ID,
    client_secret = config.GITHUB_CLIENT_SECRET,
    scope         = 'user:email',
    redirect_to   = 'github_oauth_callback',
)
app.register_blueprint(google_bp, url_prefix='/login')
app.register_blueprint(github_bp, url_prefix='/login')

# ─────────────────────────────────────────────────
# Shared OAuth helper: find-or-create user
# ─────────────────────────────────────────────────
def _oauth_login_or_register(provider: str, provider_user_id: str, email: str,
                              first_name: str, last_name: str, access_token: str = None):
    """Find an existing user linked to this OAuth account, or create one.
    Sets the Flask session and returns True on success."""
    if not mysql or not email:
        flash("OAuth login failed: could not retrieve your email.", "error")
        return False

    cur = mysql.connection.cursor()
    try:
        # 1) Check if this provider account is already linked
        cur.execute(
            "SELECT user_id FROM oauth_providers WHERE provider=%s AND provider_user_id=%s",
            (provider, str(provider_user_id))
        )
        row = cur.fetchone()

        if row:
            # Provider already linked — fetch user and log in
            user_id = row[0]
            cur.execute("SELECT first_name, last_name FROM users WHERE id=%s", [user_id])
            u = cur.fetchone()
            session['user_id']   = user_id
            session['user_name'] = f"{u[0]} {u[1]}".strip() if u else email.split('@')[0]
        else:
            # 2) Check if the email is already registered (local account)
            cur.execute("SELECT id, first_name, last_name FROM users WHERE email=%s", [email])
            existing = cur.fetchone()

            if existing:
                # Link this provider to the existing account
                user_id = existing[0]
                session['user_name'] = f"{existing[1]} {existing[2]}".strip()
            else:
                # 3) Brand-new user — create a local account with a random password
                import secrets
                dummy_pw = generate_password_hash(secrets.token_hex(16))
                cur.execute(
                    "INSERT INTO users (first_name, last_name, email, password_hash) VALUES (%s,%s,%s,%s)",
                    (first_name, last_name, email, dummy_pw)
                )
                mysql.connection.commit()
                user_id = cur.lastrowid
                session['user_name'] = f"{first_name} {last_name}".strip()

            # Link this OAuth provider to the user
            cur.execute(
                """INSERT INTO oauth_providers (user_id, provider, provider_user_id, provider_email, access_token)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE provider_email=%s, access_token=%s""",
                (user_id, provider, str(provider_user_id), email, access_token,
                 email, access_token)
            )
            mysql.connection.commit()

            session['user_id'] = user_id

        cur.close()
        return True
    except Exception as e:
        print(f"OAuth DB error: {e}")
        cur.close()
        flash("An error occurred during login. Please try again.", "error")
        return False


# ─────────────────────────────────────────────────
# OAuth Callback Routes
# ─────────────────────────────────────────────────
@app.route('/oauth/google/callback')
def google_oauth_callback():
    if not google.authorized:
        flash("Google authorization failed or was cancelled.", "error")
        return redirect(url_for('login'))
    try:
        resp = google.get('/oauth2/v2/userinfo')
        if not resp.ok:
            flash("Failed to fetch your Google profile.", "error")
            return redirect(url_for('login'))
        info        = resp.json()
        provider_id = info.get('id', '')
        email       = info.get('email', '')
        first_name  = info.get('given_name', email.split('@')[0])
        last_name   = info.get('family_name', '')
        token       = google.token.get('access_token', '') if google.token else ''

        if _oauth_login_or_register('google', provider_id, email, first_name, last_name, token):
            flash(f"Welcome, {session.get('user_name', '')}! Signed in with Google.", "success")
            return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Google callback error: {e}")
        flash("Google login failed. Please try again.", "error")
    return redirect(url_for('login'))


@app.route('/oauth/github/callback')
def github_oauth_callback():
    if not github.authorized:
        flash("GitHub authorization failed or was cancelled.", "error")
        return redirect(url_for('login'))
    try:
        resp = github.get('/user')
        if not resp.ok:
            flash("Failed to fetch your GitHub profile.", "error")
            return redirect(url_for('login'))
        info        = resp.json()
        provider_id = str(info.get('id', ''))
        name_parts  = (info.get('name') or info.get('login', 'GitHub User')).split(' ', 1)
        first_name  = name_parts[0]
        last_name   = name_parts[1] if len(name_parts) > 1 else ''
        token       = github.token.get('access_token', '') if github.token else ''

        # GitHub may not return email in /user — fetch from /user/emails
        email = info.get('email') or ''
        if not email:
            emails_resp = github.get('/user/emails')
            if emails_resp.ok:
                for e in emails_resp.json():
                    if e.get('primary') and e.get('verified'):
                        email = e.get('email', '')
                        break

        if _oauth_login_or_register('github', provider_id, email, first_name, last_name, token):
            flash(f"Welcome, {session.get('user_name', '')}! Signed in with GitHub.", "success")
            return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"GitHub callback error: {e}")
        flash("GitHub login failed. Please try again.", "error")
    return redirect(url_for('login'))

@app.before_request
def fetch_portfolios():
    if 'user_id' in session and mysql:
        try:
            cur = mysql.connection.cursor()
            cur.execute(
                "SELECT id, name, base_currency FROM portfolios WHERE user_id = %s ORDER BY is_default DESC, id ASC",
                [session['user_id']]
            )
            portfolios = cur.fetchall()
            cur.close()
            session['portfolios'] = [{'id': p[0], 'name': p[1], 'currency': p[2]} for p in portfolios]

            if 'portfolio_id' not in session and portfolios:
                session['portfolio_id']       = portfolios[0][0]
                session['portfolio_name']     = portfolios[0][1]
                session['portfolio_currency'] = portfolios[0][2]
        except Exception as e:
            print("DB error fetching portfolios:", e)

# -------------------------------------------------------------
# Auth Routes
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not mysql:
            flash("Database connection error.", "error")
            return render_template('login.html')
            
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, first_name, last_name, password_hash FROM users WHERE email = %s", [email])
        user = cur.fetchone()
        cur.close()
        
        if user and check_password_hash(user[3], password):
            session['user_id'] = user[0]
            session['user_name'] = f"{user[1]} {user[2]}".strip()
            flash("Login successful! Redirecting...", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Please check your credentials", "error")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name', 'User')
        last_name = request.form.get('last_name', '')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        if password != confirm:
            flash("Passwords do not match", "error")
        elif not mysql:
            flash("Database connection error.", "error")
        else:
            cur = mysql.connection.cursor()
            cur.execute("SELECT id FROM users WHERE email = %s", [email])
            if cur.fetchone():
                flash("Email already registered", "error")
                cur.close()
            else:
                hashed = generate_password_hash(password)
                cur.execute("INSERT INTO users(first_name, last_name, email, password_hash) VALUES(%s, %s, %s, %s)", 
                            (first_name, last_name, email, hashed))
                mysql.connection.commit()
                user_id = cur.lastrowid
                cur.close()
                
                session['user_id'] = user_id
                session['user_name'] = f"{first_name} {last_name}".strip()
                flash("Account created successfully!", "success")
                return redirect(url_for('setup', step=1))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -------------------------------------------------------------
# Setup Routes
# -------------------------------------------------------------
@app.route('/setup/<int:step>', methods=['GET', 'POST'])
@login_required
def setup(step):
    if step not in [1, 2, 3]:
        return redirect(url_for('setup', step=1))
        
    if request.method == 'POST':
        if step == 1:
            # Save currency choice in session before moving on
            session['setup_currency'] = request.form.get('currency', 'INR')
            return redirect(url_for('setup', step=2))
        elif step == 2:
            session['setup_categories'] = request.form.getlist('categories') or ['stocks', 'crypto']
            return redirect(url_for('setup', step=3))
        else:
            portfolio_name  = request.form.get('portfolio_name', 'My Portfolio')
            description     = request.form.get('description', '')
            currency        = session.pop('setup_currency', 'INR')
            user_id         = session.get('user_id')
            if mysql and user_id:
                cur = mysql.connection.cursor()
                # Check if this is the user's first portfolio → mark as default
                cur.execute("SELECT COUNT(*) FROM portfolios WHERE user_id = %s", [user_id])
                is_default = 1 if cur.fetchone()[0] == 0 else 0
                cur.execute(
                    "INSERT INTO portfolios (user_id, name, description, base_currency, is_default) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, portfolio_name, description or None, currency, is_default)
                )
                mysql.connection.commit()
                portfolio_id = cur.lastrowid
                cur.close()
                session['portfolio_id']       = portfolio_id
                session['portfolio_name']     = portfolio_name
                session['portfolio_currency'] = currency
                flash(f'Portfolio "{portfolio_name}" created!', "success")
            else:
                flash("Database connection error.", "error")
            return redirect(url_for('dashboard'))
            
    return render_template('setup.html', step=step)

# -------------------------------------------------------------
# Dashboard Route
# -------------------------------------------------------------
@app.route('/switch_portfolio/<int:index>')
@login_required
def switch_portfolio(index):
    portfolios = session.get('portfolios', [])
    if 0 <= index < len(portfolios):
        session['portfolio_id']       = portfolios[index]['id']
        session['portfolio_name']     = portfolios[index]['name']
        session['portfolio_currency'] = portfolios[index].get('currency', 'INR')
    return redirect(url_for('dashboard'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    portfolio_id = session.get('portfolio_id')
    user_id = session.get('user_id')
    currency = session.get('portfolio_currency', 'INR')
    currency_symbol = CURRENCY_SYMBOLS.get(currency, '₹')

    holdings = []
    recent_transactions = []
    allocation_data = {}   # {category: total_value}
    portfolio = {
        'name': session.get('portfolio_name', 'My Portfolio'),
        'total_value': 0.0,
        'total_gain': 0.0,
        'total_invested': 0.0,
        'todays_pl': 0.0,
        'currency_symbol': currency_symbol,
    }

    if mysql and portfolio_id:
        cur = mysql.connection.cursor()

        # Recent transactions
        cur.execute("""
            SELECT type, asset_symbol, quantity, price, transaction_date
            FROM transactions
            WHERE portfolio_id = %s
            ORDER BY transaction_date DESC LIMIT 5
        """, [portfolio_id])
        for row in cur.fetchall():
            recent_transactions.append({
                "type": row[0], "symbol": row[1],
                "qty": float(row[2]), "price": float(row[3]),
                "date": row[4].strftime('%Y-%m-%d') if row[4] else '', "time": ""
            })

        # Aggregate holdings per symbol
        cur.execute("""
            SELECT asset_symbol, category,
                   SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) AS total_qty,
                   SUM(CASE WHEN type='buy' THEN price * quantity ELSE 0 END) /
                   NULLIF(SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost
            FROM transactions
            WHERE portfolio_id = %s
            GROUP BY asset_symbol, category
            HAVING total_qty > 0
        """, [portfolio_id])
        rows = cur.fetchall()
        cur.close()

        # Fetch live prices for all unique symbols in one batch
        symbols = [r[0] for r in rows]
        live_prices = {sym: get_live_price(sym) for sym in symbols}

        for row in rows:
            symbol = row[0]
            category = row[1].capitalize()
            qty = float(row[2])
            cost = float(row[3]) if row[3] else 0.0
            live_price = live_prices.get(symbol, 0.0)
            # Fall back to cost if live price unavailable
            current_price = live_price if live_price > 0 else cost

            value = current_price * qty
            invested = cost * qty
            gain = value - invested
            gain_pct = (gain / invested * 100) if invested > 0 else 0

            h = {
                "symbol": symbol,
                "name": symbol,
                "category": category,
                "price": current_price,
                "qty": qty,
                "cost": cost,
                "value": value,
                "gain": gain,
                "gain_pct": gain_pct,
                "is_positive": gain >= 0,
                "change7d": gain_pct,   # approximation
                "sparkline": [current_price * (1 + (i - 3) * 0.01) for i in range(7)],
            }

            portfolio['total_value'] += value
            portfolio['total_invested'] += invested
            portfolio['total_gain'] += gain
            allocation_data[category] = allocation_data.get(category, 0.0) + value
            holdings.append(h)

        # Today's P&L ≈ 0.5% random swing on total value (no intraday data without premium API)
        import random
        portfolio['todays_pl'] = portfolio['total_value'] * random.uniform(-0.005, 0.015)

    # Build allocation JSON for the chart
    alloc_labels = list(allocation_data.keys())
    alloc_values = [round(v / portfolio['total_value'] * 100, 1) if portfolio['total_value'] > 0 else 0
                    for v in allocation_data.values()]
    allocation_json = json.dumps({'labels': alloc_labels, 'values': alloc_values})
    
    return render_template(
        'dashboard.html',
        portfolio=portfolio,
        holdings=holdings,
        recent_transactions=recent_transactions,
        allocation_json=allocation_json,
    )

# -------------------------------------------------------------
# Add Entry Route
# -------------------------------------------------------------
@app.route('/add_entry', methods=['GET', 'POST'])
@login_required
def add_entry():
    if request.method == 'POST':
        asset       = request.form.get('asset_symbol', 'UNKNOWN').upper()
        asset_name  = request.form.get('asset_name', '').strip() or None
        tx_type     = request.form.get('tx_type', 'buy')
        try:
            qty   = float(request.form.get('quantity', 0))
            price = float(request.form.get('price', 0))
            fees  = float(request.form.get('fees', 0))
        except ValueError:
            qty, price, fees = 0.0, 0.0, 0.0

        date     = request.form.get('entry_date')
        category = request.form.get('category', 'stocks')
        notes    = request.form.get('notes', '')

        portfolio_id = session.get('portfolio_id')
        user_id      = session.get('user_id')

        if mysql and portfolio_id and qty > 0 and price > 0:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO transactions
                    (user_id, portfolio_id, type, asset_symbol, asset_name, category, quantity, price, fees, transaction_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, portfolio_id, tx_type, asset, asset_name, category, qty, price, fees, date, notes))
            mysql.connection.commit()
            cur.close()
            flash(f"Successfully recorded {tx_type} of {qty} {asset}", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Database error or invalid input. Portfolio may not be selected.", "error")

    return render_template('add_entry.html')

# -------------------------------------------------------------
# Secondary Pages Routes
# -------------------------------------------------------------
@app.route('/holdings')
@login_required
def holdings():
    portfolio_id = session.get('portfolio_id')
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    holdings_list = []

    if mysql and portfolio_id:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT asset_symbol, category,
                   SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) AS total_qty,
                   SUM(CASE WHEN type='buy' THEN price * quantity ELSE 0 END) /
                   NULLIF(SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost,
                   COUNT(*) as tx_count
            FROM transactions
            WHERE portfolio_id = %s
            GROUP BY asset_symbol, category
            HAVING total_qty > 0
            ORDER BY category, asset_symbol
        """, [portfolio_id])
        rows = cur.fetchall()
        cur.close()
        symbols = [r[0] for r in rows]
        live_prices = {sym: get_live_price(sym) for sym in symbols}
        for row in rows:
            sym = row[0]; cat = row[1]; qty = float(row[2])
            cost = float(row[3]) if row[3] else 0.0
            tx_count = row[4]
            price = live_prices.get(sym, 0.0) or cost
            value = price * qty; invested = cost * qty
            gain = value - invested
            gain_pct = (gain / invested * 100) if invested > 0 else 0
            holdings_list.append({
                'symbol': sym, 'category': cat.capitalize(), 'qty': qty,
                'cost': cost, 'price': price, 'value': value,
                'invested': invested, 'gain': gain, 'gain_pct': gain_pct,
                'is_positive': gain >= 0, 'tx_count': tx_count
            })

    return render_template('holdings.html', holdings=holdings_list, currency_symbol=currency_symbol)

@app.route('/transactions')
@login_required
def transactions():
    portfolio_id    = session.get('portfolio_id')
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    txs = []
    if mysql and portfolio_id:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT type, asset_symbol, asset_name, category, quantity, price, fees, transaction_date, notes
            FROM transactions
            WHERE portfolio_id = %s
            ORDER BY transaction_date DESC
        """, [portfolio_id])
        for row in cur.fetchall():
            txs.append({
                "type"    : row[0],
                "symbol"  : row[1],
                "name"    : row[2] or row[1],
                "category": row[3],
                "qty"     : float(row[4]),
                "price"   : float(row[5]),
                "fees"    : float(row[6]),
                "total"   : float(row[4]) * float(row[5]) + float(row[6]),
                "date"    : row[7].strftime('%Y-%m-%d') if row[7] else '',
                "notes"   : row[8] or ''
            })
        cur.close()
    return render_template('transactions.html', transactions=txs, currency_symbol=currency_symbol)

@app.route('/analytics')
@login_required
def analytics():
    portfolio_id = session.get('portfolio_id')
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    allocation_json = json.dumps({'labels': [], 'values': []})

    if mysql and portfolio_id:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT asset_symbol, category,
                   SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) AS total_qty,
                   SUM(CASE WHEN type='buy' THEN price * quantity ELSE 0 END) /
                   NULLIF(SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost
            FROM transactions
            WHERE portfolio_id = %s
            GROUP BY asset_symbol, category
            HAVING total_qty > 0
        """, [portfolio_id])
        rows = cur.fetchall()
        cur.close()
        alloc = {}
        total_val = 0.0
        for row in rows:
            sym = row[0]; cat = row[1].capitalize(); qty = float(row[2])
            cost = float(row[3]) if row[3] else 0.0
            price = get_live_price(sym) or cost
            value = price * qty
            alloc[cat] = alloc.get(cat, 0.0) + value
            total_val += value
        labels = list(alloc.keys())
        values = [round(v / total_val * 100, 1) if total_val > 0 else 0 for v in alloc.values()]
        allocation_json = json.dumps({'labels': labels, 'values': values})

    return render_template('analytics.html', allocation_json=allocation_json, currency_symbol=currency_symbol)

# -------------------------------------------------------------
# Profile Route
# -------------------------------------------------------------
@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user_id = session.get('user_id')

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name  = request.form.get('last_name', '').strip()
        phone      = request.form.get('phone', '').strip() or None

        if (first_name or last_name) and mysql:
            session['user_name'] = f"{first_name} {last_name}".strip()
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE users SET first_name=%s, last_name=%s, phone=%s WHERE id=%s",
                (first_name, last_name, phone, user_id)
            )
            mysql.connection.commit()
            cur.close()

        portfolio_name = request.form.get('portfolio_name')
        portfolio_desc = request.form.get('portfolio_description', '').strip() or None
        if portfolio_name and 'portfolio_id' in session and mysql:
            session['portfolio_name'] = portfolio_name
            cur = mysql.connection.cursor()
            cur.execute(
                "UPDATE portfolios SET name=%s, description=%s WHERE id=%s",
                (portfolio_name, portfolio_desc, session['portfolio_id'])
            )
            mysql.connection.commit()
            cur.close()

        flash('Profile updated successfully!', 'success')
        return redirect(url_for('edit_profile'))

    # Load fresh data from DB for the form
    user_data = {}
    if mysql and user_id:
        cur = mysql.connection.cursor()
        cur.execute("SELECT first_name, last_name, email, phone FROM users WHERE id=%s", [user_id])
        row = cur.fetchone()
        if row:
            user_data = {'first_name': row[0], 'last_name': row[1] or '', 'email': row[2], 'phone': row[3] or ''}
        # Also load portfolio description
        if 'portfolio_id' in session:
            cur.execute("SELECT name, description, base_currency FROM portfolios WHERE id=%s", [session['portfolio_id']])
            prow = cur.fetchone()
            if prow:
                user_data['portfolio_name']        = prow[0]
                user_data['portfolio_description'] = prow[1] or ''
                user_data['portfolio_currency']    = prow[2]
        cur.close()

    return render_template('edit_profile.html', **user_data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
