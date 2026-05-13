from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_mysqldb import MySQL
import config
from datetime import datetime

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

# -------------------------------------------------------------
# Auth Routes
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Simple mock login
        email = request.form.get('email')
        password = request.form.get('password')
        if email and len(password) >= 6:
            session['user_id'] = 1 # mock user id
            flash("Login successful! Redirecting...", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Please check your credentials", "error")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Simple mock register
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        if password != confirm:
            flash("Passwords do not match", "error")
        else:
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
def setup(step):
    if step not in [1, 2, 3]:
        return redirect(url_for('setup', step=1))
        
    if request.method == 'POST':
        if step < 3:
            return redirect(url_for('setup', step=step+1))
        else:
            portfolio_name = request.form.get('portfolio_name', 'My Portfolio')
            session['portfolio_name'] = portfolio_name
            flash(f'Portfolio "{portfolio_name}" created!', "success")
            return redirect(url_for('dashboard'))
            
    return render_template('setup.html', step=step)

# -------------------------------------------------------------
# Dashboard Route
# -------------------------------------------------------------
@app.route('/')
@app.route('/dashboard')
def dashboard():
    # If using real DB, uncomment and implement the logic from Tracker.txt
    '''
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM portfolio_settings LIMIT 1")
    settings = cur.fetchone()
    # calculate total, PL, etc.
    '''
    
    # Passing mock context data to render the premium dashboard layout
    portfolio = {
        'name': session.get('portfolio_name', 'My Portfolio'),
        'total_value': 124859.43,
        'total_gain': 13842.17,
        'todays_pl': 387.22
    }
    
    holdings = [
        {"symbol": "AAPL", "name": "Apple Inc.", "category": "Stocks", "price": 189.84, "qty": 50, "cost": 172.30, "change7d": 3.2, "sparkline": [180,182,179,185,187,186,189]},
        {"symbol": "BTC", "name": "Bitcoin", "category": "Crypto", "price": 67432.10, "qty": 0.5, "cost": 58200.00, "change7d": 5.8, "sparkline": [62000,63500,64800,64200,66100,66800,67432]},
        {"symbol": "MSFT", "name": "Microsoft Corp.", "category": "Stocks", "price": 415.26, "qty": 20, "cost": 380.50, "change7d": 1.4, "sparkline": [408,410,407,412,413,414,415]},
        {"symbol": "GOOGL", "name": "Alphabet Inc.", "category": "Stocks", "price": 155.72, "qty": 80, "cost": 140.10, "change7d": -0.8, "sparkline": [157,156,154,153,155,156,155]},
        {"symbol": "ETH", "name": "Ethereum", "category": "Crypto", "price": 3521.80, "qty": 5, "cost": 3100.00, "change7d": 4.1, "sparkline": [3380,3420,3390,3450,3480,3500,3521]},
    ]
    
    # Calculate values and gains for holdings
    for h in holdings:
        h['value'] = h['price'] * h['qty']
        h['gain'] = (h['price'] - h['cost']) * h['qty']
        h['gain_pct'] = (h['price'] - h['cost']) / h['cost'] * 100
        h['is_positive'] = h['gain'] >= 0
    
    recent_transactions = [
        {"type": "buy", "symbol": "SOL", "qty": 10, "price": 168.50, "date": "2024-12-18", "time": "14:32"},
        {"type": "sell", "symbol": "NVDA", "qty": 5, "price": 495.20, "date": "2024-12-17", "time": "09:15"},
        {"type": "buy", "symbol": "AAPL", "qty": 10, "price": 185.40, "date": "2024-12-16", "time": "16:45"},
    ]
    
    return render_template(
        'dashboard.html', 
        portfolio=portfolio,
        holdings=holdings,
        recent_transactions=recent_transactions
    )

# -------------------------------------------------------------
# Add Entry Route
# -------------------------------------------------------------
@app.route('/add_entry', methods=['GET', 'POST'])
def add_entry():
    if request.method == 'POST':
        # Logic to save to database from Tracker.txt
        '''
        entry_date = request.form.get('entry_date')
        daily_pl = request.form.get('daily_pl') # or calculate from asset tx
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO daily_entries(entry_date, daily_pl) VALUES(%s, %s)", (entry_date, daily_pl))
        mysql.connection.commit()
        cur.close()
        '''
        
        # For mock UI
        asset = request.form.get('asset_symbol', 'Unknown')
        tx_type = request.form.get('tx_type', 'buy')
        qty = request.form.get('quantity', 0)
        flash(f"Successfully recorded {tx_type} of {qty} {asset}", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('add_entry.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
