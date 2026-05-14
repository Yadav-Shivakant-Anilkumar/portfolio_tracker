from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_mysqldb import MySQL
import config
from datetime import datetime, timedelta
import json
import os
import requests

# ─────────────────────────────────────────────────
# 1. App Initialization & Config
# ─────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vaultfolio_super_secret_key_change_in_prod")

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
# 2. Constants & Decorators
# ─────────────────────────────────────────────────
CURRENCY_SYMBOLS = {'INR': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£', 'BTC': '₿'}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ─────────────────────────────────────────────────
# 3. Core Logic Helpers
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
    crypto_map = {'BTC': 'BTC-USD', 'ETH': 'ETH-USD', 'SOL': 'SOL-USD',
                  'BNB': 'BNB-USD', 'ADA': 'ADA-USD', 'XRP': 'XRP-USD'}
    ticker_sym = crypto_map.get(sym, sym)
    
    price = 0.0
    try:
        import yfinance as yf
        t = yf.Ticker(ticker_sym)
        info = t.fast_info
        price = float(info.last_price or 0)
        
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

# ─────────────────────────────────────────────────
# 4. Global Hooks
# ─────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────
# 5. API Routes
# ─────────────────────────────────────────────────
@app.route('/api/search_assets')
@login_required
def search_assets():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return json.dumps([])

    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        results = []
        for quote in data.get('quotes', []):
            quote_type = quote.get('quoteType', '')
            if quote_type not in ['EQUITY', 'CRYPTOCURRENCY', 'ETF', 'MUTUALFUND']:
                continue
                
            results.append({
                'symbol': quote.get('symbol'),
                'name': quote.get('shortname') or quote.get('longname') or quote.get('symbol'),
                'category': quote_type.lower(),
                'exchange': quote.get('exchDisp')
            })
            
        return json.dumps(results[:10])
    except Exception as e:
        print(f"Search API error: {e}")
        return json.dumps([])

@app.route('/api/get_price/<symbol>')
@login_required
def get_price_api(symbol):
    price = get_live_price(symbol)
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    return json.dumps({'price': price, 'symbol': currency_symbol})

# ─────────────────────────────────────────────────
# 6. Auth Routes
# ─────────────────────────────────────────────────
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
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid credentials", "error")
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

# ─────────────────────────────────────────────────
# 7. Portfolio & Transactions
# ─────────────────────────────────────────────────
@app.route('/setup/<int:step>', methods=['GET', 'POST'])
@login_required
def setup(step):
    if step not in [1, 2, 3]: return redirect(url_for('setup', step=1))
    if request.method == 'POST':
        if step == 1:
            session['setup_currency'] = request.form.get('currency', 'INR')
            return redirect(url_for('setup', step=2))
        elif step == 2:
            session['setup_categories'] = request.form.getlist('categories')
            return redirect(url_for('setup', step=3))
        else:
            portfolio_name = request.form.get('portfolio_name', 'My Portfolio')
            desc = request.form.get('description', '')
            currency = session.pop('setup_currency', 'INR')
            user_id = session.get('user_id')
            if mysql and user_id:
                cur = mysql.connection.cursor()
                cur.execute("SELECT COUNT(*) FROM portfolios WHERE user_id = %s", [user_id])
                is_default = 1 if cur.fetchone()[0] == 0 else 0
                cur.execute(
                    "INSERT INTO portfolios (user_id, name, description, base_currency, is_default) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, portfolio_name, desc or None, currency, is_default)
                )
                mysql.connection.commit()
                session['portfolio_id'] = cur.lastrowid
                session['portfolio_name'] = portfolio_name
                session['portfolio_currency'] = currency
                cur.close()
            return redirect(url_for('dashboard'))
    return render_template('setup.html', step=step)

@app.route('/dashboard')
@app.route('/')
@login_required
def dashboard():
    portfolio_id = session.get('portfolio_id')
    currency = session.get('portfolio_currency', 'INR')
    currency_symbol = CURRENCY_SYMBOLS.get(currency, '₹')

    holdings, recent_transactions = [], []
    allocation_data = {}
    portfolio = {'name': session.get('portfolio_name', 'My Portfolio'), 'total_value': 0.0, 'total_gain': 0.0, 'total_invested': 0.0, 'todays_pl': 0.0, 'currency_symbol': currency_symbol}

    if mysql and portfolio_id:
        cur = mysql.connection.cursor()
        cur.execute("SELECT type, asset_symbol, quantity, price, transaction_date FROM transactions WHERE portfolio_id = %s ORDER BY transaction_date DESC LIMIT 5", [portfolio_id])
        for row in cur.fetchall():
            recent_transactions.append({"type": row[0], "symbol": row[1], "qty": float(row[2]), "price": float(row[3]), "date": row[4].strftime('%Y-%m-%d') if row[4] else ''})

        cur.execute("""
            SELECT asset_symbol, category,
                   SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) AS total_qty,
                   SUM(CASE WHEN type='buy' THEN price * quantity ELSE 0 END) / NULLIF(SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost
            FROM transactions WHERE portfolio_id = %s GROUP BY asset_symbol, category HAVING total_qty > 0
        """, [portfolio_id])
        rows = cur.fetchall()
        cur.close()

        for row in rows:
            sym, cat, qty, cost = row[0], row[1].capitalize(), float(row[2]), float(row[3] or 0)
            live_price = get_live_price(sym) or cost
            value, invested = live_price * qty, cost * qty
            gain = value - invested
            gain_pct = (gain / invested * 100) if invested > 0 else 0

            portfolio['total_value'] += value
            portfolio['total_invested'] += invested
            portfolio['total_gain'] += gain
            allocation_data[cat] = allocation_data.get(cat, 0.0) + value
            holdings.append({"symbol": sym, "category": cat, "price": live_price, "qty": qty, "cost": cost, "value": value, "gain": gain, "gain_pct": gain_pct, "is_positive": gain >= 0})

    alloc_labels = list(allocation_data.keys())
    alloc_values = [round(v / portfolio['total_value'] * 100, 1) if portfolio['total_value'] > 0 else 0 for v in allocation_data.values()]
    
    return render_template('dashboard.html', portfolio=portfolio, holdings=holdings, recent_transactions=recent_transactions, allocation_json=json.dumps({'labels': alloc_labels, 'values': alloc_values}))

@app.route('/add_entry', methods=['GET', 'POST'])
@login_required
def add_entry():
    if request.method == 'POST':
        asset = request.form.get('asset_symbol', 'UNKNOWN').upper()
        name = request.form.get('asset_name', '').strip() or None
        tx_type = request.form.get('tx_type', 'buy')
        try:
            qty, price, fees = float(request.form.get('quantity', 0)), float(request.form.get('price', 0)), float(request.form.get('fees', 0))
        except: qty, price, fees = 0, 0, 0
        
        date, cat, notes = request.form.get('entry_date'), request.form.get('category', 'stocks'), request.form.get('notes', '')
        pid, uid = session.get('portfolio_id'), session.get('user_id')

        if mysql and pid and qty > 0:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO transactions (user_id, portfolio_id, type, asset_symbol, asset_name, category, quantity, price, fees, transaction_date, notes) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                        (uid, pid, tx_type, asset, name, cat, qty, price, fees, date, notes))
            mysql.connection.commit()
            cur.close()
            flash(f"Recorded {tx_type} of {asset}", "success")
            return redirect(url_for('dashboard'))
    return render_template('add_entry.html')

