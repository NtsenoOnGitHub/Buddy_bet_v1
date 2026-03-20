# Buddy Bet

Peer-to-peer football betting platform. Users create and accept bets on football match outcomes (home win / away win / draw), stake funds from an in-app wallet, and receive payouts on settlement.

## Tech stack

- **FastAPI** — async HTTP API
- **PostgreSQL 14+** — primary datastore (enums, JSONB, triggers)
- **SQLAlchemy 2.0** (asyncio + asyncpg) — ORM and query layer
- **Alembic** — database migrations
- **Pydantic v2** — request/response validation
- **JWT (HS256)** via `python-jose` — stateless auth

---

## Local setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ running locally
- `pip` or `uv`

### 1. Clone and install dependencies

```bash
git clone https://github.com/NtsenoOnGitHub/Buddy_bet_v1.git
cd Buddy_bet_v1

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

### 2. Configure environment

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` — the required variables are listed below.

### 3. Create the database

```bash
psql -U postgres -c "CREATE DATABASE buddy_bet;"
psql -U postgres -c "CREATE USER buddy_bet_app WITH PASSWORD 'your_password';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE buddy_bet TO buddy_bet_app;"
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start the server

```bash
uvicorn app.main:app --reload
```

API is available at `http://localhost:8000`.
Interactive docs at `http://localhost:8000/docs`.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `development` | Environment name (`development`, `staging`, `production`) |
| `APP_DEBUG` | No | `true` | Enable SQLAlchemy SQL logging |
| `APP_HOST` | No | `0.0.0.0` | Bind host |
| `APP_PORT` | No | `8000` | Bind port |
| `SECRET_KEY` | **Yes (non-dev)** | — | Secret used to sign JWTs. Must be a long random string in any non-development environment. |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `60` | JWT lifetime in minutes |
| `DB_HOST` | No | `localhost` | PostgreSQL host |
| `DB_PORT` | No | `5432` | PostgreSQL port |
| `DB_NAME` | No | `buddy_bet` | Database name |
| `DB_USER` | No | `buddy_bet_app` | Database user |
| `DB_PASSWORD` | **Yes** | — | Database password |
| `DATABASE_URL` | No | — | Full DSN override (overrides DB_* components) |
| `CORS_ORIGINS` | No | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed CORS origins |
| `MIN_STAKE_AMOUNT` | No | `10.00` | Minimum bet stake in ZAR |
| `MAX_STAKE_AMOUNT` | No | `10000.00` | Maximum bet stake in ZAR |
| `BET_CREATION_CUTOFF_MINUTES` | No | `15` | Minutes before kickoff after which bet creation is blocked |
| `LOG_LEVEL` | No | `INFO` | Python log level |

> **Security note:** The application will refuse to start if `SECRET_KEY` is set to an insecure placeholder value and `APP_ENV` is not `development`.

---

## API routes

All routes are prefixed with `/api/v1`.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | — | Register a new account, returns JWT |
| POST | `/auth/login` | — | Login, returns JWT |
| GET | `/wallet` | Required | Get wallet balances |
| GET | `/wallet/transactions` | Required | Paginated ledger history |
| GET | `/matches` | Required | List upcoming scheduled matches |
| GET | `/matches/{id}` | Required | Single match detail |
| GET | `/bets/open` | Required | Paginated feed of open bets |
| GET | `/bets/my` | Required | Current user's full bet history |
| POST | `/bets` | Required | Create a new bet |
| POST | `/bets/{id}/accept` | Required | Accept an open bet |
| POST | `/bets/{id}/cancel` | Required | Cancel an open bet (creator only) |

---

## Migration commands

```bash
# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Roll back all migrations
alembic downgrade base

# Generate a new migration (after model changes)
alembic revision --autogenerate -m "describe your change"

# Show current migration state
alembic current

# Show migration history
alembic history
```

---

## Running tests

```bash
pytest

# With coverage
pytest --cov=app --cov-report=term-missing
```

---

## Project structure

```
app/
  api/v1/endpoints/   — route handlers
  core/               — config, security, dependencies, exceptions
  db/                 — engine and session factory
  models/             — SQLAlchemy ORM models
  repositories/       — data access layer
  schemas/            — Pydantic request/response schemas
  services/           — business logic
  utils/              — decimal helpers, pagination
alembic/              — migration scripts
tests/                — test suite
schema.sql            — reference DDL (not applied directly; use alembic)
```
