-- =============================================================================
-- Buddy Bet — Complete Database Schema for Supabase / PostgreSQL 14+
-- =============================================================================
-- This is the consolidated schema combining:
--   • schema.sql         v1.1  (base schema)
--   • migration 001      (matches: provider_name, last_synced_at)
--   • migration 002      (deposit_requests, withdrawal_requests tables)
--   • migration 003      (deposit_requests: checkout_url column)
--
-- HOW TO RUN IN SUPABASE
-- -----------------------------------------------
-- 1. Open your Supabase project → SQL Editor → New query
-- 2. Paste this entire file and click Run
-- 3. After the schema is created, insert your fee rates:
--      INSERT INTO fee_config (fee_type, rate, currency, effective_from)
--      VALUES
--        ('WINNER_FEE',    0.1000, 'ZAR', NOW()),
--        ('NO_WINNER_FEE', 0.0500, 'ZAR', NOW());
--
-- NOTES
-- -----------------------------------------------
-- • All monetary columns use DECIMAL(15,2) — never FLOAT.
-- • All timestamps are TIMESTAMPTZ (UTC-aware).
-- • Ledger tables are immutable — triggers block UPDATE/DELETE.
-- • The app manages its own auth (JWT). Supabase RLS is NOT enabled here.
-- • Run the entire script in one shot — it is idempotent via IF NOT EXISTS.
-- =============================================================================


