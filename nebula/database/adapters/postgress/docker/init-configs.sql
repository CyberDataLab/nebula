-- --------------------------------------------------
-- init_postgres.sql
-- --------------------------------------------------

-- 1) (Optional) If you need to create the database, uncomment:
-- CREATE DATABASE nebula;
-- \c nebula

-- 2) Users table
CREATE TABLE IF NOT EXISTS users (
    "user" TEXT PRIMARY KEY,
    password TEXT,
    role TEXT
);

-- 2) Nodes
CREATE TABLE IF NOT EXISTS nodes (
  uid TEXT PRIMARY KEY,
  idx TEXT,
  ip TEXT,
  port TEXT,
  role TEXT,
  neighbors TEXT[],
  timestamp TEXT,
  federation TEXT,
  round TEXT,
  scenario TEXT,
  hash TEXT,
  extras JSONB,
  malicious TEXT
);

-- Ensure column exists for pre-existing installations
ALTER TABLE IF EXISTS nodes
  ADD COLUMN IF NOT EXISTS extras JSONB;

-- Drop legacy columns for latitude/longitude if present
ALTER TABLE IF EXISTS nodes
  DROP COLUMN IF EXISTS latitude;
ALTER TABLE IF EXISTS nodes
  DROP COLUMN IF EXISTS longitude;

-- 3) Configs as JSONB
DROP INDEX IF EXISTS idx_configs_config_gin;
DROP TABLE IF EXISTS configs;
CREATE TABLE configs (
  id SERIAL PRIMARY KEY,
  config JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_configs_config_gin ON configs USING GIN (config);

-- 4) Scenarios table as JSONB
CREATE TABLE IF NOT EXISTS scenarios (
    name TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    status TEXT,
    start_time TEXT,
    end_time TEXT,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast JSONB queries on scenarios.config
CREATE INDEX IF NOT EXISTS idx_scenarios_config_gin
    ON scenarios USING GIN (config);

-- 5) Notes table
CREATE TABLE IF NOT EXISTS notes (
    scenario TEXT PRIMARY KEY,
    scenario_notes TEXT
);
