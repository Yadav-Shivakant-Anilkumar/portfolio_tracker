-- =============================================================
--  Vaultfolio V2 — Fresh Database Schema
-- =============================================================

CREATE DATABASE IF NOT EXISTS portfolio_tracker
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE portfolio_tracker;

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    full_name      VARCHAR(100) NOT NULL,
    email          VARCHAR(150) NOT NULL UNIQUE,
    phone          VARCHAR(20)  DEFAULT NULL,
    password_text  VARCHAR(255) NOT NULL, -- User requested 'no hash', using text for now (NOT RECOMMENDED)
    base_currency  VARCHAR(10)  NOT NULL DEFAULT 'INR',
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- Portfolios Table
CREATE TABLE IF NOT EXISTS portfolios (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    user_id        INT          NOT NULL,
    name           VARCHAR(100) NOT NULL,
    type           ENUM('Stock', 'Crypto', 'Cash', 'Other') NOT NULL,
    initial_capital DECIMAL(20,2) NOT NULL DEFAULT 0.00,
    current_pl     DECIMAL(20,2) NOT NULL DEFAULT 0.00,
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Transactions Table (for detailed CRUD tracking within each portfolio)
CREATE TABLE IF NOT EXISTS transactions (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    portfolio_id   INT          NOT NULL,
    amount         DECIMAL(20,2) NOT NULL,
    type           ENUM('Capital Add', 'Capital Withdraw', 'Profit', 'Loss') NOT NULL,
    notes          TEXT,
    tx_date        DATE         NOT NULL,
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
);
