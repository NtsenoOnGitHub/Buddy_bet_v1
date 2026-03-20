-- =============================================================================
-- Buddy Bet MVP — PostgreSQL Production Schema
-- Version:    1.1
-- Date:       2026-03-20
-- Source:     Backend Design Specification v0.3 (amended)
-- Target:     PostgreSQL 14+
-- =============================================================================
-- Changes in v1.1 (hardening pass):
--   - pgcrypto extension added for UUID portability across PostgreSQL versions.
--   - platform_ledger_entries.direction typed as ledger_direction enum (was VARCHAR).
--   - platform_ledger_entries.reference_type typed as ledger_reference_type enum (was VARCHAR).
--   - platform_accounts: UNIQUE (currency) added to enforce one account per currency at MVP.
--   - matches: chk_matches_outcome_score_consistency added — outcome must agree with scores.
--   - bets: chk_bets_winner_identity replaces two weaker winner constraints; uses CASE to
--     avoid NULL-ambiguity in CHECK expressions.
--   - bets: chk_bets_payout_presence added — payout_amount required for winner path,
--     must be NULL for no-winner/voided. Replaces chk_bets_payout_non_negative.
--   - bets: chk_bets_platform_fee_consistency added — platform_fee required and positive for
--     settled paths, must be NULL for voided. Replaces chk_bets_platform_fee_non_negative.
--   - ledger_entries: idx_ledger_reference_id replaced with composite index on
--     (reference_id, reference_type) to support filtered traceability queries.
-- =============================================================================
-- All monetary columns use DECIMAL(15,2). Never use floating-point for money.
-- All timestamps are TIMESTAMPTZ (UTC-aware). Store and retrieve in UTC.
-- Ledger tables (ledger_entries, platform_ledger_entries, bet_events) are
-- immutable by policy. Mutation-prevention triggers are installed on each.
-- =============================================================================


-- =============================================================================
-- SECTION 0: EXTENSIONS
-- =============================================================================

-- pgcrypto provides gen_random_uuid() on PostgreSQL 12 and earlier.
-- On PostgreSQL 13+, gen_random_uuid() is a built-in function; this extension
-- is a no-op but is included for portability and explicit documentation.
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- =============================================================================
-- SECTION 1: ENUM TYPES
-- =============================================================================

CREATE TYPE user_status AS ENUM (
    'active',
    'suspended',
    'banned'
);

CREATE TYPE user_role AS ENUM (
    'user',
    'admin'
);

-- Shared outcome type used for both match results and bet predictions.
CREATE TYPE football_outcome AS ENUM (
    'home_win',
    'away_win',
    'draw'
);

CREATE TYPE match_status AS ENUM (
    'scheduled',
    'live',
    'completed',
    'postponed',
    'cancelled',
    'abandoned'
);

CREATE TYPE bet_status AS ENUM (
    'OPEN',
    'MATCHED',
    'PENDING_SETTLEMENT',
    'SETTLED',
    'CANCELLED',
    'VOIDED',
    'UNDER_REVIEW'
);

CREATE TYPE settlement_outcome AS ENUM (
    'creator_wins',
    'opponent_wins',
    'no_winner',
    'voided'
);

-- Entry types for user-side ledger entries.
CREATE TYPE ledger_entry_type AS ENUM (
    'STAKE_LOCK',         -- Stake moved from available to locked at bet creation/acceptance.
    'STAKE_UNLOCK',       -- Stake returned from locked to available on cancellation.
    'VOID_REFUND',        -- Full stake returned from locked to available on void.
    'SETTLEMENT_DEDUCT',  -- Locked stake consumed at settlement (winner and no-winner paths).
    'PAYOUT_CREDIT',      -- Winner payout (90% of pool) credited to available.
    'REFUND_CREDIT',      -- No-winner refund (95% of stake) credited to available.
    'FEE_DEDUCT',         -- No-winner platform fee (5% of stake) deducted from locked.
    'DEPOSIT',            -- Funds added to wallet via payment provider.
    'WITHDRAWAL'          -- Funds removed via withdrawal request.
);

CREATE TYPE balance_field AS ENUM (
    'available',
    'locked'
);

CREATE TYPE ledger_direction AS ENUM (
    'credit',
    'debit'
);

-- Reference types for ledger_entries.reference_type and
-- platform_ledger_entries.reference_type.
CREATE TYPE ledger_reference_type AS ENUM (
    'bet',
    'settlement',
    'void',
    'cancellation',
    'deposit',
    'withdrawal'
);

-- Entry types for platform-side fee ledger.
CREATE TYPE platform_entry_type AS ENUM (
    'FEE_COLLECTION',           -- Fee collected when there is a winner (10% of pool).
    'FEE_COLLECTION_NO_WINNER'  -- Fee collected when there is no winner (5% per user).
);

