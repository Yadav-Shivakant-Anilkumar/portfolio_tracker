from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
from flask_mysqldb import MySQL
import config
import json
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vaultfolio_v2_secret_key")

# MySQL Config
app.config['MYSQL_HOST']     = config.MYSQL_HOST
app.config['MYSQL_PORT']     = config.MYSQL_PORT
app.config['MYSQL_USER']     = config.MYSQL_USER
app.config['MYSQL_PASSWORD'] = config.MYSQL_PASSWORD
app.config['MYSQL_DB']       = config.MYSQL_DB

mysql = MySQL(app)

# -------------------------------------------------------------
# Startup Database Migrations & Seeding
# -------------------------------------------------------------
migration_done = False

@app.before_request
def run_migrations():
    global migration_done
    if not migration_done:
        try:
            cur = mysql.connection.cursor()
            
            # Check if is_admin column exists
            cur.execute("SHOW COLUMNS FROM users LIKE 'is_admin'")
            exists = cur.fetchone()
            
            if not exists:
                print("Migration: Adding 'is_admin' column to 'users' table...")
                cur.execute("ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0")
                mysql.connection.commit()
                print("Migration: 'is_admin' column added successfully.")
            
            # Seed default admin user if it doesn't exist
            cur.execute("SELECT id FROM users WHERE email = 'admin@vaultfolio.com'")
            admin_exists = cur.fetchone()
            if not admin_exists:
                print("Migration: Seeding default admin user...")
                cur.execute("""
                    INSERT INTO users (full_name, email, phone, password_text, base_currency, is_admin)
                    VALUES ('System Admin', 'admin@vaultfolio.com', '9999999999', 'admin@059', 'INR', 1)
                """)
                mysql.connection.commit()
                print("Migration: Default admin user seeded successfully.")
                
            cur.close()
            migration_done = True
        except Exception as e:
            print(f"Migration/Seeding warning: {e}")

# -------------------------------------------------------------
# Decorators & Helpers
# -------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'error')
            return redirect(url_for('login'))
        if session.get('is_admin') != 1:
            flash('Access denied. Administrator privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# -------------------------------------------------------------
# Auth Routes
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, full_name, password_text, is_admin FROM users WHERE email = %s", [email])
        user = cur.fetchone()
        cur.close()
        
        # User requested NO HASHING, so we check plain text
        if user and user[2] == password:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['is_admin'] = user[3]
            flash(f"Welcome back, {user[1]}!", "success")
            if user[3] == 1:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "error")
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        cur = mysql.connection.cursor()
        # Check if email exists
        cur.execute("SELECT id FROM users WHERE email = %s", [email])
        if cur.fetchone():
            flash("Email already registered.", "error")
            cur.close()
        else:
            cur.execute("INSERT INTO users (full_name, email, password_text, is_admin) VALUES (%s, %s, %s, 0)", 
                        (full_name, email, password))
            mysql.connection.commit()
            user_id = cur.lastrowid
            cur.close()
            
            session['user_id'] = user_id
            session['user_name'] = full_name
            session['is_admin'] = 0
            flash("Registration successful! Let's set up your profile.", "success")
            return redirect(url_for('setup_profile'))
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

# -------------------------------------------------------------
# Profile & Setup Routes
# -------------------------------------------------------------
@app.route('/setup_profile', methods=['GET', 'POST'])
@login_required
def setup_profile():
    if request.method == 'POST':
        currency = request.form.get('currency', 'INR')
        phone = request.form.get('phone')
        
        cur = mysql.connection.cursor()
        cur.execute("UPDATE users SET base_currency = %s, phone = %s WHERE id = %s", 
                    (currency, phone, session['user_id']))
        mysql.connection.commit()
        cur.close()
        
        flash("Profile updated! Now create your first portfolio tracker.", "success")
        return redirect(url_for('create_portfolio'))
        
    return render_template('setup_profile.html')

