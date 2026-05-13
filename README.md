# Vaultfolio Portfolio Tracker

A premium, database-backed portfolio tracker built with Flask, MySQL, and Tailwind CSS.

## Features
- Premium dynamic UI built with Tailwind CSS and Glassmorphism
- Dashboard with performance charts and allocation distribution
- Add daily entries and transactions
- Interactive asset search and real-time P&L calculations
- Multi-step setup wizard and authentication UI pages

## Prerequisites
- Python 3.8+
- MySQL Server

## Setup Instructions

1. **Install Dependencies**
   Navigate to the `portfolio_tracker` directory and install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Database**
   - Create a MySQL database named `portfolio_tracker`.
   - Run the SQL script located at `database/schema.sql` to create the necessary tables.
   - Update `config.py` with your MySQL credentials (username and password).

3. **Run the Application**
   Start the Flask development server:
   ```bash
   python app.py
   ```
   *(Note: You will see a warning that says "This is a development server." This is completely normal and means your app is running perfectly!)*

4. **Access the App**
   Open your browser and navigate to `http://127.0.0.1:5000/`

## Project Structure
- `app.py`: Main Flask application handling routes and logic.
- `config.py`: Database configuration parameters.
- `database/schema.sql`: MySQL table definitions.
- `templates/`: Jinja2 HTML templates for the UI.