-- Which settlement branch generated a platform fee entry.
CREATE TYPE settlement_path_type AS ENUM (
    'winner',
    'no_winner'
);

CREATE TYPE fee_type AS ENUM (
    'WINNER_FEE',    -- Rate applied when there is a winner. Spec default: 10%.
    'NO_WINNER_FEE'  -- Rate applied when there is no winner. Spec default: 5%.
);

CREATE TYPE bet_event_type AS ENUM (
    'CREATED',
    'MATCHED',
    'PENDING_SETTLEMENT',
    'SETTLED',
    'CANCELLED',
    'VOIDED',
    'UNDER_REVIEW',
    'ADMIN_OVERRIDE'
);


-- =============================================================================
-- SECTION 2: UTILITY FUNCTIONS
-- =============================================================================

-- Auto-update updated_at on any table that carries that column.
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- Raise an exception if any mutation (UPDATE or DELETE) is attempted on an
-- immutable table. Applied to ledger_entries, platform_ledger_entries, and
-- bet_events. Corrections must be made via compensating entries only.
CREATE OR REPLACE FUNCTION fn_prevent_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
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
-- TABLE: users
-- One row per registered platform user. Includes both bettors and admins.
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id            UUID          NOT NULL DEFAULT gen_random_uuid(),
    email         VARCHAR(320)  NOT NULL,
    phone_number  VARCHAR(30),
    display_name  VARCHAR(100)  NOT NULL,
    password_hash TEXT          NOT NULL,
    role          user_role     NOT NULL DEFAULT 'user',
    status        user_status   NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_users
        PRIMARY KEY (id),

    CONSTRAINT uq_users_email
        UNIQUE (email)
);

COMMENT ON TABLE users IS
    'Platform user accounts. role controls access (user = bettor, admin = ops/support). '
    'status controls betting eligibility. Neither users nor their records are deleted; '
    'they are suspended or banned.';

COMMENT ON COLUMN users.password_hash IS
    'Bcrypt or Argon2id hash. The plain-text password is never stored or logged.';

COMMENT ON COLUMN users.status IS
    'active: normal access. '
    'suspended: account under review; open bets auto-cancelled, matched bets flagged UNDER_REVIEW. '
    'banned: permanently blocked from the platform.';

COMMENT ON COLUMN users.role IS
    'user: standard bettor. admin: operations access to admin module endpoints.';

CREATE INDEX idx_users_status ON users (status);

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- TABLE: wallets
-- One wallet per user. Tracks available and locked balances independently.
-- total_balance is NOT stored. It is always computed as:
--   total_balance = available_balance + locked_balance
-- -----------------------------------------------------------------------------
CREATE TABLE wallets (
    id                UUID          NOT NULL DEFAULT gen_random_uuid(),
    user_id           UUID          NOT NULL,
    available_balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    locked_balance    DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    currency          CHAR(3)       NOT NULL DEFAULT 'ZAR',
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    version           INTEGER       NOT NULL DEFAULT 0,

    CONSTRAINT pk_wallets
        PRIMARY KEY (id),

    CONSTRAINT fk_wallets_user
        FOREIGN KEY (user_id) REFERENCES users (id),

    CONSTRAINT uq_wallets_user
        UNIQUE (user_id),  -- Exactly one wallet per user.

    CONSTRAINT chk_wallets_available_non_negative
        CHECK (available_balance >= 0),

    CONSTRAINT chk_wallets_locked_non_negative
        CHECK (locked_balance >= 0)
);

COMMENT ON TABLE wallets IS
    'User wallet. Stores available_balance (spendable) and locked_balance (reserved against '
    'active bets) as separate fields. total_balance = available + locked is computed on read — '
    'it is not a stored column. The ledger_entries table is the authoritative source of truth; '
    'these balances are a performance cache reconciled daily.';

COMMENT ON COLUMN wallets.available_balance IS
    'Funds the user can bet with, or withdraw. Decreases when a stake is locked; '
    'increases when a bet is cancelled, voided, or when a payout/refund is credited.';

COMMENT ON COLUMN wallets.locked_balance IS
    'Funds reserved against active (OPEN or MATCHED) bets. Not spendable or withdrawable. '
    'Consumed at settlement. Returned in full on void or cancellation.';

COMMENT ON COLUMN wallets.version IS
    'Optimistic lock counter. The application increments this on every balance update '
    'and uses it to detect concurrent writes: '
    'UPDATE wallets SET ... version = version + 1 WHERE id = ? AND version = ?';