@app.route('/create_portfolio', methods=['GET', 'POST'])
@login_required
def create_portfolio():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        p_type = request.form.get('type')
        capital = float(request.form.get('capital', 0))
        pl_val = float(request.form.get('pl', 0))
        pl_type = request.form.get('pl_type', 'Profit')
        
        # Calculate signed P/L
        pl = -abs(pl_val) if pl_type == 'Loss' else abs(pl_val)
        
        cur = mysql.connection.cursor()
        
        # Check if portfolio with exact name already exists for this user (case-sensitive)
        cur.execute("SELECT id FROM portfolios WHERE user_id = %s AND BINARY name = %s", (session['user_id'], name))
        if cur.fetchone():
            flash(f"A portfolio named '{name}' already exists. Please choose a unique name.", "error")
            cur.close()
            return render_template('create_portfolio.html', 
                                   name=name, 
                                   p_type=p_type, 
                                   capital=capital, 
                                   pl=pl_val, 
                                   pl_type=pl_type)
        
        cur.execute("INSERT INTO portfolios (user_id, name, type, initial_capital, current_pl) VALUES (%s, %s, %s, %s, %s)",
                    (session['user_id'], name, p_type, capital, pl))
        mysql.connection.commit()
        cur.close()
        
        flash(f"Portfolio '{name}' created successfully!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('create_portfolio.html')

# -------------------------------------------------------------
# Main Dashboard & Portfolio CRUD
# -------------------------------------------------------------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    cur = mysql.connection.cursor()
    
    # Fetch all portfolios for the user
    cur.execute("SELECT id, name, type, initial_capital, current_pl FROM portfolios WHERE user_id = %s", [user_id])
    portfolios = []
    total_capital = 0
    total_pl = 0
    
    for row in cur.fetchall():
        p = {
            'id': row[0],
            'name': row[1],
            'type': row[2],
            'capital': float(row[3]),
            'pl': float(row[4]),
            'total_value': float(row[3] + row[4])
        }
        portfolios.append(p)
        total_capital += p['capital']
        total_pl += p['pl']
    
    cur.close()
    
    summary = {
        'total_capital': total_capital,
        'total_pl': total_pl,
        'total_value': total_capital + total_pl,
        'pl_pct': (total_pl / total_capital * 100) if total_capital > 0 else 0
    }
    
    return render_template('dashboard_v2.html', portfolios=portfolios, summary=summary)

@app.route('/portfolio/<int:id>')
@login_required
def view_portfolio(id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, name, type, initial_capital, current_pl FROM portfolios WHERE id = %s AND user_id = %s", 
                (id, session['user_id']))
    portfolio = cur.fetchone()
    
    if not portfolio:
        flash("Portfolio not found.", "error")
        return redirect(url_for('dashboard'))
        
    cur.execute("SELECT id, amount, type, notes, tx_date FROM transactions WHERE portfolio_id = %s ORDER BY tx_date DESC", [id])
    transactions = []
    for row in cur.fetchall():
        transactions.append({
            'id': row[0],
            'amount': float(row[1]),
            'type': row[2],
            'notes': row[3],
            'date': row[4].strftime('%Y-%m-%d')
        })
    cur.close()
    
    p_data = {
        'id': portfolio[0], 'name': portfolio[1], 'type': portfolio[2],
        'capital': float(portfolio[3]), 'pl': float(portfolio[4]),
        'total_value': float(portfolio[3] + portfolio[4])
    }
    
    return render_template('portfolio_detail.html', portfolio=p_data, transactions=transactions, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/portfolio/<int:id>/add_transaction', methods=['POST'])
@login_required
def add_transaction(id):
    amount = float(request.form.get('amount', 0))
    tx_type = request.form.get('type')
    notes = request.form.get('notes')
    date = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    cur = mysql.connection.cursor()
    # Insert transaction
    cur.execute("INSERT INTO transactions (portfolio_id, amount, type, notes, tx_date) VALUES (%s, %s, %s, %s, %s)",
                (id, amount, tx_type, notes, date))
    
    # Update portfolio totals
    if tx_type == 'Capital Add':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital + %s WHERE id = %s", (amount, id))
    elif tx_type == 'Capital Withdraw':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital - %s WHERE id = %s", (amount, id))
    elif tx_type == 'Profit':
        cur.execute("UPDATE portfolios SET current_pl = current_pl + %s WHERE id = %s", (amount, id))
    elif tx_type == 'Loss':
        cur.execute("UPDATE portfolios SET current_pl = current_pl - %s WHERE id = %s", (amount, id))
        
    mysql.connection.commit()
    cur.close()
    
    flash("Transaction recorded!", "success")
    return redirect(url_for('view_portfolio', id=id))

@app.route('/transaction/<int:tx_id>/edit', methods=['POST'])
@login_required
def edit_transaction(tx_id):
    new_amount = float(request.form.get('amount', 0))
    new_type   = request.form.get('type')
    new_notes  = request.form.get('notes')
    new_date   = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))

    cur = mysql.connection.cursor()

    # Fetch the original transaction to reverse its effect on the portfolio
    cur.execute("SELECT portfolio_id, amount, type FROM transactions WHERE id = %s", [tx_id])
    old_tx = cur.fetchone()

    if not old_tx:
        flash("Transaction not found.", "error")
        cur.close()
        return redirect(url_for('dashboard'))

    portfolio_id = old_tx[0]
    old_amount   = float(old_tx[1])
    old_type     = old_tx[2]

    # --- Reverse old transaction effect ---
    if old_type == 'Capital Add':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital - %s WHERE id = %s", (old_amount, portfolio_id))
    elif old_type == 'Capital Withdraw':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital + %s WHERE id = %s", (old_amount, portfolio_id))
    elif old_type == 'Profit':
        cur.execute("UPDATE portfolios SET current_pl = current_pl - %s WHERE id = %s", (old_amount, portfolio_id))
    elif old_type == 'Loss':
        cur.execute("UPDATE portfolios SET current_pl = current_pl + %s WHERE id = %s", (old_amount, portfolio_id))

    # --- Apply new transaction effect ---
    if new_type == 'Capital Add':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital + %s WHERE id = %s", (new_amount, portfolio_id))
    elif new_type == 'Capital Withdraw':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital - %s WHERE id = %s", (new_amount, portfolio_id))
    elif new_type == 'Profit':
        cur.execute("UPDATE portfolios SET current_pl = current_pl + %s WHERE id = %s", (new_amount, portfolio_id))
    elif new_type == 'Loss':
        cur.execute("UPDATE portfolios SET current_pl = current_pl - %s WHERE id = %s", (new_amount, portfolio_id))

    # --- Update the transaction record ---
    cur.execute(
        "UPDATE transactions SET amount = %s, type = %s, notes = %s, tx_date = %s WHERE id = %s",
        (new_amount, new_type, new_notes, new_date, tx_id)
    )

    mysql.connection.commit()
    cur.close()

    flash("Transaction updated successfully!", "success")
    return redirect(url_for('view_portfolio', id=portfolio_id))


