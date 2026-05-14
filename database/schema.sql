-- =============================================================
--  Portfolio Tracker — Full Database Schema (Fresh Install)
--  Generated: 2026-05-14
--  Drop & recreate everything cleanly.
-- =============================================================

CREATE DATABASE IF NOT EXISTS portfolio_tracker
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE portfolio_tracker;

-- =============================================================
-- TABLE: users
-- Stores registered user accounts with secure password hashes.
-- =============================================================
CREATE TABLE IF NOT EXISTS users (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    first_name     VARCHAR(50)  NOT NULL,
    last_name      VARCHAR(50)  DEFAULT '',
    email          VARCHAR(150) NOT NULL UNIQUE,
    phone          VARCHAR(20)  DEFAULT NULL,           -- optional phone number
    password_hash  VARCHAR(255) NOT NULL,
    profile_pic_url VARCHAR(500) DEFAULT NULL,          -- optional avatar URL
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- =============================================================
-- TABLE: portfolios
-- Each user can have multiple named portfolios.
-- =============================================================
CREATE TABLE IF NOT EXISTS portfolios (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    user_id        INT          NOT NULL,
    name           VARCHAR(100) NOT NULL DEFAULT 'My Portfolio',
    description    TEXT         DEFAULT NULL,            -- optional portfolio notes
    base_currency  VARCHAR(10)  NOT NULL DEFAULT 'INR',  -- INR, USD, EUR, GBP …
    is_default     TINYINT(1)   NOT NULL DEFAULT 0,      -- 1 = user's primary portfolio
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- =============================================================
-- TABLE: transactions
-- Every buy/sell/dividend event recorded by the user.
-- =============================================================
CREATE TABLE IF NOT EXISTS transactions (
    id               INT PRIMARY KEY AUTO_INCREMENT,
    user_id          INT          NOT NULL,             -- kept for fast per-user queries
    portfolio_id     INT          NOT NULL,
    type             ENUM('buy', 'sell', 'dividend') NOT NULL,
    asset_symbol     VARCHAR(20)  NOT NULL,             -- e.g. AAPL, BTC, ETH
    asset_name       VARCHAR(100) DEFAULT NULL,         -- friendly name e.g. "Apple Inc."
    category         VARCHAR(50)  NOT NULL DEFAULT 'stocks', -- stocks, crypto, etf, mutual_fund …
    quantity         DECIMAL(20,8) NOT NULL,            -- supports fractional crypto
    price            DECIMAL(20,8) NOT NULL,            -- 8dp supports micro-price coins (SHIB etc.)
    fees             DECIMAL(15,4) NOT NULL DEFAULT 0,  -- brokerage/gas fees
    transaction_date DATE         NOT NULL,
    notes            TEXT         DEFAULT NULL,
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)      REFERENCES users(id)      ON DELETE CASCADE,
    FOREIGN KEY (portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
);

-- Performance indexes for the most common query patterns
CREATE INDEX idx_tx_portfolio        ON transactions (portfolio_id);
CREATE INDEX idx_tx_portfolio_symbol ON transactions (portfolio_id, asset_symbol);
CREATE INDEX idx_tx_user             ON transactions (user_id);
CREATE INDEX idx_tx_date             ON transactions (transaction_date);
CREATE INDEX idx_tx_type             ON transactions (type);

-- =============================================================
-- TABLE: watchlist
-- Symbols the user wants to track without owning them.
-- =============================================================
CREATE TABLE IF NOT EXISTS watchlist (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    user_id        INT          NOT NULL,
    asset_symbol   VARCHAR(20)  NOT NULL,
    asset_name     VARCHAR(100) DEFAULT NULL,
    category       VARCHAR(50)  NOT NULL DEFAULT 'stocks',
    target_price   DECIMAL(20,8) DEFAULT NULL,          -- optional price alert target
    notes          TEXT         DEFAULT NULL,
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_watchlist_user_symbol (user_id, asset_symbol),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_watchlist_user ON watchlist (user_id);

-- =============================================================
-- TABLE: price_cache
-- Stores the last known live prices fetched via yfinance.
-- Avoids hammering the API on every page load.
-- =============================================================
CREATE TABLE IF NOT EXISTS price_cache (
    asset_symbol   VARCHAR(20)  PRIMARY KEY,
    last_price     DECIMAL(20,8) NOT NULL DEFAULT 0,
    currency       VARCHAR(10)  NOT NULL DEFAULT 'USD',
    fetched_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- =============================================================
-- TABLE: oauth_providers
-- Links external OAuth accounts (Google, GitHub) to local users.
-- =============================================================
CREATE TABLE IF NOT EXISTS oauth_providers (
    id               INT PRIMARY KEY AUTO_INCREMENT,
    user_id          INT          NOT NULL,
    provider         VARCHAR(30)  NOT NULL,              -- 'google' or 'github'
    provider_user_id VARCHAR(255) NOT NULL,              -- ID from the OAuth provider
    provider_email   VARCHAR(150) DEFAULT NULL,          -- email returned by provider
    access_token     TEXT         DEFAULT NULL,          -- stored for API calls (optional)
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_oauth_provider_user (provider, provider_user_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_oauth_user ON oauth_providers (user_id);