@app.route('/holdings')
@login_required
def holdings():
    # Similar to dashboard logic but for the full list
    portfolio_id = session.get('portfolio_id')
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    holdings_list = []
    if mysql and portfolio_id:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT asset_symbol, category,
                   SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) AS total_qty,
                   SUM(CASE WHEN type='buy' THEN price * quantity ELSE 0 END) / NULLIF(SUM(CASE WHEN type='buy' THEN quantity ELSE 0 END), 0) AS avg_cost
            FROM transactions WHERE portfolio_id = %s GROUP BY asset_symbol, category HAVING total_qty > 0
        """, [portfolio_id])
        rows = cur.fetchall()
        cur.close()
        for row in rows:
            sym, cat, qty, cost = row[0], row[1].capitalize(), float(row[2]), float(row[3] or 0)
            price = get_live_price(sym) or cost
            value, invested = price * qty, cost * qty
            gain = value - invested
            gain_pct = (gain / invested * 100) if invested > 0 else 0
            holdings_list.append({'symbol': sym, 'category': cat, 'qty': qty, 'cost': cost, 'price': price, 'value': value, 'invested': invested, 'gain': gain, 'gain_pct': gain_pct, 'is_positive': gain >= 0})
    return render_template('holdings.html', holdings=holdings_list, currency_symbol=currency_symbol)

@app.route('/transactions')
@login_required
def transactions():
    pid = session.get('portfolio_id')
    currency_symbol = CURRENCY_SYMBOLS.get(session.get('portfolio_currency', 'INR'), '₹')
    txs = []
    if mysql and pid:
        cur = mysql.connection.cursor()
        cur.execute("SELECT type, asset_symbol, asset_name, category, quantity, price, fees, transaction_date, notes FROM transactions WHERE portfolio_id = %s ORDER BY transaction_date DESC", [pid])
        for r in cur.fetchall():
            txs.append({"type": r[0], "symbol": r[1], "name": r[2] or r[1], "category": r[3], "qty": float(r[4]), "price": float(r[5]), "fees": float(r[6]), "total": float(r[4])*float(r[5])+float(r[6]), "date": r[7].strftime('%Y-%m-%d') if r[7] else '', "notes": r[8] or ''})
        cur.close()
    return render_template('transactions.html', transactions=txs, currency_symbol=currency_symbol)

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    uid = session.get('user_id')
    if request.method == 'POST':
        f, l, p = request.form.get('first_name'), request.form.get('last_name'), request.form.get('phone')
        if mysql and uid:
            cur = mysql.connection.cursor()
            cur.execute("UPDATE users SET first_name=%s, last_name=%s, phone=%s WHERE id=%s", (f, l, p or None, uid))
            mysql.connection.commit()
            cur.close()
            session['user_name'] = f"{f} {l}".strip()
        flash('Profile updated!', 'success')
        return redirect(url_for('edit_profile'))
    
    user_data = {}
    if mysql and uid:
        cur = mysql.connection.cursor()
        cur.execute("SELECT first_name, last_name, email, phone FROM users WHERE id=%s", [uid])
        r = cur.fetchone()
        if r: user_data = {'first_name': r[0], 'last_name': r[1] or '', 'email': r[2], 'phone': r[3] or ''}
        cur.close()
    return render_template('edit_profile.html', **user_data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