-- =============================================================================
-- SECTION 0: EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- =============================================================================
-- SECTION 1: ENUM TYPES
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE user_status AS ENUM ('active', 'suspended', 'banned');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('user', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Shared outcome type for match results and bet predictions.
DO $$ BEGIN
    CREATE TYPE football_outcome AS ENUM ('home_win', 'away_win', 'draw');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE match_status AS ENUM (
        'scheduled', 'live', 'completed', 'postponed', 'cancelled', 'abandoned'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE bet_status AS ENUM (
        'OPEN', 'MATCHED', 'PENDING_SETTLEMENT', 'SETTLED',
        'CANCELLED', 'VOIDED', 'UNDER_REVIEW'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE settlement_outcome AS ENUM (
        'creator_wins', 'opponent_wins', 'no_winner', 'voided'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- User-side ledger entry types (includes migration 002 additions).
DO $$ BEGIN
    CREATE TYPE ledger_entry_type AS ENUM (
        'STAKE_LOCK',        -- Stake moved available → locked at bet creation/acceptance.
        'STAKE_UNLOCK',      -- Stake returned locked → available on cancellation.
        'VOID_REFUND',       -- Full stake returned locked → available on void.
        'SETTLEMENT_DEDUCT', -- Locked stake consumed at settlement.
        'PAYOUT_CREDIT',     -- Winner payout (90% of pool) credited to available.
        'REFUND_CREDIT',     -- No-winner refund (95% of stake) credited to available.
        'FEE_DEDUCT',        -- No-winner platform fee (5% of stake) deducted from locked.
        'DEPOSIT',           -- Funds added via payment provider.
        'WITHDRAWAL',        -- Funds removed via withdrawal request.
        'WITHDRAWAL_HOLD',   -- available → locked when withdrawal is requested.
        'WITHDRAWAL_RELEASE' -- locked → available on rejection / failure.
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE balance_field AS ENUM ('available', 'locked');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE ledger_direction AS ENUM ('credit', 'debit');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE ledger_reference_type AS ENUM (
        'bet', 'settlement', 'void', 'cancellation', 'deposit', 'withdrawal'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE platform_entry_type AS ENUM (
        'FEE_COLLECTION',           -- Fee collected when there is a winner (10% of pool).
        'FEE_COLLECTION_NO_WINNER'  -- Fee collected when there is no winner (5% per user).
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE settlement_path_type AS ENUM ('winner', 'no_winner');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE fee_type AS ENUM (
        'WINNER_FEE',    -- Rate applied when there is a winner. Default: 10%.
        'NO_WINNER_FEE'  -- Rate applied when there is no winner. Default: 5%.
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE bet_event_type AS ENUM (
        'CREATED', 'MATCHED', 'PENDING_SETTLEMENT', 'SETTLED',
        'CANCELLED', 'VOIDED', 'UNDER_REVIEW', 'ADMIN_OVERRIDE'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Migration 002: deposit and withdrawal status enums.
DO $$ BEGIN
    CREATE TYPE deposit_status AS ENUM (
        'pending', 'processing', 'completed', 'failed', 'cancelled'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE withdrawal_status AS ENUM (
        'pending', 'approved', 'processing', 'completed', 'failed', 'rejected'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- =============================================================================
-- SECTION 2: UTILITY FUNCTIONS
-- =============================================================================

-- Auto-update updated_at on any table that carries that column.
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- Raise an exception if any mutation (UPDATE or DELETE) is attempted on an
-- immutable table. Applied to ledger_entries, platform_ledger_entries, and
-- bet_events. Corrections must be made via compensating entries only.
CREATE OR REPLACE FUNCTION fn_prevent_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'Table "%" is immutable. Mutations are not permitted. '
        'Write a compensating entry instead. '
        '(operation=%, table=%)',
        TG_TABLE_NAME, TG_OP, TG_TABLE_NAME;
END;
$$;


-- =============================================================================
-- SECTION 3: CORE TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- users
-- One row per registered platform user. Includes both bettors and admins.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            UUID          NOT NULL DEFAULT gen_random_uuid(),
    email         VARCHAR(320)  NOT NULL,
    phone_number  VARCHAR(30),
    display_name  VARCHAR(100)  NOT NULL,
    password_hash TEXT          NOT NULL,
    role          user_role     NOT NULL DEFAULT 'user',
    status        user_status   NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_users          PRIMARY KEY (id),
    CONSTRAINT uq_users_email    UNIQUE (email)
);

COMMENT ON TABLE  users                IS 'Platform user accounts. role controls access; status controls betting eligibility.';
COMMENT ON COLUMN users.password_hash  IS 'Bcrypt hash. Plain-text password is never stored or logged.';
COMMENT ON COLUMN users.status         IS 'active: normal. suspended: under review. banned: permanently blocked.';

CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- wallets
-- One wallet per user. available_balance + locked_balance = total (not stored).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wallets (
    id                UUID          NOT NULL DEFAULT gen_random_uuid(),
    user_id           UUID          NOT NULL,
    available_balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    locked_balance    DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    currency          CHAR(3)       NOT NULL DEFAULT 'ZAR',
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    version           INTEGER       NOT NULL DEFAULT 0,

    CONSTRAINT pk_wallets                       PRIMARY KEY (id),
    CONSTRAINT fk_wallets_user                  FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT uq_wallets_user                  UNIQUE (user_id),
    CONSTRAINT chk_wallets_available_non_negative CHECK (available_balance >= 0),
    CONSTRAINT chk_wallets_locked_non_negative    CHECK (locked_balance    >= 0)
);

COMMENT ON TABLE  wallets                   IS 'User wallet. available + locked = total balance. Ledger is authoritative; this is a read cache.';
COMMENT ON COLUMN wallets.available_balance IS 'Spendable/withdrawable funds.';
COMMENT ON COLUMN wallets.locked_balance    IS 'Funds reserved against active bets. Not spendable.';
COMMENT ON COLUMN wallets.version           IS 'Optimistic lock counter. Incremented on every balance update.';

DROP TRIGGER IF EXISTS trg_wallets_updated_at ON wallets;
CREATE TRIGGER trg_wallets_updated_at
    BEFORE UPDATE ON wallets
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- platform_accounts
-- Internal fee-collection accounts. One row per currency at MVP.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_accounts (
    id           UUID          NOT NULL DEFAULT gen_random_uuid(),
    account_code VARCHAR(100)  NOT NULL,
    name         VARCHAR(200)  NOT NULL,
    currency     CHAR(3)       NOT NULL,
    balance      DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    version      INTEGER       NOT NULL DEFAULT 0,

    CONSTRAINT pk_platform_accounts          PRIMARY KEY (id),
    CONSTRAINT uq_platform_accounts_code     UNIQUE (account_code),
    CONSTRAINT uq_platform_accounts_currency UNIQUE (currency),
    CONSTRAINT chk_platform_accounts_balance_non_negative CHECK (balance >= 0)
);

COMMENT ON TABLE  platform_accounts              IS 'Internal fee-collection accounts. One per currency at MVP.';
COMMENT ON COLUMN platform_accounts.account_code IS 'Stable app-readable identifier e.g. PLATFORM_FEES_ZAR. Do not change after go-live.';
COMMENT ON COLUMN platform_accounts.version      IS 'Optimistic lock counter.';

DROP TRIGGER IF EXISTS trg_platform_accounts_updated_at ON platform_accounts;
CREATE TRIGGER trg_platform_accounts_updated_at
    BEFORE UPDATE ON platform_accounts
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- matches
-- Local mirror of football fixture data. Includes migration 001 columns.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    id                   UUID             NOT NULL DEFAULT gen_random_uuid(),
    external_id          VARCHAR(200)     NOT NULL,
    home_team            VARCHAR(200)     NOT NULL,
    away_team            VARCHAR(200)     NOT NULL,
    competition          VARCHAR(200)     NOT NULL,
    kickoff_at           TIMESTAMPTZ      NOT NULL,
    status               match_status     NOT NULL DEFAULT 'scheduled',
    result_home_score    INTEGER,
    result_away_score    INTEGER,
    outcome              football_outcome,
    result_confirmed_at  TIMESTAMPTZ,
    -- Migration 001 columns:
    provider_name        VARCHAR(50),
    last_synced_at       TIMESTAMPTZ,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_matches                  PRIMARY KEY (id),
    CONSTRAINT uq_matches_external_id      UNIQUE (external_id),

    -- Scores must be set together or not at all.
    CONSTRAINT chk_matches_scores_both_or_neither
        CHECK (
            (result_home_score IS NULL AND result_away_score IS NULL)
            OR (result_home_score IS NOT NULL AND result_away_score IS NOT NULL)
        ),
    CONSTRAINT chk_matches_home_score_non_negative
        CHECK (result_home_score IS NULL OR result_home_score >= 0),
    CONSTRAINT chk_matches_away_score_non_negative
        CHECK (result_away_score IS NULL OR result_away_score >= 0),

    -- Outcome can only be set once scores are present.
    CONSTRAINT chk_matches_outcome_requires_scores
        CHECK (outcome IS NULL OR result_home_score IS NOT NULL),

    -- result_confirmed_at can only be set once an outcome is recorded.
    CONSTRAINT chk_matches_confirmed_at_requires_outcome
        CHECK (result_confirmed_at IS NULL OR outcome IS NOT NULL),

    -- Outcome must be mathematically consistent with the scoreline.
    CONSTRAINT chk_matches_outcome_score_consistency
        CHECK (
            outcome IS NULL
            OR result_home_score IS NULL
            OR result_away_score IS NULL
            OR (result_home_score > result_away_score  AND outcome = 'home_win')
            OR (result_home_score < result_away_score  AND outcome = 'away_win')
            OR (result_home_score = result_away_score  AND outcome = 'draw')
        )
);

COMMENT ON TABLE  matches               IS 'Local mirror of football fixtures. outcome column drives all bet settlement.';
COMMENT ON COLUMN matches.external_id   IS 'Provider-assigned match ID. Used to deduplicate incoming fixture data.';
COMMENT ON COLUMN matches.outcome       IS 'Set on completion. Drives settlement: home_win | away_win | draw.';
COMMENT ON COLUMN matches.provider_name IS 'Which provider ingested this fixture e.g. "api_football". NULL for manual rows.';
COMMENT ON COLUMN matches.last_synced_at IS 'Timestamp of the most recent successful provider sync.';

CREATE INDEX IF NOT EXISTS idx_matches_status        ON matches (status);
CREATE INDEX IF NOT EXISTS idx_matches_kickoff_at    ON matches (kickoff_at);
CREATE INDEX IF NOT EXISTS ix_matches_provider_name  ON matches (provider_name);

DROP TRIGGER IF EXISTS trg_matches_updated_at ON matches;
CREATE TRIGGER trg_matches_updated_at
    BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- fee_config
-- Versioned platform fee rates. Rows are never deleted.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fee_config (
    id             UUID          NOT NULL DEFAULT gen_random_uuid(),
    fee_type       fee_type      NOT NULL,
    rate           DECIMAL(5,4)  NOT NULL,
    currency       CHAR(3)       NOT NULL,
    effective_from TIMESTAMPTZ   NOT NULL,
    created_by     UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fee_config          PRIMARY KEY (id),
    CONSTRAINT fk_fee_config_created_by FOREIGN KEY (created_by) REFERENCES users (id),
    CONSTRAINT chk_fee_config_rate_range CHECK (rate > 0 AND rate < 1)
);

COMMENT ON TABLE  fee_config               IS 'Versioned fee rates. To change, insert a new row with a future effective_from. Never update/delete.';
COMMENT ON COLUMN fee_config.rate          IS 'Fractional rate. 0.1000 = 10%, 0.0500 = 5%.';
COMMENT ON COLUMN fee_config.effective_from IS 'Active for settlements where settled_at >= effective_from. Most recent wins.';

CREATE INDEX IF NOT EXISTS idx_fee_config_lookup
    ON fee_config (fee_type, currency, effective_from DESC);


-- =============================================================================
-- SECTION 4: BETTING TABLE
-- =============================================================================

-- -----------------------------------------------------------------------------
-- bets
-- Core bet record. Full lifecycle from OPEN through SETTLED / VOIDED.
-- Uses CASE-based CHECK constraints to avoid NULL-ambiguity.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bets (
    id                         UUID              NOT NULL DEFAULT gen_random_uuid(),
    match_id                   UUID              NOT NULL,
    creator_id                 UUID              NOT NULL,
    opponent_id                UUID,
    creator_prediction         football_outcome  NOT NULL,
    opponent_prediction        football_outcome,
    stake_amount               DECIMAL(15,2)     NOT NULL,
    currency                   CHAR(3)           NOT NULL DEFAULT 'ZAR',
    status                     bet_status        NOT NULL DEFAULT 'OPEN',
    settlement_outcome         settlement_outcome,
    winner_id                  UUID,
    platform_fee               DECIMAL(15,2),
    payout_amount              DECIMAL(15,2),
    applied_winner_fee_rate    DECIMAL(5,4),
    applied_no_winner_fee_rate DECIMAL(5,4),
    expires_at                 TIMESTAMPTZ       NOT NULL,
    settled_at                 TIMESTAMPTZ,
    created_at                 TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ       NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_bets                     PRIMARY KEY (id),
    CONSTRAINT fk_bets_match               FOREIGN KEY (match_id)    REFERENCES matches (id),
    CONSTRAINT fk_bets_creator             FOREIGN KEY (creator_id)  REFERENCES users   (id),
    CONSTRAINT fk_bets_opponent            FOREIGN KEY (opponent_id) REFERENCES users   (id),
    CONSTRAINT fk_bets_winner              FOREIGN KEY (winner_id)   REFERENCES users   (id),

    -- Participant integrity
    CONSTRAINT chk_bets_creator_ne_opponent
        CHECK (opponent_id IS NULL OR opponent_id <> creator_id),

    CONSTRAINT chk_bets_predictions_differ
        CHECK (opponent_prediction IS NULL OR opponent_prediction <> creator_prediction),

    CONSTRAINT chk_bets_opponent_fields_consistent
        CHECK (
            (opponent_id IS NULL     AND opponent_prediction IS NULL)
            OR (opponent_id IS NOT NULL AND opponent_prediction IS NOT NULL)
        ),

    CONSTRAINT chk_bets_winner_is_participant
        CHECK (
            winner_id IS NULL
            OR winner_id = creator_id
            OR winner_id = opponent_id
        ),

    CONSTRAINT chk_bets_winner_requires_opponent
        CHECK (winner_id IS NULL OR opponent_id IS NOT NULL),

    -- Settlement integrity (CASE-based to avoid NULL-ambiguity)
    CONSTRAINT chk_bets_winner_identity
        CHECK (
            CASE settlement_outcome
                WHEN 'creator_wins'  THEN winner_id IS NOT NULL AND winner_id = creator_id
                WHEN 'opponent_wins' THEN winner_id IS NOT NULL AND winner_id = opponent_id
                WHEN 'no_winner'     THEN winner_id IS NULL
                WHEN 'voided'        THEN winner_id IS NULL
                ELSE TRUE
            END
        ),

    CONSTRAINT chk_bets_payout_presence
        CHECK (
            CASE settlement_outcome
                WHEN 'creator_wins'  THEN payout_amount IS NOT NULL AND payout_amount > 0
                WHEN 'opponent_wins' THEN payout_amount IS NOT NULL AND payout_amount > 0
                WHEN 'no_winner'     THEN payout_amount IS NULL
                WHEN 'voided'        THEN payout_amount IS NULL
                ELSE TRUE
            END
        ),

    CONSTRAINT chk_bets_platform_fee_consistency
        CHECK (
            CASE settlement_outcome
                WHEN 'creator_wins'  THEN platform_fee IS NOT NULL AND platform_fee > 0
                WHEN 'opponent_wins' THEN platform_fee IS NOT NULL AND platform_fee > 0
                WHEN 'no_winner'     THEN platform_fee IS NOT NULL AND platform_fee > 0
                WHEN 'voided'        THEN platform_fee IS NULL
                ELSE TRUE
            END
        ),

    -- Lifecycle constraints
    CONSTRAINT chk_bets_outcome_when_settled
        CHECK (status <> 'SETTLED' OR settlement_outcome IS NOT NULL),

    CONSTRAINT chk_bets_settled_at_when_settled
        CHECK (status <> 'SETTLED' OR settled_at IS NOT NULL),

    -- Financial constraints
    CONSTRAINT chk_bets_stake_positive
        CHECK (stake_amount > 0),

    CONSTRAINT chk_bets_winner_fee_rate_valid
        CHECK (applied_winner_fee_rate IS NULL
               OR (applied_winner_fee_rate > 0 AND applied_winner_fee_rate < 1)),

    CONSTRAINT chk_bets_no_winner_fee_rate_valid
        CHECK (applied_no_winner_fee_rate IS NULL
               OR (applied_no_winner_fee_rate > 0 AND applied_no_winner_fee_rate < 1)),

    CONSTRAINT chk_bets_expires_at_after_created
        CHECK (expires_at > created_at)
);

COMMENT ON TABLE  bets               IS 'Core bet record. Tracks full lifecycle from OPEN through SETTLED/VOIDED.';
COMMENT ON COLUMN bets.stake_amount  IS 'Stake per user. Both users stake this exact amount (equal-stake model). Pool = stake * 2.';
COMMENT ON COLUMN bets.expires_at    IS 'Acceptance deadline = matches.kickoff_at. No acceptance permitted at or after this time.';
COMMENT ON COLUMN bets.winner_id     IS 'Set by settlement engine. Constrained by chk_bets_winner_identity.';
COMMENT ON COLUMN bets.payout_amount IS 'Amount credited to winner. pool * (1 - applied_winner_fee_rate). NULL for no-winner/voided.';
COMMENT ON COLUMN bets.platform_fee  IS 'Total fee collected. Winner path: 10% of pool. No-winner: 5% per user. NULL for voided.';

-- Public feed: OPEN bets not yet expired.
CREATE INDEX IF NOT EXISTS idx_bets_open_feed
    ON bets (created_at DESC)
    WHERE status = 'OPEN';

-- Filter open bets by match.
CREATE INDEX IF NOT EXISTS idx_bets_match_open
    ON bets (match_id, created_at DESC)
    WHERE status = 'OPEN';

-- Settlement engine: bets awaiting settlement.
CREATE INDEX IF NOT EXISTS idx_bets_pending_settlement
    ON bets (match_id)
    WHERE status IN ('MATCHED', 'PENDING_SETTLEMENT');

-- Expiry job: auto-cancel OPEN bets whose kickoff has passed.
CREATE INDEX IF NOT EXISTS idx_bets_expiry_job
    ON bets (expires_at)
    WHERE status = 'OPEN';

-- User history.
CREATE INDEX IF NOT EXISTS idx_bets_creator_history  ON bets (creator_id,  created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bets_opponent_history ON bets (opponent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bets_status           ON bets (status);
CREATE INDEX IF NOT EXISTS idx_bets_winner_id
    ON bets (winner_id)
    WHERE winner_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_bets_updated_at ON bets;
CREATE TRIGGER trg_bets_updated_at
    BEFORE UPDATE ON bets
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- =============================================================================
-- SECTION 5: LEDGER TABLES (IMMUTABLE — NO UPDATE/DELETE PERMITTED)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- ledger_entries
-- Immutable, append-only financial event log for user wallets.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ledger_entries (
    id                      UUID                  NOT NULL DEFAULT gen_random_uuid(),
    user_id                 UUID                  NOT NULL,
    wallet_id               UUID                  NOT NULL,
    entry_type              ledger_entry_type     NOT NULL,
    balance_field           balance_field         NOT NULL,
    direction               ledger_direction      NOT NULL,
    amount                  DECIMAL(15,2)         NOT NULL,
    reference_type          ledger_reference_type NOT NULL,
    reference_id            UUID                  NOT NULL,
    available_balance_after DECIMAL(15,2)         NOT NULL,
    locked_balance_after    DECIMAL(15,2)         NOT NULL,
    created_at              TIMESTAMPTZ           NOT NULL DEFAULT NOW(),
    notes                   TEXT,

    CONSTRAINT pk_ledger_entries                   PRIMARY KEY (id),
    CONSTRAINT fk_ledger_entries_user              FOREIGN KEY (user_id)   REFERENCES users   (id),
    CONSTRAINT fk_ledger_entries_wallet            FOREIGN KEY (wallet_id) REFERENCES wallets (id),
    CONSTRAINT chk_ledger_amount_positive          CHECK (amount > 0),
    CONSTRAINT chk_ledger_available_after_non_negative CHECK (available_balance_after >= 0),
    CONSTRAINT chk_ledger_locked_after_non_negative    CHECK (locked_balance_after    >= 0)
);

COMMENT ON TABLE  ledger_entries                        IS 'Immutable financial event log. Authoritative source; wallets table is a read cache.';
COMMENT ON COLUMN ledger_entries.balance_field          IS 'Which sub-balance this entry affects: available or locked.';
COMMENT ON COLUMN ledger_entries.reference_id           IS 'ID of the source record (bet_id, deposit_id, etc). Shared across paired entries.';
COMMENT ON COLUMN ledger_entries.available_balance_after IS 'Wallet snapshot after this entry — enables point-in-time reconstruction.';
COMMENT ON COLUMN ledger_entries.locked_balance_after   IS 'Wallet snapshot after this entry.';

CREATE INDEX IF NOT EXISTS idx_ledger_user_history    ON ledger_entries (user_id,    created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_wallet_history  ON ledger_entries (wallet_id,  created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_reference       ON ledger_entries (reference_id, reference_type);

DROP TRIGGER IF EXISTS trg_ledger_no_update ON ledger_entries;
DROP TRIGGER IF EXISTS trg_ledger_no_delete ON ledger_entries;
CREATE TRIGGER trg_ledger_no_update
    BEFORE UPDATE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();
CREATE TRIGGER trg_ledger_no_delete
    BEFORE DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();


-- -----------------------------------------------------------------------------
-- platform_ledger_entries
-- Immutable record of every fee credit to a platform account.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_ledger_entries (
    id                  UUID                  NOT NULL DEFAULT gen_random_uuid(),
    platform_account_id UUID                  NOT NULL,
    entry_type          platform_entry_type   NOT NULL,
    direction           ledger_direction      NOT NULL DEFAULT 'credit',
    amount              DECIMAL(15,2)         NOT NULL,
    reference_type      ledger_reference_type NOT NULL DEFAULT 'settlement',
    reference_id        UUID                  NOT NULL,
    balance_after       DECIMAL(15,2)         NOT NULL,
    settlement_path     settlement_path_type  NOT NULL,
    created_at          TIMESTAMPTZ           NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_platform_ledger_entries        PRIMARY KEY (id),
    CONSTRAINT fk_platform_ledger_account        FOREIGN KEY (platform_account_id) REFERENCES platform_accounts (id),
    CONSTRAINT fk_platform_ledger_bet            FOREIGN KEY (reference_id)        REFERENCES bets (id),
    CONSTRAINT chk_platform_ledger_direction_credit
        CHECK (direction = 'credit'),
    CONSTRAINT chk_platform_ledger_reference_type_settlement
        CHECK (reference_type = 'settlement'),
    CONSTRAINT chk_platform_ledger_amount_positive
        CHECK (amount > 0),
    CONSTRAINT chk_platform_ledger_balance_after_non_negative
        CHECK (balance_after >= 0)
);

COMMENT ON TABLE  platform_ledger_entries               IS 'Immutable platform fee ledger. Paired with ledger_entries via shared reference_id.';
COMMENT ON COLUMN platform_ledger_entries.direction     IS 'Always credit — enforced by constraint. Platform accounts only accumulate fees.';
COMMENT ON COLUMN platform_ledger_entries.reference_id  IS 'FK → bets.id. Same reference_id as paired user ledger_entries rows.';
COMMENT ON COLUMN platform_ledger_entries.balance_after IS 'Platform account balance immediately after this entry.';

CREATE INDEX IF NOT EXISTS idx_platform_ledger_account_id
    ON platform_ledger_entries (platform_account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_platform_ledger_reference_id
    ON platform_ledger_entries (reference_id);

DROP TRIGGER IF EXISTS trg_platform_ledger_no_update ON platform_ledger_entries;
DROP TRIGGER IF EXISTS trg_platform_ledger_no_delete ON platform_ledger_entries;
CREATE TRIGGER trg_platform_ledger_no_update
    BEFORE UPDATE ON platform_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();
CREATE TRIGGER trg_platform_ledger_no_delete
    BEFORE DELETE ON platform_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();


-- =============================================================================
-- SECTION 6: AUDIT AND OPERATIONS TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- bet_events
-- Immutable, append-only audit trail for every bet state transition.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bet_events (
    id          UUID           NOT NULL DEFAULT gen_random_uuid(),
    bet_id      UUID           NOT NULL,
    event_type  bet_event_type NOT NULL,
    actor_id    UUID,
    actor_label VARCHAR(100)   NOT NULL,
    payload     JSONB,
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_bet_events      PRIMARY KEY (id),
    CONSTRAINT fk_bet_events_bet  FOREIGN KEY (bet_id)   REFERENCES bets  (id),
    CONSTRAINT fk_bet_events_user FOREIGN KEY (actor_id) REFERENCES users (id)
);

COMMENT ON TABLE  bet_events            IS 'Immutable audit trail. A row per bet state transition and admin/system action.';
COMMENT ON COLUMN bet_events.actor_id   IS 'NULL for automated system actions (settlement engine, expiry job).';
COMMENT ON COLUMN bet_events.actor_label IS 'Always set. e.g. "USER", "ADMIN", "SETTLEMENT_ENGINE", "SYSTEM".';
COMMENT ON COLUMN bet_events.payload    IS 'JSON snapshot of bet and wallet state at event time. Used for dispute resolution.';

CREATE INDEX IF NOT EXISTS idx_bet_events_bet_id    ON bet_events (bet_id,     created_at ASC);
CREATE INDEX IF NOT EXISTS idx_bet_events_created_at ON bet_events (created_at DESC);

DROP TRIGGER IF EXISTS trg_bet_events_no_update ON bet_events;
DROP TRIGGER IF EXISTS trg_bet_events_no_delete ON bet_events;
CREATE TRIGGER trg_bet_events_no_update
    BEFORE UPDATE ON bet_events
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();
CREATE TRIGGER trg_bet_events_no_delete
    BEFORE DELETE ON bet_events
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();


-- -----------------------------------------------------------------------------
-- processed_events
-- Idempotency / deduplication log for incoming external events.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_events (
    id                UUID         NOT NULL DEFAULT gen_random_uuid(),
    event_source      VARCHAR(100) NOT NULL,
    external_event_id VARCHAR(500) NOT NULL,
    processed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_processed_events              PRIMARY KEY (id),
    CONSTRAINT uq_processed_events_source_event UNIQUE (event_source, external_event_id)
);

COMMENT ON TABLE  processed_events                IS 'Deduplication log for external events. Check before processing; insert within same transaction.';
COMMENT ON COLUMN processed_events.event_source   IS 'External system identifier e.g. "api_football", "payfast".';
COMMENT ON COLUMN processed_events.external_event_id IS 'Provider-assigned event ID. Unique within its event_source.';


-- =============================================================================
-- SECTION 7: FUNDING TABLES (from migration 002 + 003)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- deposit_requests
-- Tracks the lifecycle of a user wallet top-up via a payment provider.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS deposit_requests (
    id                 UUID            NOT NULL DEFAULT gen_random_uuid(),
    user_id            UUID            NOT NULL,
    wallet_id          UUID            NOT NULL,
    amount             DECIMAL(15,2)   NOT NULL,
    currency           CHAR(3)         NOT NULL DEFAULT 'ZAR',
    status             deposit_status  NOT NULL DEFAULT 'pending',
    payment_provider   VARCHAR(50),
    provider_reference VARCHAR(200),
    client_reference   VARCHAR(200),
    notes              TEXT,
    -- Migration 003: checkout URL stored so frontend can retrieve without re-signing.
    checkout_url       TEXT,
    requested_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    failed_at          TIMESTAMPTZ,

    CONSTRAINT pk_deposit_requests                  PRIMARY KEY (id),
    CONSTRAINT fk_deposit_requests_user             FOREIGN KEY (user_id)   REFERENCES users   (id) ON DELETE CASCADE,
    CONSTRAINT fk_deposit_requests_wallet           FOREIGN KEY (wallet_id) REFERENCES wallets (id) ON DELETE CASCADE,
    CONSTRAINT uq_deposit_requests_provider_ref     UNIQUE (provider_reference),
    CONSTRAINT uq_deposit_requests_client_ref       UNIQUE (client_reference),
    CONSTRAINT chk_deposit_requests_amount_positive CHECK (amount > 0)
);

COMMENT ON TABLE  deposit_requests                   IS 'Lifecycle of a wallet top-up. pending → processing → completed | failed | cancelled.';
COMMENT ON COLUMN deposit_requests.provider_reference IS 'PayFast pf_payment_id or equivalent. UNIQUE — used for idempotency.';
COMMENT ON COLUMN deposit_requests.client_reference   IS 'Our internal reference passed to the provider. UNIQUE.';
COMMENT ON COLUMN deposit_requests.checkout_url       IS 'PayFast hosted checkout URL stored at deposit initiation.';

CREATE INDEX IF NOT EXISTS ix_deposit_requests_user_id     ON deposit_requests (user_id);
CREATE INDEX IF NOT EXISTS ix_deposit_requests_wallet_id   ON deposit_requests (wallet_id);
CREATE INDEX IF NOT EXISTS ix_deposit_requests_status      ON deposit_requests (status);
CREATE INDEX IF NOT EXISTS ix_deposit_requests_user_status ON deposit_requests (user_id, status);
CREATE INDEX IF NOT EXISTS ix_deposit_requests_requested_at ON deposit_requests (requested_at);


-- -----------------------------------------------------------------------------
-- withdrawal_requests
-- Tracks the lifecycle of a user wallet withdrawal.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS withdrawal_requests (
    id                  UUID                NOT NULL DEFAULT gen_random_uuid(),
    user_id             UUID                NOT NULL,
    wallet_id           UUID                NOT NULL,
    amount              DECIMAL(15,2)       NOT NULL,
    currency            CHAR(3)             NOT NULL DEFAULT 'ZAR',
    status              withdrawal_status   NOT NULL DEFAULT 'pending',
    destination_account VARCHAR(200),
    destination_type    VARCHAR(50),
    provider_reference  VARCHAR(200),
    rejection_reason    TEXT,
    requested_at        TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    approved_at         TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    failed_at           TIMESTAMPTZ,

    CONSTRAINT pk_withdrawal_requests                    PRIMARY KEY (id),
    CONSTRAINT fk_withdrawal_requests_user               FOREIGN KEY (user_id)   REFERENCES users   (id) ON DELETE CASCADE,
    CONSTRAINT fk_withdrawal_requests_wallet             FOREIGN KEY (wallet_id) REFERENCES wallets (id) ON DELETE CASCADE,
    CONSTRAINT uq_withdrawal_requests_provider_reference UNIQUE (provider_reference),
    CONSTRAINT chk_withdrawal_requests_amount_positive   CHECK (amount > 0)
);

COMMENT ON TABLE  withdrawal_requests                    IS 'Lifecycle of a wallet withdrawal. pending → approved → processing → completed | failed | rejected.';
COMMENT ON COLUMN withdrawal_requests.destination_account IS 'Bank account number, EFT reference, or equivalent.';
COMMENT ON COLUMN withdrawal_requests.destination_type    IS 'Payment rail e.g. "bank_transfer", "eft".';
COMMENT ON COLUMN withdrawal_requests.provider_reference  IS 'Provider-assigned payout reference. UNIQUE.';

CREATE INDEX IF NOT EXISTS ix_withdrawal_requests_user_id      ON withdrawal_requests (user_id);
CREATE INDEX IF NOT EXISTS ix_withdrawal_requests_wallet_id    ON withdrawal_requests (wallet_id);
CREATE INDEX IF NOT EXISTS ix_withdrawal_requests_status       ON withdrawal_requests (status);
CREATE INDEX IF NOT EXISTS ix_withdrawal_requests_user_status  ON withdrawal_requests (user_id, status);
CREATE INDEX IF NOT EXISTS ix_withdrawal_requests_requested_at ON withdrawal_requests (requested_at);


-- =============================================================================
-- SECTION 8: REQUIRED BOOTSTRAP DATA
-- =============================================================================
-- The platform_accounts row must exist before any settlement can execute.
-- Fee config rows must be inserted by an admin before the settlement engine runs.
-- =============================================================================

INSERT INTO platform_accounts (account_code, name, currency, balance, version)
VALUES ('PLATFORM_FEES_ZAR', 'Platform Fee Account — ZAR', 'ZAR', 0.00, 0)
ON CONFLICT (account_code) DO NOTHING;


-- =============================================================================
-- SECTION 9: REQUIRED FEE RATES
-- =============================================================================
-- Uncomment and run after confirming rates with the Product Owner.
-- These match the spec defaults (10% winner fee, 5% no-winner fee).
-- =============================================================================

-- INSERT INTO fee_config (fee_type, rate, currency, effective_from)
-- VALUES
--   ('WINNER_FEE',    0.1000, 'ZAR', NOW()),
--   ('NO_WINNER_FEE', 0.0500, 'ZAR', NOW());


-- =============================================================================
-- END OF SCHEMA
-- Tables: users, wallets, platform_accounts, matches, fee_config, bets,
--         ledger_entries, platform_ledger_entries, bet_events,
--         processed_events, deposit_requests, withdrawal_requests
-- =============================================================================
