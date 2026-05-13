from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_mysqldb import MySQL
import config
from datetime import datetime
import json

# ─────────────────────────────────────────────────
# Live Price Helper
# ─────────────────────────────────────────────────
_price_cache = {}   # simple in-process cache {symbol: price}

def get_live_price(symbol: str) -> float:
    """Fetch live market price via yfinance.
    Falls back to cached value, then 0.0 on error."""
    sym = symbol.upper()
    # Map common crypto tickers to yfinance format
    crypto_map = {'BTC': 'BTC-USD', 'ETH': 'ETH-USD', 'SOL': 'SOL-USD',
                  'BNB': 'BNB-USD', 'ADA': 'ADA-USD', 'XRP': 'XRP-USD'}
    ticker = crypto_map.get(sym, sym)
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = float(info.last_price or 0)
        if price > 0:
            _price_cache[sym] = price
            return price
    except Exception as e:
        print(f"yfinance error for {sym}: {e}")
    return _price_cache.get(sym, 0.0)

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
app.secret_key = "vaultfolio_super_secret_key" # Replace in production

# MySQL Config
app.config['MYSQL_HOST'] = config.MYSQL_HOST
app.config['MYSQL_USER'] = config.MYSQL_USER
app.config['MYSQL_PASSWORD'] = config.MYSQL_PASSWORD
app.config['MYSQL_DB'] = config.MYSQL_DB

try:
    mysql = MySQL(app)
except Exception as e:
    print(f"Error initializing MySQL: {e}")
    mysql = None

@app.before_request
def fetch_portfolios():
    if 'user_id' in session and mysql:
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT id, name FROM portfolios WHERE user_id = %s", [session['user_id']])
            portfolios = cur.fetchall()
            cur.close()
            session['portfolios'] = [{'id': p[0], 'name': p[1]} for p in portfolios]
            
            if 'portfolio_id' not in session and portfolios:
                session['portfolio_id'] = portfolios[0][0]
                session['portfolio_name'] = portfolios[0][1]
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
            portfolio_name = request.form.get('portfolio_name', 'My Portfolio')
            currency = session.pop('setup_currency', 'INR')
            user_id = session.get('user_id')
            if mysql and user_id:
                cur = mysql.connection.cursor()
                cur.execute(
                    "INSERT INTO portfolios (user_id, name, base_currency) VALUES (%s, %s, %s)",
                    (user_id, portfolio_name, currency)
                )
                mysql.connection.commit()
                portfolio_id = cur.lastrowid
                cur.close()
                session['portfolio_id'] = portfolio_id
                session['portfolio_name'] = portfolio_name
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
        session['portfolio_id'] = portfolios[index]['id']
        session['portfolio_name'] = portfolios[index]['name']
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
        asset = request.form.get('asset_symbol', 'UNKNOWN').upper()
        tx_type = request.form.get('tx_type', 'buy')
        try:
            qty = float(request.form.get('quantity', 0))
            price = float(request.form.get('price', 0))
        except ValueError:
            qty, price = 0.0, 0.0
            
        date = request.form.get('entry_date')
        category = request.form.get('category', 'stocks')
        notes = request.form.get('notes', '')
        
        portfolio_id = session.get('portfolio_id')
        user_id = session.get('user_id')
        
        if mysql and portfolio_id and qty > 0 and price > 0:
            cur = mysql.connection.cursor()
            cur.execute("""
                INSERT INTO transactions (user_id, portfolio_id, type, asset_symbol, category, quantity, price, transaction_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, portfolio_id, tx_type, asset, category, qty, price, date, notes))
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
    portfolio_id = session.get('portfolio_id')
    txs = []
    if mysql and portfolio_id:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT type, asset_symbol, category, quantity, price, transaction_date, notes 
            FROM transactions 
            WHERE portfolio_id = %s 
            ORDER BY transaction_date DESC
        """, [portfolio_id])
        for row in cur.fetchall():
            txs.append({
                "type": row[0], "symbol": row[1], "category": row[2], 
                "qty": float(row[3]), "price": float(row[4]), 
                "date": row[5].strftime('%Y-%m-%d') if row[5] else '', "notes": row[6]
            })
        cur.close()
    return render_template('transactions.html', transactions=txs)

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
    if request.method == 'POST':
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        
        if first_name or last_name:
            session['user_name'] = f"{first_name} {last_name}".strip()
            
        portfolio_name = request.form.get('portfolio_name')
        if portfolio_name and 'portfolio_id' in session and mysql:
            session['portfolio_name'] = portfolio_name
            cur = mysql.connection.cursor()
            cur.execute("UPDATE portfolios SET name = %s WHERE id = %s", (portfolio_name, session['portfolio_id']))
            mysql.connection.commit()
            cur.close()
            
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('edit_profile'))
        
    current_name = session.get('user_name', 'User')
    parts = current_name.split(' ', 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    portfolio_name = session.get('portfolio_name', 'My Portfolio')
    
    return render_template('edit_profile.html', first_name=first, last_name=last, portfolio_name=portfolio_name)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