@app.route('/transaction/<int:tx_id>/delete/<int:portfolio_id>', methods=['POST'])
@login_required
def delete_transaction(tx_id, portfolio_id):
    cur = mysql.connection.cursor()

    # Fetch the transaction to reverse its portfolio impact
    cur.execute("SELECT amount, type FROM transactions WHERE id = %s", [tx_id])
    tx = cur.fetchone()

    if not tx:
        flash("Transaction not found.", "error")
        cur.close()
        return redirect(url_for('view_portfolio', id=portfolio_id))

    amount  = float(tx[0])
    tx_type = tx[1]

    # --- Reverse the transaction's effect on portfolio ---
    if tx_type == 'Capital Add':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital - %s WHERE id = %s", (amount, portfolio_id))
    elif tx_type == 'Capital Withdraw':
        cur.execute("UPDATE portfolios SET initial_capital = initial_capital + %s WHERE id = %s", (amount, portfolio_id))
    elif tx_type == 'Profit':
        cur.execute("UPDATE portfolios SET current_pl = current_pl - %s WHERE id = %s", (amount, portfolio_id))
    elif tx_type == 'Loss':
        cur.execute("UPDATE portfolios SET current_pl = current_pl + %s WHERE id = %s", (amount, portfolio_id))

    # --- Delete the transaction ---
    cur.execute("DELETE FROM transactions WHERE id = %s", [tx_id])

    mysql.connection.commit()
    cur.close()

    flash("Transaction deleted and portfolio balance updated.", "info")
    return redirect(url_for('view_portfolio', id=portfolio_id))