CREATE TRIGGER trg_wallets_updated_at
    BEFORE UPDATE ON wallets
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- TABLE: platform_accounts
-- Internal fee-collection accounts. Not user-facing. One row per currency at MVP.
-- -----------------------------------------------------------------------------
CREATE TABLE platform_accounts (
    id           UUID          NOT NULL DEFAULT gen_random_uuid(),
    account_code VARCHAR(100)  NOT NULL,
    name         VARCHAR(200)  NOT NULL,
    currency     CHAR(3)       NOT NULL,
    balance      DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    version      INTEGER       NOT NULL DEFAULT 0,

    CONSTRAINT pk_platform_accounts
        PRIMARY KEY (id),

    CONSTRAINT uq_platform_accounts_code
        UNIQUE (account_code),

    -- MVP invariant: exactly one fee account per currency.
    -- Prevents accidental duplicate accounts for the same currency.
    CONSTRAINT uq_platform_accounts_currency
        UNIQUE (currency),

    CONSTRAINT chk_platform_accounts_balance_non_negative
        CHECK (balance >= 0)
);

COMMENT ON TABLE platform_accounts IS
    'Internal accounts that accumulate platform fee revenue. Not user-facing. '
    'One row per currency at MVP — enforced by the UNIQUE (currency) constraint. '
    'balance is a running total reconciled against the sum of all platform_ledger_entries '
    'for this account.';

COMMENT ON COLUMN platform_accounts.account_code IS
    'Stable, application-readable identifier. e.g. PLATFORM_FEES_ZAR. '
    'Referenced in application config — do not change after go-live.';

COMMENT ON COLUMN platform_accounts.balance IS
    'Running total of all fees collected into this account. '
    'Must equal SUM(amount) FROM platform_ledger_entries WHERE platform_account_id = this.id.';

COMMENT ON COLUMN platform_accounts.version IS
    'Optimistic lock counter. Incremented on every balance update, same pattern as wallets.';

CREATE TRIGGER trg_platform_accounts_updated_at
    BEFORE UPDATE ON platform_accounts
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- TABLE: matches
-- Local mirror of football fixture data ingested from an external provider.
-- All bet settlement is driven from the outcome column on this table.
-- -----------------------------------------------------------------------------
CREATE TABLE matches (
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
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_matches
        PRIMARY KEY (id),

    CONSTRAINT uq_matches_external_id
        UNIQUE (external_id),

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

    -- When both scores and outcome are present, the outcome must be mathematically
    -- consistent with the scoreline. Prevents a data provider error or admin mistake
    -- from writing a contradictory result (e.g. home 3-1 away but outcome = 'draw').
    -- The NULL escape clauses are required: if either score or outcome is NULL,
    -- this constraint does not apply (other constraints handle those cases).
    CONSTRAINT chk_matches_outcome_score_consistency
        CHECK (
            outcome IS NULL
            OR result_home_score IS NULL
            OR result_away_score IS NULL
            OR (result_home_score > result_away_score AND outcome = 'home_win')
            OR (result_home_score < result_away_score AND outcome = 'away_win')
            OR (result_home_score = result_away_score AND outcome = 'draw')
        )
);

COMMENT ON TABLE matches IS
    'Local mirror of football fixtures sourced from an external data provider. '
    'The Fixture Module writes and updates these rows. The Settlement Engine reads '
    'the outcome column to determine the settlement path for all bets on a match. '
    'All bets reference this table via match_id.';

COMMENT ON COLUMN matches.external_id IS
    'Provider-assigned match identifier. Used to deduplicate incoming fixture data '
    'and correlate webhook/poll results back to local records.';

COMMENT ON COLUMN matches.outcome IS
    'Set when status transitions to completed. Null for all other statuses. '
    'Drives settlement path: home_win | away_win | draw. '
    'Must be mathematically consistent with result_home_score and result_away_score '
    '(enforced by chk_matches_outcome_score_consistency).';

COMMENT ON COLUMN matches.result_confirmed_at IS
    'Timestamp when the result was confirmed and the MatchResultConfirmed event '
    'was emitted. Settlement engine processing begins after this is set.';

COMMENT ON COLUMN matches.kickoff_at IS
    'Scheduled match start time (UTC). Bets cannot be created or accepted at or '
    'after this time. Equals bets.expires_at for all bets on this match.';

CREATE INDEX idx_matches_status     ON matches (status);
CREATE INDEX idx_matches_kickoff_at ON matches (kickoff_at);
-- external_id unique constraint already creates an implicit index.

CREATE TRIGGER trg_matches_updated_at
    BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- -----------------------------------------------------------------------------
-- TABLE: fee_config
-- Versioned platform fee rates. Rows are never deleted.
-- The Settlement Engine queries for the rate active at settlement time:
--   SELECT rate FROM fee_config
--   WHERE fee_type = ? AND currency = ? AND effective_from <= <settled_at>
--   ORDER BY effective_from DESC LIMIT 1
-- -----------------------------------------------------------------------------
CREATE TABLE fee_config (
    id             UUID          NOT NULL DEFAULT gen_random_uuid(),
    fee_type       fee_type      NOT NULL,
    rate           DECIMAL(5,4)  NOT NULL,
    currency       CHAR(3)       NOT NULL,
    effective_from TIMESTAMPTZ   NOT NULL,
    created_by     UUID,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_fee_config
        PRIMARY KEY (id),

    CONSTRAINT fk_fee_config_created_by
        FOREIGN KEY (created_by) REFERENCES users (id),

    -- Rate must be a meaningful non-zero fraction strictly less than 100%.
    CONSTRAINT chk_fee_config_rate_range
        CHECK (rate > 0 AND rate < 1)
);

