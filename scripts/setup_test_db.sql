-- =============================================================================
-- Test database setup — run this as the PostgreSQL superuser (postgres) ONCE.
-- Usage: psql -U postgres -f scripts/setup_test_db.sql
-- =============================================================================

-- Create the application role (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'buddy_bet_app') THEN
        CREATE ROLE buddy_bet_app WITH LOGIN PASSWORD 'buddy_bet_local';
    END IF;
END
$$;

-- Create the test database (idempotent via DO block)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'buddy_bet_test') THEN
        PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE buddy_bet_test OWNER buddy_bet_app');
    END IF;
END
$$;

-- Grant privileges (safe to run multiple times)
GRANT ALL PRIVILEGES ON DATABASE buddy_bet_test TO buddy_bet_app;