@app.route('/portfolio/delete/<int:id>')
@login_required
def delete_portfolio(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM portfolios WHERE id = %s AND user_id = %s", (id, session['user_id']))
    mysql.connection.commit()
    cur.close()
    flash("Portfolio deleted.", "info")
    return redirect(url_for('dashboard'))

# -------------------------------------------------------------
# Settings & Profile
# -------------------------------------------------------------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user_id = session['user_id']
    cur = mysql.connection.cursor()
    
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        currency = request.form.get('currency')
        
        cur.execute("UPDATE users SET full_name = %s, phone = %s, base_currency = %s WHERE id = %s",
                    (full_name, phone, currency, user_id))
        mysql.connection.commit()
        session['user_name'] = full_name
        flash("Profile updated successfully!", "success")
        return redirect(url_for('edit_profile'))
    
    cur.execute("SELECT full_name, email, phone, base_currency FROM users WHERE id = %s", [user_id])
    user = cur.fetchone()
    cur.close()
    
    user_data = {'full_name': user[0], 'email': user[1], 'phone': user[2], 'currency': user[3]}
    return render_template('profile_v2.html', user=user_data)

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    old_pass = request.form.get('old_password')
    new_pass = request.form.get('new_password')
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT password_text FROM users WHERE id = %s", [session['user_id']])
    current_pass = cur.fetchone()[0]
    
    if current_pass == old_pass:
        cur.execute("UPDATE users SET password_text = %s WHERE id = %s", (new_pass, session['user_id']))
        mysql.connection.commit()
        flash("Password changed successfully!", "success")
    else:
        flash("Incorrect old password.", "error")
        
    cur.close()
    return redirect(url_for('edit_profile'))

# -------------------------------------------------------------
# Admin Routes
# -------------------------------------------------------------
@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    cur = mysql.connection.cursor()
    
    # 1. Total users
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    
    # 2. Total portfolios
    cur.execute("SELECT COUNT(*) FROM portfolios")
    total_portfolios = cur.fetchone()[0]
    
    # 3. Total invested capital and current P&L
    cur.execute("SELECT SUM(initial_capital), SUM(current_pl) FROM portfolios")
    totals = cur.fetchone()
    total_capital = float(totals[0] or 0)
    total_pl = float(totals[1] or 0)
    total_value = total_capital + total_pl
    
    # 4. Fetch all users with portfolio count, capital, and P&L
    cur.execute("""
        SELECT u.id, u.full_name, u.email, u.phone, u.base_currency, u.is_admin, u.created_at,
               COUNT(p.id) as portfolio_count,
               IFNULL(SUM(p.initial_capital), 0) as total_capital,
               IFNULL(SUM(p.current_pl), 0) as total_pl
        FROM users u
        LEFT JOIN portfolios p ON u.id = p.user_id
        GROUP BY u.id
        ORDER BY u.id ASC
    """)
    users_raw = cur.fetchall()
    users = []
    for row in users_raw:
        users.append({
            'id': row[0],
            'full_name': row[1],
            'email': row[2],
            'phone': row[3] or '-',
            'currency': row[4],
            'is_admin': row[5],
            'created_at': row[6].strftime('%Y-%m-%d %H:%M') if row[6] else '-',
            'portfolio_count': row[7],
            'capital': float(row[8]),
            'pl': float(row[9]),
            'total_value': float(row[8] + row[9])
        })
        
    cur.close()
    
    summary = {
        'total_users': total_users,
        'total_portfolios': total_portfolios,
        'total_capital': total_capital,
        'total_pl': total_pl,
        'total_value': total_value
    }
    
    return render_template('admin_dashboard.html', summary=summary, users=users)

@app.route('/admin/user/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def admin_user_detail(user_id):
    cur = mysql.connection.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_profile':
            full_name = request.form.get('full_name')
            phone = request.form.get('phone')
            currency = request.form.get('currency', 'INR')
            is_admin = int(request.form.get('is_admin', 0))
            
            cur.execute("UPDATE users SET full_name = %s, phone = %s, base_currency = %s, is_admin = %s WHERE id = %s",
                        (full_name, phone, currency, is_admin, user_id))
            mysql.connection.commit()
            flash("User profile updated successfully.", "success")
            
            # If editing own account, update session status
            if user_id == session['user_id']:
                session['user_name'] = full_name
                session['is_admin'] = is_admin
                if is_admin == 0:
                    cur.close()
                    return redirect(url_for('dashboard'))
                    
        elif action == 'change_password':
            new_password = request.form.get('new_password')
            if new_password:
                cur.execute("UPDATE users SET password_text = %s WHERE id = %s", (new_password, user_id))
                mysql.connection.commit()
                flash("User password updated successfully.", "success")
                
        return redirect(url_for('admin_user_detail', user_id=user_id))
    
    # GET request: fetch user profile
    cur.execute("SELECT id, full_name, email, phone, password_text, base_currency, is_admin, created_at FROM users WHERE id = %s", [user_id])
    user_row = cur.fetchone()
    if not user_row:
        flash("User not found.", "error")
        cur.close()
        return redirect(url_for('admin_dashboard'))
        
    user = {
        'id': user_row[0],
        'full_name': user_row[1],
        'email': user_row[2],
        'phone': user_row[3] or '',
        'password': user_row[4],
        'currency': user_row[5],
        'is_admin': user_row[6],
        'created_at': user_row[7].strftime('%Y-%m-%d %H:%M') if user_row[7] else '-'
    }
    
    # Fetch user's portfolios
    cur.execute("SELECT id, name, type, initial_capital, current_pl FROM portfolios WHERE user_id = %s", [user_id])
    portfolios = []
    for row in cur.fetchall():
        portfolios.append({
            'id': row[0],
            'name': row[1],
            'type': row[2],
            'capital': float(row[3]),
            'pl': float(row[4]),
            'total_value': float(row[3] + row[4])
        })
        
    # Fetch recent transactions across user's portfolios
    cur.execute("""
        SELECT t.id, t.amount, t.type, t.notes, t.tx_date, p.name as portfolio_name
        FROM transactions t
        JOIN portfolios p ON t.portfolio_id = p.id
        WHERE p.user_id = %s
        ORDER BY t.tx_date DESC LIMIT 20
    """, [user_id])
    transactions = []
    for row in cur.fetchall():
        transactions.append({
            'id': row[0],
            'amount': float(row[1]),
            'type': row[2],
            'notes': row[3] or '-',
            'date': row[4].strftime('%Y-%m-%d'),
            'portfolio_name': row[5]
        })
        
    cur.close()
    return render_template('admin_user_detail.html', user=user, portfolios=portfolios, transactions=transactions)

@app.route('/admin/user/<int:user_id>/delete')
@admin_required
def admin_delete_user(user_id):
    if user_id == session['user_id']:
        flash("You cannot delete your own admin account.", "error")
        return redirect(url_for('admin_dashboard'))
        
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", [user_id])
    mysql.connection.commit()
    cur.close()
    
    flash("User and all associated data have been permanently deleted.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/portfolios')
@admin_required
def admin_portfolios():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.type, p.initial_capital, p.current_pl, u.full_name, u.email
        FROM portfolios p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.id ASC
    """)
    portfolios = []
    for row in cur.fetchall():
        portfolios.append({
            'id': row[0],
            'name': row[1],
            'type': row[2],
            'capital': float(row[3]),
            'pl': float(row[4]),
            'total_value': float(row[3] + row[4]),
            'owner_name': row[5],
            'owner_email': row[6]
        })
    cur.close()
    return render_template('admin_portfolios.html', portfolios=portfolios)

@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT t.id, t.amount, t.type, t.notes, t.tx_date, p.name as portfolio_name, u.full_name, u.email
        FROM transactions t
        JOIN portfolios p ON t.portfolio_id = p.id
        JOIN users u ON p.user_id = u.id
        ORDER BY t.tx_date DESC, t.id DESC LIMIT 100
    """)
    transactions = []
    for row in cur.fetchall():
        transactions.append({
            'id': row[0],
            'amount': float(row[1]),
            'type': row[2],
            'notes': row[3] or '-',
            'date': row[4].strftime('%Y-%m-%d'),
            'portfolio_name': row[5],
            'owner_name': row[6],
            'owner_email': row[7]
        })
    cur.close()
    return render_template('admin_transactions.html', transactions=transactions)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