COMMENT ON TABLE fee_config IS
    'Versioned platform fee rates. Historical rows are never deleted or updated. '
    'To change a rate, insert a new row with a future effective_from. '
    'The Settlement Engine resolves the applicable rate at settlement time and '
    'records it as a frozen snapshot on the bets row (applied_winner_fee_rate / '
    'applied_no_winner_fee_rate). Future rate changes never affect settled bets.';

COMMENT ON COLUMN fee_config.rate IS
    'Fractional fee rate. 0.1000 = 10%, 0.0500 = 5%. Must be > 0 and < 1. '
    'WINNER_FEE is applied to (stake * 2). NO_WINNER_FEE is applied per user stake.';

COMMENT ON COLUMN fee_config.effective_from IS
    'This rate is active for all settlements where settled_at >= effective_from. '
    'Multiple rows may exist; the most recent effective_from <= settled_at wins.';

COMMENT ON COLUMN fee_config.created_by IS
    'Admin user who configured this rate. Nullable only for the initial bootstrap '
    'insert before any admin users exist.';

-- Optimised for the Settlement Engine rate-lookup query.
CREATE INDEX idx_fee_config_lookup
    ON fee_config (fee_type, currency, effective_from DESC);


-- =============================================================================
-- SECTION 4: BETTING TABLE
-- =============================================================================

-- -----------------------------------------------------------------------------
-- TABLE: bets
-- Core betting record. One row per bet from creation through final resolution.
-- No uniqueness constraints on (creator_id, match_id) or
-- (creator_id, match_id, creator_prediction). A user may create multiple bets
-- on the same match with any combination of predictions.
--
-- Settlement constraint design note:
-- Three CASE-based constraints (chk_bets_winner_identity, chk_bets_payout_presence,
-- chk_bets_platform_fee_consistency) use CASE rather than OR chains to avoid
-- PostgreSQL's NULL-ambiguity in CHECK expressions. In a CHECK constraint, an
-- expression that evaluates to NULL is treated as "unknown" and passes, which can
-- cause incorrect rows to be accepted when OR branches contain nullable comparisons.
-- CASE explicitly returns TRUE or FALSE for each branch, eliminating this risk.
-- -----------------------------------------------------------------------------
CREATE TABLE bets (
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

    CONSTRAINT pk_bets
        PRIMARY KEY (id),

    CONSTRAINT fk_bets_match
        FOREIGN KEY (match_id)    REFERENCES matches (id),

    CONSTRAINT fk_bets_creator
        FOREIGN KEY (creator_id)  REFERENCES users (id),

    CONSTRAINT fk_bets_opponent
        FOREIGN KEY (opponent_id) REFERENCES users (id),

    CONSTRAINT fk_bets_winner
        FOREIGN KEY (winner_id)   REFERENCES users (id),

    -- -------------------------------------------------------------------------
    -- Participant integrity constraints
    -- -------------------------------------------------------------------------

    -- A user cannot accept their own bet (BR-01).
    CONSTRAINT chk_bets_creator_ne_opponent
        CHECK (opponent_id IS NULL OR opponent_id <> creator_id),

    -- Opponent must choose a different outcome from the creator (BR-06, BR-07).
    CONSTRAINT chk_bets_predictions_differ
        CHECK (
            opponent_prediction IS NULL
            OR opponent_prediction <> creator_prediction
        ),

    -- opponent_id and opponent_prediction must be set together or not at all.
    CONSTRAINT chk_bets_opponent_fields_consistent
        CHECK (
            (opponent_id IS NULL     AND opponent_prediction IS NULL)
            OR
            (opponent_id IS NOT NULL AND opponent_prediction IS NOT NULL)
        ),

    -- winner_id (if set pre-settlement) must be one of the two known participants.
    -- Guards against a winner_id being assigned to an unrelated user.
    CONSTRAINT chk_bets_winner_is_participant
        CHECK (
            winner_id IS NULL
            OR winner_id = creator_id
            OR winner_id = opponent_id
        ),

    -- A winner can only exist if there is an opponent.
    CONSTRAINT chk_bets_winner_requires_opponent
        CHECK (winner_id IS NULL OR opponent_id IS NOT NULL),

    -- -------------------------------------------------------------------------
    -- Settlement integrity constraints (CASE-based — see design note above)
    -- -------------------------------------------------------------------------

    -- winner_id must exactly match the winning participant indicated by
    -- settlement_outcome, and must be NULL for no-winner/voided outcomes.
    -- Uses CASE to avoid NULL-ambiguity: each branch returns an explicit
    -- boolean rather than relying on nullable comparison short-circuit logic.
    --
    --   creator_wins  → winner_id IS NOT NULL AND winner_id = creator_id
    --   opponent_wins → winner_id IS NOT NULL AND winner_id = opponent_id
    --   no_winner     → winner_id IS NULL
    --   voided        → winner_id IS NULL
    --   NULL (pre-settlement) → no constraint (ELSE TRUE)
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

    -- payout_amount must be present and positive for winner paths;
    -- must be NULL for no-winner and voided paths.
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

    -- platform_fee must be present and positive for all settled paths (winner and
    -- no-winner); must be NULL for voided bets (no fee is charged on a void).
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

    -- -------------------------------------------------------------------------
    -- Lifecycle constraints
    -- -------------------------------------------------------------------------

    -- When status is SETTLED, settlement_outcome must be recorded.
    CONSTRAINT chk_bets_outcome_when_settled
        CHECK (status <> 'SETTLED' OR settlement_outcome IS NOT NULL),

    -- When status is SETTLED, settled_at must be recorded.
    CONSTRAINT chk_bets_settled_at_when_settled
        CHECK (status <> 'SETTLED' OR settled_at IS NOT NULL),

    -- -------------------------------------------------------------------------
    -- Financial constraints
    -- -------------------------------------------------------------------------

    -- Stake must be a positive amount (BR-05 equal-stake model).
    CONSTRAINT chk_bets_stake_positive
        CHECK (stake_amount > 0),

    -- Applied fee rates must be valid fractions when present.
    CONSTRAINT chk_bets_winner_fee_rate_valid
        CHECK (applied_winner_fee_rate IS NULL
               OR (applied_winner_fee_rate > 0 AND applied_winner_fee_rate < 1)),

    CONSTRAINT chk_bets_no_winner_fee_rate_valid
        CHECK (applied_no_winner_fee_rate IS NULL
               OR (applied_no_winner_fee_rate > 0 AND applied_no_winner_fee_rate < 1)),

    -- expires_at must be after the bet was created.
    -- The application sets expires_at = match.kickoff_at; kickoff must be
    -- in the future at creation time.
    CONSTRAINT chk_bets_expires_at_after_created
        CHECK (expires_at > created_at)
);

