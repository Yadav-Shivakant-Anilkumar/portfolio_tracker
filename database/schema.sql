-- Create the database if it doesn't exist
CREATE DATABASE IF NOT EXISTS portfolio_tracker;
USE portfolio_tracker;

-- Table for user preferences/settings
CREATE TABLE IF NOT EXISTS portfolio_settings (
    id INT PRIMARY KEY AUTO_INCREMENT,
    start_date DATE,
    invested_amount DECIMAL(15,2),
    initial_pl DECIMAL(15,2)
);

-- Table for daily performance entries
CREATE TABLE IF NOT EXISTS daily_entries (
    id INT PRIMARY KEY AUTO_INCREMENT,
    entry_date DATE,
    daily_pl DECIMAL(15,2)
);

-- Optional: Tables for multi-user and individual transactions (for future expansion)
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    email VARCHAR(100) UNIQUE,
    password_hash VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT,
    type ENUM('buy', 'sell', 'dividend'),
    asset_symbol VARCHAR(20),
    category VARCHAR(50),
    quantity DECIMAL(18,8),
    price DECIMAL(15,2),
    transaction_date DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
