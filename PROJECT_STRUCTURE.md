# Buddy Bet — Project Structure

## File Tree

```
Buddy_bet_v1/
├── BACKEND_DESIGN_SPEC.md          # Product + technical specification (v0.3)
├── PROJECT_STRUCTURE.md            # This file
├── schema.sql                      # Production PostgreSQL schema (v1.1)
├── pyproject.toml                  # Project metadata and dependencies
├── alembic.ini                     # Alembic migration tool config
│
├── alembic/
│   ├── env.py                      # Async Alembic migration environment
│   ├── script.py.mako              # Migration script template
│   └── versions/                   # Generated migration files (empty at init)
│
└── app/
    ├── __init__.py
    ├── main.py                     # Application factory (create_app), lifespan, middleware
    │
    ├── api/
    │   └── v1/
    │       ├── router.py           # Aggregates all endpoint routers under /api/v1
    │       └── endpoints/
    │           ├── auth.py         # POST /auth/register, POST /auth/login
    │           ├── bets.py         # GET /bets/open, GET /bets/my, POST /bets,
    │           │                   # POST /bets/{id}/accept, POST /bets/{id}/cancel
    │           ├── matches.py      # GET /matches, GET /matches/{id}
    │           └── wallet.py       # GET /wallet/me
    │
    ├── core/
    │   ├── config.py               # Pydantic Settings v2, get_settings() singleton
    │   ├── dependencies.py         # get_db, get_current_user, get_current_admin
    │   ├── exceptions.py           # AppException hierarchy (NotFoundError, etc.)
    │   └── security.py             # JWT encode/decode, bcrypt password hashing
    │
    ├── db/
    │   ├── base.py                 # DeclarativeBase (imports all models for Alembic)
    │   └── session.py              # create_async_engine, AsyncSessionFactory
    │
    ├── models/                     # SQLAlchemy 2.0 ORM models (Mapped[] style)
    │   ├── enums.py                # Python str enums matching every PostgreSQL enum
    │   ├── user.py                 # users table
    │   ├── wallet.py               # wallets table
    │   ├── match.py                # matches table
    │   ├── fee_config.py           # fee_config table
    │   ├── bet.py                  # bets table
    │   ├── ledger.py               # ledger_entries + platform_ledger_entries tables
    │   ├── platform.py             # platform_accounts table
    │   ├── bet_event.py            # bet_events table
    │   └── processed_event.py      # processed_events table (idempotency log)
    │
    ├── repositories/               # Data access layer — raw DB queries only
    │   ├── base.py                 # BaseRepository[T] with get_by_id_or_404
    │   ├── user_repository.py      # get_by_email, get_by_id_or_404
    │   ├── wallet_repository.py    # get_by_user_id_for_update, update_balances
    │   ├── bet_repository.py       # get_for_update, get_open_bets, get_user_bets
    │   ├── match_repository.py     # get_by_id_or_404, list (paginated)
    │   └── ledger_repository.py    # create_entry (insert-only)
    │
    ├── schemas/                    # Pydantic v2 request/response models
    │   ├── common.py               # DecimalStr, PageParams, PaginatedResponse[T]
    │   ├── auth.py                 # RegisterRequest, LoginRequest, TokenResponse
    │   ├── user.py                 # UserResponse
    │   ├── wallet.py               # WalletResponse
    │   ├── match.py                # MatchResponse, MatchListResponse
    │   └── bet.py                  # CreateBetRequest, AcceptBetRequest,
    │                               # BetResponse, BetListResponse
    │
    ├── services/                   # Business logic layer
    │   ├── auth_service.py         # register, login (hashing, JWT issuance)
    │   ├── wallet_service.py       # lock_stake, unlock_stake, void_refund,
    │   │                           # credit_available, apply_balance_update
    │   ├── bet_service.py          # create_bet, accept_bet, cancel_bet,
    │   │                           # get_open_bets, get_user_bets
    │   ├── match_service.py        # list_matches, get_match
    │   ├── ledger_service.py       # write_stake_lock, write_stake_unlock,
    │   │                           # write_void_refund, write_settlement_winner,
    │   │                           # write_settlement_no_winner
    │   └── settlement_service.py   # settle_bet (stub — raises NotImplementedError)
    │
    └── utils/
        ├── decimal_utils.py        # safe_add, safe_subtract, round_half_up,
        │                           # verify_non_negative (zero float arithmetic)
        └── pagination.py           # Pagination helper utilities
```

---

## Architecture Decisions

### 1. Layer Separation

The codebase is divided into four strict layers with a one-way dependency rule:

```
API endpoints → Services → Repositories → Models
```

- **Endpoints** (`api/v1/endpoints/`) handle HTTP: parse requests, call a single service method, return responses. No business logic, no DB queries.
- **Services** (`services/`) own all business rules. They coordinate repositories and other services. They never touch the DB directly.
- **Repositories** (`repositories/`) contain all SQL. They return ORM model instances. No business logic.
- **Models** (`models/`) are pure SQLAlchemy table mappings. No methods beyond simple properties.

This makes each layer independently testable and prevents business logic from leaking into HTTP handlers or SQL from leaking into service logic.

---

### 2. Transaction Ownership — `get_db`

Every request gets exactly one `AsyncSession`. The `get_db` FastAPI dependency (in `core/dependencies.py`) owns the transaction lifecycle:

- Commits on success.
- Rolls back on any exception.
- Closes the session in a `finally` block.

Services call `flush()` to write pending changes to the DB within the transaction (to get generated IDs, trigger constraints, etc.) but **never** call `commit()` or `rollback()`. This means every request is a single atomic unit: either everything succeeds or nothing does.

---

### 3. Concurrency Safety — SELECT FOR UPDATE

Two different rows require locking to prevent race conditions:

**Wallet row** — `WalletRepository.get_by_user_id_for_update()` issues `SELECT ... FOR UPDATE` before every balance mutation. This serialises concurrent writes to the same wallet (e.g. two bets being accepted simultaneously by the same user). All balance-mutating service methods (`lock_stake`, `unlock_stake`, `void_refund`) call this method first.

**Bet row** — `BetRepository.get_for_update()` issues `SELECT ... FOR UPDATE` at the start of `accept_bet`. This prevents the double-acceptance race condition: if two users attempt to accept the same bet concurrently, only one will proceed; the other will see status ≠ OPEN after acquiring the lock and will receive a `BetNotAvailableError`.

Both locks are held within the same database transaction — the bet lock and the wallet lock are acquired together, preventing all known concurrent-acceptance scenarios.

---

### 4. Decimal Enforcement — No Float Arithmetic

All monetary values are `Decimal` throughout the stack:

- PostgreSQL columns: `NUMERIC(15, 2)`.
- SQLAlchemy: `Numeric(15, 2)`.
- Python: `Decimal` from the `decimal` module.
- API responses: serialised as **strings** via the custom `DecimalStr` type in `schemas/common.py`.

`app/utils/decimal_utils.py` provides `safe_add`, `safe_subtract`, `round_half_up` (using `ROUND_HALF_UP`), and `verify_non_negative`. These are the only functions used for monetary arithmetic. Float is never used anywhere in money-handling code paths.

`DecimalStr` is a custom Pydantic v2 annotated type that:
- Accepts `Decimal`, `int`, `float`, or `str` on input and converts to `Decimal`.
- Serialises to `str` in JSON responses (prevents floating-point precision loss in JavaScript clients).

---

### 5. Model Enum Safety — `create_type=False`

All PostgreSQL enums are defined in `schema.sql` and created when the schema is applied. SQLAlchemy must **not** attempt to `CREATE TYPE` again at ORM level.

Every enum column in every model uses:
```python
SAEnum(FootballOutcome, create_type=False, native_enum=True)
```

`create_type=False` tells SQLAlchemy to skip type creation. `native_enum=True` uses the PostgreSQL native enum type (as opposed to a VARCHAR with a CHECK constraint), which matches the schema exactly.

---

### 6. Ledger Write Ordering — Snapshot Correctness

`LedgerService` methods require the wallet to be passed **after** `update_balances()` has been called and flushed. This ensures the `available_balance_after` and `locked_balance_after` snapshot columns in `ledger_entries` reflect the correct post-operation state, not the pre-operation state.

The correct call sequence in `WalletService` is:
1. `get_by_user_id_for_update()` — acquire lock, read current balances.
2. Compute new balances.
3. `update_balances()` — write and flush new balances.
4. `ledger_service.write_*()` — write ledger entries using the updated wallet.

Every public method on `LedgerService` writes exactly two (or three) entries per the spec ledger sequences (§9.3/9.4). All entries for a single operation share the same `reference_id` (the `bet_id`) for end-to-end audit traceability.

---

### 7. Static Route Ordering — `/bets/open` before `/{bet_id}`

FastAPI matches routes in registration order. If `/{bet_id}` were registered before `/open`, FastAPI would attempt to parse the string `"open"` as a UUID, fail, and return a 422 error.

In `api/v1/endpoints/bets.py`, the static routes are registered first:
```
GET  /bets/open   ← registered first
GET  /bets/my     ← registered second
POST /bets/       ← dynamic routes follow
POST /bets/{bet_id}/accept
POST /bets/{bet_id}/cancel
```

A comment at the top of the file documents this constraint explicitly.

---

### 8. Settlement Service — Stub

`services/settlement_service.py` is currently a stub. `settle_bet()` raises `NotImplementedError`. The private helper methods (`_determine_path`, `_compute_winner_amounts`, `_compute_no_winner_amounts`) have correct signatures and docstrings but no implementation.

Settlement will be the next major implementation milestone. The full ledger sequences it must write are defined in `BACKEND_DESIGN_SPEC.md` sections 9.3 and 9.4, and the ledger write methods it will call (`write_settlement_winner`, `write_settlement_no_winner`) are already fully implemented in `LedgerService`.

---

## Key Platform Constants (from `core/config.py`)

| Setting | Value | Description |
|---|---|---|
| `platform_currency` | `ZAR` | All stakes and payouts denominated in ZAR |
| `min_stake_amount` | `10.00` | Minimum bet stake (subject to PO-02 confirmation) |
| `max_stake_amount` | `10000.00` | Maximum bet stake (subject to PO-02 confirmation) |
| `bet_creation_cutoff_minutes` | `15` | Bets close 15 min before kickoff (subject to PO-05 confirmation) |
| `access_token_expire_minutes` | `60` | JWT access token lifetime |

---

## Fee Structure

| Scenario | Platform Fee | Per User |
|---|---|---|
| Winner path (PATH A or B) | 10% of total pool (2 × stake) | N/A (deducted from pool) |
| No-winner path (PATH C) | 5% per user | Each user loses 5% of their stake |
| Voided bet | 0% | Full stake refunded |

Winner payout = `stake × 2 × 0.90` (90% of total pool).
No-winner refund per user = `stake × 0.95`.

---

## Implementation Status

| Module | Status |
|---|---|
| Auth (register, login) | Complete |
| Wallet (read, lock, unlock, void_refund, credit) | Complete |
| Bets (create, accept, cancel, list) | Complete |
| Ledger (all entry types) | Complete |
| Matches (list, get) | Complete |
| Settlement | Stub only (NotImplementedError) |
| Admin module | Not started |
| Notifications | Not started |
| Background jobs (expiry, settlement polling, watchdog) | Not started |
| Tests | Not started |