COMMENT ON TABLE bets IS
    'Core betting record. Tracks the full lifecycle of a P2P bet from OPEN through '
    'SETTLED or VOIDED. No uniqueness constraint exists on (creator_id, match_id) or '
    '(creator_id, match_id, creator_prediction) — a user may create multiple bets on '
    'the same match with any prediction.';

COMMENT ON COLUMN bets.stake_amount IS
    'Stake per user. Both users stake this exact amount (equal-stake model, BR-05). '
    'Total pool = stake_amount * 2.';

COMMENT ON COLUMN bets.expires_at IS
    'Acceptance deadline. Set equal to matches.kickoff_at at bet creation time. '
    'No acceptance is permitted at or after this timestamp.';

COMMENT ON COLUMN bets.opponent_id IS
    'NULL while status = OPEN. Set atomically when User B accepts (status → MATCHED). '
    'Once set, this bet is permanently closed to new participants.';

COMMENT ON COLUMN bets.settlement_outcome IS
    'Set at settlement. creator_wins | opponent_wins | no_winner | voided. '
    'NULL until bet reaches SETTLED or VOIDED. '
    'Drives winner_id, payout_amount, and platform_fee via DB-level CASE constraints.';

COMMENT ON COLUMN bets.winner_id IS
    'The user who won the bet. Constrained by chk_bets_winner_identity: '
    'must equal creator_id when settlement_outcome = creator_wins, '
    'must equal opponent_id when settlement_outcome = opponent_wins, '
    'must be NULL when settlement_outcome IN (no_winner, voided).';

COMMENT ON COLUMN bets.platform_fee IS
    'Total platform fee collected across both users at settlement. '
    'Winner path: 10% of total pool. No-winner path: 5% per user summed. '
    'Must be NULL for voided bets. Must be present and positive for all other settled paths. '
    'Enforced by chk_bets_platform_fee_consistency.';

COMMENT ON COLUMN bets.payout_amount IS
    'Amount credited to winner.available_balance at settlement. '
    'Equals total_pool * (1 - applied_winner_fee_rate). '
    'Must be present and positive when settlement_outcome IN (creator_wins, opponent_wins). '
    'Must be NULL for no-winner and voided paths. Enforced by chk_bets_payout_presence.';

COMMENT ON COLUMN bets.applied_winner_fee_rate IS
    'Frozen snapshot of the fee_config rate used if this bet followed the winner path. '
    'Unaffected by future changes to fee_config. NULL if no-winner path.';

