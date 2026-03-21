-- =============================================================================
-- Test database setup (simple version) — run as PostgreSQL superuser.
-- Usage: psql -U postgres -f scripts/setup_test_db_simple.sql
-- =============================================================================

-- 1. Create the application role
CREATE ROLE buddy_bet_app WITH LOGIN PASSWORD 'buddy_bet_local';

-- 2. Create the test database
CREATE DATABASE buddy_bet_test OWNER buddy_bet_app;

-- 3. Grant all privileges
GRANT ALL PRIVILEGES ON DATABASE buddy_bet_test TO buddy_bet_app;
