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
app.config['MYSQL_USER']     = config.MYSQL_USER
app.config['MYSQL_PASSWORD'] = config.MYSQL_PASSWORD
app.config['MYSQL_DB']       = config.MYSQL_DB

mysql = MySQL(app)

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

# -------------------------------------------------------------
# Auth Routes
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, full_name, password_text FROM users WHERE email = %s", [email])
        user = cur.fetchone()
        cur.close()
        
        # User requested NO HASHING, so we check plain text
        if user and user[2] == password:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            flash(f"Welcome back, {user[1]}!", "success")
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
            cur.execute("INSERT INTO users (full_name, email, password_text) VALUES (%s, %s, %s)", 
                        (full_name, email, password))
            mysql.connection.commit()
            user_id = cur.lastrowid
            cur.close()
            
            session['user_id'] = user_id
            session['user_name'] = full_name
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
        name = request.form.get('name')
        p_type = request.form.get('type')
        capital = float(request.form.get('capital', 0))
        pl = float(request.form.get('pl', 0))
        
        cur = mysql.connection.cursor()
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
    
    return render_template('portfolio_detail.html', portfolio=p_data, transactions=transactions)

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