COMMENT ON COLUMN bets.applied_no_winner_fee_rate IS
    'Frozen snapshot of the fee_config rate used if this bet followed the no-winner path. '
    'NULL if winner path.';

-- Public feed query: OPEN bets not yet expired, ordered by creation time.
CREATE INDEX idx_bets_open_feed
    ON bets (created_at DESC)
    WHERE status = 'OPEN';

-- Filter open bets by match (e.g. "show open bets for this fixture").
CREATE INDEX idx_bets_match_open
    ON bets (match_id, created_at DESC)
    WHERE status = 'OPEN';

-- Settlement engine: locate bets awaiting settlement when a match result arrives.
CREATE INDEX idx_bets_pending_settlement
    ON bets (match_id)
    WHERE status IN ('MATCHED', 'PENDING_SETTLEMENT');

-- Expiry job: auto-cancel OPEN bets whose kickoff time has passed.
CREATE INDEX idx_bets_expiry_job
    ON bets (expires_at)
    WHERE status = 'OPEN';

-- User history endpoint: /bets/my — all bets for a given user.
CREATE INDEX idx_bets_creator_history
    ON bets (creator_id, created_at DESC);

CREATE INDEX idx_bets_opponent_history
    ON bets (opponent_id, created_at DESC);

-- Admin filtering on status.
CREATE INDEX idx_bets_status
    ON bets (status);

-- winner_id lookups (reconciliation, disputes).
CREATE INDEX idx_bets_winner_id
    ON bets (winner_id)
    WHERE winner_id IS NOT NULL;

CREATE TRIGGER trg_bets_updated_at
    BEFORE UPDATE ON bets
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- =============================================================================
-- SECTION 5: LEDGER TABLES (IMMUTABLE)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- TABLE: ledger_entries
-- Immutable, append-only financial event log for user wallets.
-- Every change to any wallet balance field produces one or more rows here.
-- The wallets table balances are a cache derived from this log.
-- Paired entries (e.g. STAKE_LOCK debit + credit) share the same reference_id.
-- Operations that affect both balance fields produce exactly two rows per wallet.
-- -----------------------------------------------------------------------------
CREATE TABLE ledger_entries (
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

    CONSTRAINT pk_ledger_entries
        PRIMARY KEY (id),

    CONSTRAINT fk_ledger_entries_user
        FOREIGN KEY (user_id)   REFERENCES users   (id),

    CONSTRAINT fk_ledger_entries_wallet
        FOREIGN KEY (wallet_id) REFERENCES wallets (id),

    CONSTRAINT chk_ledger_amount_positive
        CHECK (amount > 0),

    CONSTRAINT chk_ledger_available_after_non_negative
        CHECK (available_balance_after >= 0),

    CONSTRAINT chk_ledger_locked_after_non_negative
        CHECK (locked_balance_after >= 0)
);

COMMENT ON TABLE ledger_entries IS
    'Immutable, append-only financial event log. Every wallet balance change produces '
    'one or more rows here. The wallets table is a read-optimised cache; this table is '
    'authoritative. Discrepancies between cached balances and ledger-derived sums must '
    'trigger an admin alert. Corrections are made via compensating entries only — no '
    'UPDATE or DELETE is ever permitted.';

COMMENT ON COLUMN ledger_entries.balance_field IS
    'Which of the two wallet sub-balances this entry affects: available or locked. '
    'Operations that move funds between sub-balances produce two rows with the same '
    'reference_id — one debit on the source field, one credit on the destination.';

COMMENT ON COLUMN ledger_entries.reference_id IS
    'ID of the source record driving this entry. For bet-related entries this is the '
    'bets.id. For deposits/withdrawals it is the corresponding payment record ID. '
    'Shared across all paired entries in a single operation, and shared with the '
    'corresponding platform_ledger_entries row for fee traceability.';

COMMENT ON COLUMN ledger_entries.available_balance_after IS
    'Snapshot of wallet.available_balance immediately after this entry is applied. '
    'Recorded on every entry (even when only locked_balance changed) to enable '
    'point-in-time wallet reconstruction without full history replay.';

COMMENT ON COLUMN ledger_entries.locked_balance_after IS
    'Snapshot of wallet.locked_balance immediately after this entry is applied. '
    'Recorded on every entry even when only available_balance changed.';

-- User transaction history (e.g. GET /wallet/transactions).
CREATE INDEX idx_ledger_user_history
    ON ledger_entries (user_id, created_at DESC);

-- Wallet-level audit / reconciliation.
CREATE INDEX idx_ledger_wallet_history
    ON ledger_entries (wallet_id, created_at DESC);

-- Traceability: look up all entries for a given source record, optionally filtered
-- by reference_type (e.g. all 'bet' entries for a bet_id, all 'deposit' entries
-- for a deposit_id). Including reference_type allows the planner to use the index
-- for filtered queries such as:
--   WHERE reference_id = :bet_id AND reference_type = 'settlement'
CREATE INDEX idx_ledger_reference
    ON ledger_entries (reference_id, reference_type);

-- Mutation-prevention triggers.
CREATE TRIGGER trg_ledger_no_update
    BEFORE UPDATE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();

CREATE TRIGGER trg_ledger_no_delete
    BEFORE DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();


-- -----------------------------------------------------------------------------
-- TABLE: platform_ledger_entries
-- Immutable record of every fee credit to a platform account.
-- Every row is linked to the user-side ledger_entries rows that funded it
-- via a shared reference_id (the bet_id). This satisfies the traceability
-- requirement: sum of user FEE_DEDUCT / SETTLEMENT_DEDUCT entries minus
-- user PAYOUT_CREDIT / REFUND_CREDIT entries = platform fee amount.
--
-- direction and reference_type use the ledger_direction and ledger_reference_type
-- enum types (shared with ledger_entries) with CHECK constraints narrowing them
-- to their single valid values for platform entries.
-- -----------------------------------------------------------------------------
CREATE TABLE platform_ledger_entries (
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

    CONSTRAINT pk_platform_ledger_entries
        PRIMARY KEY (id),

    CONSTRAINT fk_platform_ledger_account
        FOREIGN KEY (platform_account_id) REFERENCES platform_accounts (id),

    -- reference_id always points to the settled bet that generated this fee.
    CONSTRAINT fk_platform_ledger_bet
        FOREIGN KEY (reference_id) REFERENCES bets (id),

    -- Platform accounts only receive fees; direction is always credit.
    -- The ledger_direction enum permits 'debit'; the CHECK narrows it.
    CONSTRAINT chk_platform_ledger_direction_credit
        CHECK (direction = 'credit'),

    -- At MVP, platform fees are always generated by settlement events.
    -- The ledger_reference_type enum permits other values; the CHECK narrows it.
    CONSTRAINT chk_platform_ledger_reference_type_settlement
        CHECK (reference_type = 'settlement'),

    CONSTRAINT chk_platform_ledger_amount_positive
        CHECK (amount > 0),

    CONSTRAINT chk_platform_ledger_balance_after_non_negative
        CHECK (balance_after >= 0)
);

COMMENT ON TABLE platform_ledger_entries IS
    'Immutable record of every fee credit received by a platform account. '
    'Each row is paired with user-side ledger_entries via a shared reference_id (bet_id). '
    'Traceability audit: SELECT * FROM ledger_entries WHERE reference_id = :bet_id gives '
    'all user-side deductions; SELECT * FROM platform_ledger_entries WHERE reference_id = :bet_id '
    'gives the corresponding platform credit. Their net must balance to zero.';

COMMENT ON COLUMN platform_ledger_entries.direction IS
    'Typed as ledger_direction enum (shared with ledger_entries). '
    'Always ''credit'' for platform fee entries — enforced by chk_platform_ledger_direction_credit. '
    'Platform accounts only accumulate fees; they never pay out.';

COMMENT ON COLUMN platform_ledger_entries.reference_type IS
    'Typed as ledger_reference_type enum (shared with ledger_entries). '
    'Always ''settlement'' at MVP — enforced by chk_platform_ledger_reference_type_settlement.';

COMMENT ON COLUMN platform_ledger_entries.reference_id IS
    'FK → bets.id. This is the same reference_id carried by all user-side ledger_entries '
    'for the same settlement transaction, enabling complete end-to-end traceability.';

COMMENT ON COLUMN platform_ledger_entries.balance_after IS
    'Platform account balance immediately after this entry is applied. '
    'Must equal SUM(amount) over all prior platform_ledger_entries for this account.';

COMMENT ON COLUMN platform_ledger_entries.settlement_path IS
    'Records which settlement branch generated this fee: winner or no_winner. '
    'Paired with entry_type: winner → FEE_COLLECTION, no_winner → FEE_COLLECTION_NO_WINNER.';

-- Reconciliation: sum all fees for a platform account.
CREATE INDEX idx_platform_ledger_account_id
    ON platform_ledger_entries (platform_account_id, created_at DESC);

-- Traceability: find the platform fee entry for a given bet.
CREATE INDEX idx_platform_ledger_reference_id
    ON platform_ledger_entries (reference_id);

-- Mutation-prevention triggers.
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
-- TABLE: bet_events
-- Immutable, append-only audit trail for every bet state transition.
-- Every status change, admin action, and system event writes a row here.
-- actor_id is NULL for system-initiated events; actor_label always describes the actor.
-- -----------------------------------------------------------------------------
CREATE TABLE bet_events (
    id          UUID           NOT NULL DEFAULT gen_random_uuid(),
    bet_id      UUID           NOT NULL,
    event_type  bet_event_type NOT NULL,
    actor_id    UUID,
    actor_label VARCHAR(100)   NOT NULL,
    payload     JSONB,
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_bet_events
        PRIMARY KEY (id),

    CONSTRAINT fk_bet_events_bet
        FOREIGN KEY (bet_id)   REFERENCES bets  (id),

    CONSTRAINT fk_bet_events_user
        FOREIGN KEY (actor_id) REFERENCES users (id)
);

COMMENT ON TABLE bet_events IS
    'Immutable, append-only audit trail. A row is written for every bet state transition '
    'and every admin or system action affecting a bet. No row is ever updated or deleted. '
    'The payload column captures a JSON snapshot of relevant bet and wallet state at the '
    'time of the event for dispute resolution and compliance.';

COMMENT ON COLUMN bet_events.actor_id IS
    'FK to users.id when the action was performed by a human user or admin. '
    'NULL for automated system actions (settlement engine, expiry job, etc.).';

COMMENT ON COLUMN bet_events.actor_label IS
    'Human-readable actor descriptor. Always set. '
    'For user actions: ''USER'' or ''ADMIN''. '
    'For system actions: ''SETTLEMENT_ENGINE'', ''EXPIRY_JOB'', ''SYSTEM'', ''FIXTURE_MODULE''.';

COMMENT ON COLUMN bet_events.payload IS
    'JSON snapshot of the bet state and relevant wallet balances at the moment of the event. '
    'Schema is event-type specific. Used for dispute resolution, compliance, and debugging.';

-- Audit queries: all events for a given bet, in order.
CREATE INDEX idx_bet_events_bet_id
    ON bet_events (bet_id, created_at ASC);

-- Operations dashboard: recent events across all bets.
CREATE INDEX idx_bet_events_created_at
    ON bet_events (created_at DESC);

-- Mutation-prevention triggers.
CREATE TRIGGER trg_bet_events_no_update
    BEFORE UPDATE ON bet_events
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();

CREATE TRIGGER trg_bet_events_no_delete
    BEFORE DELETE ON bet_events
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_mutation();


-- -----------------------------------------------------------------------------
-- TABLE: processed_events
-- Idempotency / deduplication log for incoming external events.
-- Before processing any external event (e.g. match result webhook), the
-- application checks this table. If the (event_source, external_event_id) pair
-- is already present, the event is discarded (return HTTP 200 to provider).
-- If absent, insert here within the same transaction that triggers settlement.
-- -----------------------------------------------------------------------------
CREATE TABLE processed_events (
    id                UUID         NOT NULL DEFAULT gen_random_uuid(),
    event_source      VARCHAR(100) NOT NULL,
    external_event_id VARCHAR(500) NOT NULL,
    processed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_processed_events
        PRIMARY KEY (id),

    CONSTRAINT uq_processed_events_source_event
        UNIQUE (event_source, external_event_id)
);

COMMENT ON TABLE processed_events IS
    'Deduplication log for incoming external events (match result webhooks, provider callbacks). '
    'On receipt, check for (event_source, external_event_id). If found: discard, return 200. '
    'If not found: insert this row within the same DB transaction that triggers settlement. '
    'Combined with the conditional bet status update (WHERE status = PENDING_SETTLEMENT), '
    'this provides two independent guards against duplicate settlement.';

COMMENT ON COLUMN processed_events.event_source IS
    'Identifies the external system that emitted the event. e.g. ''api_football'', ''sportmonks''.';

COMMENT ON COLUMN processed_events.external_event_id IS
    'Provider-assigned event identifier. Unique within its event_source. '
    'May be a string UUID, integer, or compound key depending on the provider.';

-- The unique constraint above creates this index implicitly, listed here for clarity.
-- CREATE UNIQUE INDEX uq_processed_events_lookup
--     ON processed_events (event_source, external_event_id);


-- =============================================================================
-- SECTION 7: REQUIRED BOOTSTRAP DATA
-- =============================================================================
-- The platform_accounts row is required before any settlement can execute.
-- Without it, the FK constraint on platform_ledger_entries.platform_account_id
-- will reject every settlement write.
--
-- NOTE: fee_config rows are NOT seeded here. At least one WINNER_FEE and one
-- NO_WINNER_FEE row must be inserted by an admin before settlement can run.
-- Spec defaults: WINNER_FEE = 0.1000 (10%), NO_WINNER_FEE = 0.0500 (5%).
-- These values require Product Owner confirmation before insertion.
-- =============================================================================

INSERT INTO platform_accounts (account_code, name, currency, balance, version)
VALUES ('PLATFORM_FEES_ZAR', 'Platform Fee Account — ZAR', 'ZAR', 0.00, 0);


-- =============================================================================
-- END OF SCHEMA — Version 1.1
-- =============================================================================
