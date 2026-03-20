# Buddy Bet — Backend Design Specification (MVP)

**Version:** 0.3 — Final Pre-Implementation Refinement
**Date:** 2026-03-20
**Author:** Solution Architecture Review
**Status:** Schema-ready — All blocking decisions resolved

**Changelog from v0.2:**
- Platform fee accounting rewritten: every platform fee now has an explicit user-side deduction and platform-side credit, both linked by the same `reference_id` (bet_id); full sum-check proofs added to both settlement paths
- Fixed no-winner ledger sequence: replaced incorrect `REFUND_CREDIT` locked debit with `SETTLEMENT_DEDUCT` locked debit for the refund portion, making the entry type table and ledger sequences consistent throughout
- `total_balance` defined as a computed (non-stored) value equal to `available_balance + locked_balance`; removed from `wallets` schema as a stored column; updated wallet API response and all invariant statements accordingly
- Settlement wording made precise: stake lifecycle (locked → consumed at settlement), payout flow (credited to available), and stake consumption are now explicitly described at every stage
- Added `GET /bets/open` as a dedicated public feed endpoint, separate from user-specific history (`GET /bets/my`)
- PO-03a and PO-03b resolved and locked: users may create multiple bets on the same match with different predictions (PO-03a) and with the same prediction (PO-03b); no uniqueness constraints prevent this
- Duplicate bet check row removed from validation rules; resolved decisions moved to Design Decisions Made table
- `GET /bets/open` requires authentication for MVP (authentication consistency fix)
- Held-funds language removed: on account suspension, funds tied to OPEN or MATCHED bets remain in `locked_balance` pending admin action; no `held_balance` field is introduced

---

## 1. Product Summary

Buddy Bet is a peer-to-peer football match betting platform. Two users take opposing single predictions on the outcome of a football match and stake equal amounts. The platform matches them, locks funds, settles automatically from a live result feed, and collects a fee on every resolved bet.

**Core differentiator:** This is not a bookmaker model. The platform does not set odds or take positions. It is a pure P2P matching layer. Revenue comes exclusively from fees.

**The prediction model in one paragraph:** Every football match has exactly three possible outcomes — home win, away win, or draw. User A claims one of these three outcomes. User B must claim exactly one of the two remaining outcomes. Because they hold different predictions, exactly one of three things can happen at settlement: User A is right, User B is right, or neither is right (the third outcome occurred). It is structurally impossible for both users to be right simultaneously.

**MVP Scope Boundary:**
- Single match, single prediction per bet
- Equal-stake only (User B's stake = User A's stake exactly)
- Two-user maximum per bet (no pools, no syndicate bets)
- Football only; three outcomes only: `home_win`, `away_win`, `draw`
- Automated settlement via external match result feed
- ZAR (South African Rand) as the assumed currency unit *(confirm with PO — PO-01)*

---

## 2. Core User Journey — Lifecycle of a Bet

The lifecycle has five clearly defined phases. Every bet must pass through these phases in order. No phase may be skipped.

---

### Phase 1 — Bet Creation

1. User A selects an upcoming football match from the available fixture list.
2. User A selects **exactly one** outcome from: `home_win`, `away_win`, `draw`.
3. User A enters a stake amount (subject to minimum and maximum limits).
4. The system checks that User A's wallet has sufficient **available balance**.
5. The system **locks** the stake amount — it moves from `available_balance` to `locked_balance`. Funds are not yet spent; they are reserved and unavailable for other use. The user's `available_balance` decreases by the stake amount; `locked_balance` increases by the same amount.
6. The bet is written to the database in **OPEN** status and published to the public bet feed.

---

### Phase 2 — Bet Discovery

1. The bet appears on the public feed visible to all authenticated users.
2. The feed shows: match details, User A's chosen outcome, stake amount, and match kickoff time.
3. The bet is **not** available to accept at or after the match kickoff time.
4. User A may cancel the bet while it is in OPEN status and before kickoff. Cancellation unlocks the stake: `locked_balance` decreases and `available_balance` is restored by the stake amount.

---

### Phase 3 — Bet Acceptance

1. User B (any user other than User A) views the bet and chooses to accept it.
2. User B selects **exactly one** outcome from the two outcomes **not already chosen by User A**.
3. The system validates: User B ≠ User A; bet is OPEN; kickoff has not passed; User B has sufficient available balance.
4. The system **locks** User B's stake — it moves from User B's `available_balance` to `locked_balance`.
5. The bet transitions to **MATCHED** status. Both users are committed. The bet is removed from the public feed.
6. No further acceptance is possible. The bet is permanently closed to new participants.

---

### Phase 4 — Awaiting Result

1. The bet remains in **MATCHED** status until the match completes.
2. The Fixture Module polls (or receives webhook calls from) a football data provider for the match result.
3. When the final result is confirmed, the bet transitions to **PENDING_SETTLEMENT** and the Settlement Engine is triggered.

---

### Phase 5 — Settlement

1. The Settlement Engine reads the confirmed match `outcome` from the `matches` table.
2. It determines the settlement path: **User A wins**, **User B wins**, or **no winner**.
3. It computes all fee and payout amounts using the rates in `fee_config`.
4. It executes all fund movements atomically within a single database transaction. The locked stakes of both users are **consumed** (permanently deducted from `locked_balance`) during this step. Payouts and refunds are **credited to `available_balance`**. The platform fee is credited to the platform account.
5. The bet transitions to **SETTLED**.
6. Both users are notified of the outcome and their updated wallet balances.

---

### Cancellation / Postponement Path (Parallel Track)

- If the match is cancelled, postponed, or abandoned, the bet transitions to **VOIDED** regardless of its current status.
- All locked funds are released back to `available_balance` for both affected users. No fee is charged on a void.
- A full audit trail entry is written to `bet_events`.

---

## 3. Main Business Rules

These rules are system invariants. They must be enforced at the data and application layer — not merely as UI hints.

| # | Rule |
|---|------|
| BR-01 | A user cannot accept their own bet under any circumstance. |
| BR-02 | Only one opponent may accept a given bet. Once matched, the bet is permanently closed. |
| BR-03 | Bets cannot be accepted at or after the scheduled match kickoff time. |
| BR-04 | The creator's full stake must be locked at bet creation time, not at acceptance time. |
| BR-05 | User B's stake must exactly equal User A's stake. No partial or unequal acceptance is permitted. |
| BR-06 | User B must select exactly one of the two outcomes not chosen by User A. |
| BR-07 | It is structurally impossible for both users to hold the same prediction. The system must enforce this at write time. |
| BR-08 | Settlement must occur exactly once per bet. Duplicate settlement must be technically prevented, not just guarded by application logic. |
| BR-09 | If there is a winner: deduct 10% of total pool as platform fee; pay 90% of total pool to the winner. The winner's payout is credited to their `available_balance`. Both users' locked stakes are consumed in full. |
| BR-10 | If there is no winner: deduct 5% of each user's individual stake as platform fee; refund 95% of each user's individual stake to their `available_balance`. Both users' locked stakes are consumed in full. |
| BR-11 | If a match is cancelled, postponed, or abandoned: full refund to both users (locked stakes returned to `available_balance`), zero platform fee. |
| BR-12 | All wallet balance changes must have a corresponding immutable ledger entry. No balance may change without one. |
| BR-13 | A bet may only be cancelled by User A while in OPEN status. Once MATCHED, neither user can cancel unilaterally. |
| BR-14 | Wallet balances can never go negative. `available_balance` and `locked_balance` are each independently non-negative. |
| BR-15 | Platform fee is always applied. The only fee-free scenario is a VOIDED bet. |
| BR-16 | The fee rates applied at settlement must be recorded on the bet record at the time of settlement. Future fee-rate changes must not alter historical payouts. |
| BR-17 | Every platform fee credit must be paired with explicit user-side deduction entries sharing the same `reference_id` (bet_id), so that every rand of fee revenue is traceable to its source. |
| BR-18 | A user may create multiple bets on the same match, whether with different predictions or the same prediction. No uniqueness constraint restricts this. |

---

## 4. Edge Cases and Failure Scenarios

### 4.1 Concurrent Acceptance Race Condition
**Scenario:** Two users attempt to accept the same OPEN bet simultaneously.
**Risk:** Both could succeed, creating a bet with two opponents and double-locked funds.
**Required handling:** Use `SELECT FOR UPDATE` on the `bets` row at acceptance time. The first transaction acquires the lock, validates OPEN status, writes the acceptance, and commits. The second transaction acquires the lock after the first commits, finds status = MATCHED, and returns a "bet no longer available" error. No funds are locked for the losing request.

---

### 4.2 Insufficient Funds at Acceptance Time
**Scenario:** User B had sufficient balance when viewing the bet, but a concurrent action (e.g., another bet creation) reduced it before acceptance completed.
**Required handling:** The balance check and lock operation must be a single atomic step inside the transaction. If the lock fails due to insufficient balance, the acceptance is rejected. The bet remains OPEN.

---

### 4.3 Match Postponement After Matching
**Scenario:** A bet is in MATCHED status when the football authority postpones the match to a new date.
**Ambiguity:** Does the bet carry over to the rescheduled fixture, or is it voided?
**Recommended default for MVP:** Void the bet and refund both users fully. A rescheduled match is treated as a new fixture; users may create new bets against it if they choose. *(Confirm with PO — this is a product decision.)*

---

### 4.4 Match Abandoned Mid-Game
**Scenario:** A match starts but is abandoned before a full-time result (e.g., weather, crowd incidents).
**Required handling:** The Fixture Module must map the provider's "abandoned" status to a VOID trigger. All bets on that match are voided; full refunds are issued with no fee.

---

### 4.5 Result Feed Failure or Delay
**Scenario:** The data provider is down or delayed after the match has ended.
**Risk:** Bets remain in MATCHED status indefinitely. User funds are locked with no resolution.
**Required handling:** Define a maximum settlement timeout (e.g., 24 hours after scheduled kickoff). If no confirmed result arrives within this window, the system raises an admin alert. An admin may manually confirm a result (triggering normal settlement) or void the bet. Funds must never be locked indefinitely without a resolution path.

---

### 4.6 Partial Settlement Failure
**Scenario:** The settlement transaction partially executes — for example, the platform fee credit succeeds but the winner payout fails.
**Risk:** Funds are lost in an inconsistent state.
**Required handling:** All settlement writes (balance updates, ledger entries, bet status update) execute inside a single database transaction. If any step fails, the entire transaction rolls back. The bet remains in PENDING_SETTLEMENT and the settlement engine retries.

---

### 4.7 User Account Suspension Mid-Bet
**Scenario:** User A's account is suspended while their OPEN bet is on the feed.
**Required handling:** Auto-cancel the OPEN bet on suspension — User A's locked stake is released back to `available_balance` and the bet is cancelled. For bets already in MATCHED status at the time of suspension, the locked stakes of both users remain in `locked_balance` — no new balance field is introduced. The bet is flagged to `UNDER_REVIEW`. Admin must manually resolve the bet (settle or void) and the funds are released at that point per the applicable settlement or void path.

---

### 4.8 Acceptance Record Written but Wallet Lock Fails
**Scenario:** The acceptance record is inserted but the wallet lock transaction fails.
**Risk:** Bet transitions to MATCHED without User B's funds secured.
**Required handling:** The acceptance insert and wallet lock must be a single atomic transaction. If either step fails, neither commits. The bet remains OPEN.

---

### 4.9 Duplicate Settlement Trigger
**Scenario:** The result polling job fires twice in quick succession, or a webhook is delivered twice.
**Risk:** Winner receives double payout.
**Required handling:** The `PENDING_SETTLEMENT → SETTLED` status update must use a conditional write (`WHERE status = 'PENDING_SETTLEMENT'`). If 0 rows are affected, another process has already settled — abort immediately and log a warning. Combined with idempotent event deduplication (see Section 11.6), this creates two independent guards.

---

### 4.10 No-Winner Outcome (Neither Prediction Matches)
**Scenario:** User A predicted `home_win`. User B predicted `away_win`. The match ends in a `draw`.
**Outcome:** Neither prediction is correct. This is the no-winner settlement path — both users are refunded 95% of their stake to `available_balance`; 5% per user is collected as platform fee. **This is a valid, fully expected business scenario, not an error state.** It must be handled as a first-class settlement branch, not a fallback.

---

### 4.11 Match Cancelled Before the Bet is Matched
**Scenario:** Bet is in OPEN status. The match is cancelled before any acceptance.
**Required handling:** Auto-void the bet. User A's locked funds are released to `available_balance`. No fee is applied. A `bet_events` entry is written.

---

## 5. Required Backend Modules / Services

These modules may be deployed as a single monolith with clear internal boundaries for MVP, with extraction to microservices available later if load demands it.

---

### 5.1 Auth & Identity Module
- User registration and login
- JWT issuance and validation
- Role management: `user`, `admin`
- Account status lifecycle: `active`, `suspended`, `banned`

---

### 5.2 Fixture & Match Data Module
- Ingests and caches fixture data from a third-party provider (e.g., API-Football, SportMonks, Football-Data.org)
- Maintains a local `matches` mirror: teams, competition, kickoff time, status, scores, outcome
- Exposes match data to other modules without live API calls per request
- Detects and propagates status transitions: `scheduled → live → completed / postponed / cancelled / abandoned`
- Emits a `MatchResultConfirmed` event consumed by the Settlement Engine
- Emits `MatchVoided` for postponement/cancellation/abandonment

---

### 5.3 Bet Management Module
- Handles bet creation, validation, and state transitions
- Manages the public bet feed (filtering, pagination, expiry of OPEN bets past kickoff)
- Handles bet acceptance with concurrency controls
- Handles user-initiated cancellation (OPEN bets only)
- Emits domain events: `BetCreated`, `BetMatched`, `BetCancelled`
- Listens to `MatchVoided` to trigger auto-void on affected bets

---

### 5.4 Wallet Module
- Manages user wallet balances (`available_balance`, `locked_balance`)
- Exposes atomic operations: `lock`, `unlock`, `deduct_locked`, `credit_available`, `transfer_locked_to_platform`
- Writes corresponding ledger entries for every operation
- Must never be called directly by the API layer — only by higher-level modules (Bet Management, Settlement Engine)

---

### 5.5 Ledger Module
- Immutable, append-only log of all financial events
- Every wallet operation and every platform fee collection produces one or more ledger entries
- Every platform fee entry is linked by `reference_id` (bet_id) to the user-side deduction entries generated in the same settlement transaction
- Provides the audit trail for compliance, disputes, and reconciliation
- Never modifies or deletes entries; corrections are compensating entries only

---

### 5.6 Settlement Engine
- Triggered by `MatchResultConfirmed` events from the Fixture Module
- Identifies all bets in MATCHED or PENDING_SETTLEMENT status for the completed match
- Determines the settlement path per bet (User A wins / User B wins / no winner)
- Reads applicable fee rates from `fee_config`
- Executes fund movements via the Wallet Module inside a single transaction per bet
- Writes to `platform_ledger_entries` for each fee collected, linked to the user-side ledger entries via `reference_id` = bet_id
- Transitions bet status to SETTLED
- Must be idempotent — safe to re-trigger without risk of double payment

---

### 5.7 Notification Module
- Listens to domain events: `BetMatched`, `BetSettled`, `BetVoided`, `BetCancelled`
- Delivers in-app notifications; optionally push/email/SMS
- Non-blocking — notification failure must never prevent or roll back a financial operation

---

### 5.8 Admin Module
- View and filter bets, users, wallets, ledger entries
- Manual match result confirmation and override
- Manual bet voiding with mandatory reason
- Account suspension and fund-hold management
- Fee rate configuration via `fee_config`
- Reconciliation report generation

---

### 5.9 Background Job Scheduler
- Polls the fixture data provider for match result updates on a defined interval
- Triggers the Settlement Engine when results are confirmed
- Watchdog job: alerts on bets in PENDING_SETTLEMENT beyond the timeout threshold
- Expiry job: auto-cancels OPEN bets whose kickoff time has passed with no acceptance

---

## 6. Recommended Database Entities / Tables

---

### `users`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| email | string | Unique, indexed |
| phone_number | string | Optional for MVP |
| display_name | string | |
| password_hash | string | |
| status | enum | `active`, `suspended`, `banned` |
| created_at | timestamp | |
| updated_at | timestamp | |

---

### `wallets`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK → users; unique (one wallet per user) |
| available_balance | decimal(15,2) | Spendable funds — user can bet with or withdraw these |
| locked_balance | decimal(15,2) | Reserved funds — tied to active bets, not spendable |
| currency | string | e.g., `ZAR` |
| updated_at | timestamp | |
| version | integer | Optimistic lock counter — incremented on every update |

**Balance model:** The wallet stores exactly two balance fields. `total_balance` is not stored — it is a computed value equal to `available_balance + locked_balance`. Neither stored field may go below zero. The computed total equals the user's full financial position within the platform.

**Invariant:** `available_balance ≥ 0` and `locked_balance ≥ 0` at all times. Enforced by the Wallet Module and verified by a daily reconciliation job.

---

### `ledger_entries`

Each row represents a single, atomic change to **one balance field** of one wallet. Operations that affect both `available_balance` and `locked_balance` produce **two ledger entries** sharing the same `reference_id`, wrapped in the same database transaction.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| wallet_id | UUID | FK → wallets |
| entry_type | enum | See entry type definitions below |
| balance_field | enum | `available` or `locked` — which balance field this entry affects |
| direction | enum | `credit` (increases the balance field) or `debit` (decreases it) |
| amount | decimal(15,2) | Always a positive value |
| reference_type | string | `bet`, `settlement`, `void`, `cancellation`, `deposit`, `withdrawal` |
| reference_id | UUID | ID of the related record (bet ID, deposit ID, etc.) |
| available_balance_after | decimal(15,2) | Snapshot of `available_balance` on this wallet after this entry is applied |
| locked_balance_after | decimal(15,2) | Snapshot of `locked_balance` on this wallet after this entry is applied |
| created_at | timestamp | Immutable — never updated |
| notes | string | Optional admin annotation |

**Entry type definitions:**

| Entry Type | Balance Field Affected | Direction | When Used |
|---|---|---|---|
| `STAKE_LOCK` | `available` | debit | Bet created or accepted — stake deducted from available |
| `STAKE_LOCK` | `locked` | credit | Paired entry — locked increases by same amount |
| `STAKE_UNLOCK` | `locked` | debit | Bet cancelled (OPEN) — stake released from locked |
| `STAKE_UNLOCK` | `available` | credit | Paired entry — available restored |
| `VOID_REFUND` | `locked` | debit | Bet voided — locked stake released |
| `VOID_REFUND` | `available` | credit | Paired entry — funds returned to available |
| `SETTLEMENT_DEDUCT` | `locked` | debit | Locked stake consumed at settlement (winner and no-winner paths; used for both the fee portion and refund portion as applicable) |
| `PAYOUT_CREDIT` | `available` | credit | Winner's payout (90% of total pool) credited to available |
| `REFUND_CREDIT` | `available` | credit | No-winner: 95% of stake returned to available |
| `FEE_DEDUCT` | `locked` | debit | No-winner: platform fee (5% of stake) deducted from locked before refund |
| `DEPOSIT` | `available` | credit | Funds added to wallet via payment |
| `WITHDRAWAL` | `available` | debit | Funds removed via withdrawal request |

**Note on balance snapshots:** Both `available_balance_after` and `locked_balance_after` are recorded on every ledger entry, even when only one field changed. This allows any point-in-time wallet state to be reconstructed from the ledger alone without replaying the full history.

---

### `platform_accounts`

Represents an internal financial account that collects platform fees. Not user-facing. One row per currency at MVP.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| account_code | string | Unique identifier, e.g., `PLATFORM_FEES_ZAR` |
| name | string | Human-readable name, e.g., `Platform Fee Account — ZAR` |
| currency | string | e.g., `ZAR` |
| balance | decimal(15,2) | Running total of all fees collected into this account |
| updated_at | timestamp | |
| version | integer | Optimistic lock counter |

---

### `platform_ledger_entries`

Immutable record of every fee credit received by the platform. Every row is linked to the user-side `ledger_entries` that sourced the fee via a shared `reference_id` (the bet_id). This makes every rand of platform revenue traceable to the exact settlement transaction and the user-side deductions that funded it.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| platform_account_id | UUID | FK → platform_accounts |
| entry_type | enum | `FEE_COLLECTION` (winner path), `FEE_COLLECTION_NO_WINNER` (no-winner path) |
| direction | enum | Always `credit` — platform only receives fees, never pays out |
| amount | decimal(15,2) | Total fee amount collected for this bet |
| reference_type | string | Always `settlement` at MVP |
| reference_id | UUID | FK → bets.id — the settled bet that generated this fee. This is the same `reference_id` carried by the corresponding user-side `ledger_entries`, linking user deductions to platform credits within a single traceable reference |
| balance_after | decimal(15,2) | Platform account balance after this entry |
| settlement_path | enum | `winner`, `no_winner` — which settlement branch generated this fee |
| created_at | timestamp | Immutable |

**Traceability guarantee:** For any `platform_ledger_entries` row, querying `ledger_entries WHERE reference_id = platform_ledger_entries.reference_id` returns all user-side deduction entries that funded this fee. The sum of relevant user deductions minus user payouts equals the platform fee. No funds are created or lost.

---

### `fee_config`

Stores platform fee rates. Rates are versioned by effective date so that historical settlements always use the rate that was active at settlement time.

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| fee_type | enum | `WINNER_FEE`, `NO_WINNER_FEE` |
| rate | decimal(5,4) | e.g., `0.1000` for 10%, `0.0500` for 5% |
| currency | string | Rate may vary by currency in future |
| effective_from | timestamp | This rate applies to settlements at or after this timestamp |
| created_by | UUID | FK → users (admin who set the rate) |
| created_at | timestamp | Immutable |

**Design note:** To find the applicable rate for a given settlement, query `fee_config WHERE fee_type = ? AND effective_from <= settlement_time ORDER BY effective_from DESC LIMIT 1`. The Settlement Engine records the resolved rate on the `bets` record at settlement time (see `applied_winner_fee_rate` and `applied_no_winner_fee_rate` below).

---

### `matches`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| external_id | string | Provider's match ID; unique, indexed |
| home_team | string | |
| away_team | string | |
| competition | string | e.g., `Premier League` |
| kickoff_at | timestamp | UTC |
| status | enum | `scheduled`, `live`, `completed`, `postponed`, `cancelled`, `abandoned` |
| result_home_score | integer | Nullable until completed |
| result_away_score | integer | Nullable until completed |
| outcome | enum | `home_win`, `away_win`, `draw`, null |
| result_confirmed_at | timestamp | Nullable |
| created_at | timestamp | |
| updated_at | timestamp | |

---

### `bets`
| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| match_id | UUID | FK → matches |
| creator_id | UUID | FK → users (User A) |
| opponent_id | UUID | FK → users (User B); nullable until MATCHED |
| creator_prediction | enum | `home_win`, `away_win`, `draw` |
| opponent_prediction | enum | `home_win`, `away_win`, `draw`; nullable until MATCHED |
| stake_amount | decimal(15,2) | Stake per user — both users stake this exact amount |
| currency | string | |
| status | enum | `OPEN`, `MATCHED`, `PENDING_SETTLEMENT`, `SETTLED`, `CANCELLED`, `VOIDED`, `UNDER_REVIEW` |
| settlement_outcome | enum | `creator_wins`, `opponent_wins`, `no_winner`, `voided`; null until settled |
| winner_id | UUID | FK → users; null if no winner or not yet settled |
| platform_fee | decimal(15,2) | Total platform fee collected at settlement; null until settled |
| payout_amount | decimal(15,2) | Amount credited to winner's available balance (null if no winner or not yet settled) |
| applied_winner_fee_rate | decimal(5,4) | Fee rate used if settlement path was a winner; null otherwise |
| applied_no_winner_fee_rate | decimal(5,4) | Fee rate used if settlement path was no-winner; null otherwise |
| expires_at | timestamp | Equals `kickoff_at` — acceptance deadline |
| settled_at | timestamp | Nullable |
| created_at | timestamp | |
| updated_at | timestamp | |

**Note on multiple bets:** There are no uniqueness constraints on `(creator_id, match_id)` or `(creator_id, match_id, creator_prediction)`. A user may create multiple bets on the same match with any combination of predictions.

---

### `bet_events` (Audit Log)

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| bet_id | UUID | FK → bets |
| event_type | enum | `CREATED`, `MATCHED`, `PENDING_SETTLEMENT`, `SETTLED`, `CANCELLED`, `VOIDED`, `UNDER_REVIEW`, `ADMIN_OVERRIDE` |
| actor_id | UUID | User ID or a reserved system actor ID (e.g., `SYSTEM`, `SETTLEMENT_ENGINE`) |
| payload | jsonb | Snapshot of the bet and wallet state relevant to this event |
| created_at | timestamp | Immutable |

---

### `processed_events`

Deduplication table for incoming external events (e.g., match result webhooks).

| Column | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| event_source | string | e.g., `api_football`, `sportmonks` |
| external_event_id | string | Provider's unique event identifier |
| processed_at | timestamp | |

---

## 7. Bet Statuses and State Transitions

### Status Definitions

| Status | Meaning |
|---|---|
| `OPEN` | Created by User A. User A's stake is locked. Visible on public feed. |
| `MATCHED` | User B accepted. Both stakes locked. Waiting for match result. |
| `PENDING_SETTLEMENT` | Match result confirmed. Settlement engine triggered but not yet complete. |
| `SETTLED` | Settlement complete. Locked stakes consumed; payouts and refunds credited to available balances. Outcome recorded. |
| `CANCELLED` | Cancelled by User A (OPEN status), or auto-cancelled when kickoff passes with no acceptance. User A's locked stake returned to available balance. |
| `VOIDED` | Match cancelled, postponed, or abandoned. Locked stakes returned to available balance for both users. No fee. |
| `UNDER_REVIEW` | Admin-flagged. Funds remain locked pending admin resolution. |

---

### State Transition Diagram

```
                    ┌─────────────────────────┐
                    │          OPEN            │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
    User A cancels         User B accepts     Kickoff passes /
    (or kickoff passes              │          match cancelled
    with no acceptance)             │          before acceptance
              │                    │                  │
              ▼                    ▼                  ▼
         CANCELLED             MATCHED          CANCELLED / VOIDED
                                   │
                     ┌─────────────┴──────────────┐
                     │                             │
           Match result confirmed        Match postponed /
                     │                   cancelled / abandoned
                     ▼                             │
           PENDING_SETTLEMENT                      ▼
                     │                           VOIDED
             Settlement runs
                     │
               ┌─────┴──────┐
               │             │
           SETTLED       UNDER_REVIEW
                         (admin flagged)
                              │
                     Admin resolves manually
                              │
                   ┌──────────┴──────────┐
                   ▼                     ▼
               SETTLED               VOIDED
```

---

### Allowed Transitions Table

| From | To | Trigger |
|---|---|---|
| OPEN | MATCHED | User B accepts |
| OPEN | CANCELLED | User A cancels, OR kickoff passes with no acceptance |
| OPEN | VOIDED | Match cancelled/postponed before any acceptance |
| MATCHED | PENDING_SETTLEMENT | Match result confirmed |
| MATCHED | VOIDED | Match postponed / abandoned after matching |
| MATCHED | UNDER_REVIEW | Admin flags bet |
| PENDING_SETTLEMENT | SETTLED | Settlement engine completes successfully |
| PENDING_SETTLEMENT | UNDER_REVIEW | Timeout exceeded, or admin flags |
| UNDER_REVIEW | SETTLED | Admin manually confirms result and triggers settlement |
| UNDER_REVIEW | VOIDED | Admin voids the bet |

**Any transition not in this table is invalid and must be rejected at the application layer.**

---

## 8. Wallet and Ledger Design

### 8.1 Dual Balance Model

Every user wallet maintains exactly two stored balance fields:

| Field | Definition | Can User Spend It? |
|---|---|---|
| `available_balance` | Funds the user can bet with, withdraw, or use freely | Yes |
| `locked_balance` | Funds reserved against an active (OPEN or MATCHED) bet | No |

`total_balance` is not stored. It is a computed value: `total_balance = available_balance + locked_balance`. Neither stored field may go below zero.

**Balance movements at each lifecycle stage:**

| Event | `available_balance` | `locked_balance` |
|---|---|---|
| Bet created (User A) | − stake_amount | + stake_amount |
| Bet accepted (User B) | − stake_amount | + stake_amount |
| Bet cancelled (OPEN) | + stake_amount | − stake_amount |
| Bet voided (any status) | + stake_amount (per user) | − stake_amount (per user) |
| Settlement: winner | + payout_amount (winner only) | − stake_amount (both users) |
| Settlement: no winner | + refund_amount (both users) | − stake_amount (both users) |

**At settlement, locked stakes are consumed (permanently deducted), not transferred. Payouts and refunds are fresh credits to `available_balance`. The platform fee is the difference between total stakes consumed and total amounts returned to users.**

---

### 8.2 Ledger as Source of Truth

The `available_balance` and `locked_balance` columns on the `wallets` table are a **performance cache** — derived state that can be recomputed at any time by replaying `ledger_entries`. If a discrepancy is ever found between the wallet balances and the ledger-derived totals, the ledger is authoritative.

A daily reconciliation job must verify that every wallet's cached balances match the ledger sum. Any discrepancy triggers an admin alert and a temporary hold on the affected wallet.

---

### 8.3 Ledger Entry Pairs

Operations that move funds between `available_balance` and `locked_balance` always produce **two ledger entries** in the same transaction — one debiting the source field and one crediting the destination field. Both entries share the same `reference_id`. Both record snapshots of `available_balance_after` and `locked_balance_after` reflecting the wallet state after the full operation.

Example — Bet creation (stake_amount = R1,000; wallet had available=R5,000, locked=R0 before):

| # | entry_type | balance_field | direction | amount | available_after | locked_after |
|---|---|---|---|---|---|---|
| 1 | `STAKE_LOCK` | `available` | debit | 1000.00 | 4000.00 | 1000.00 |
| 2 | `STAKE_LOCK` | `locked` | credit | 1000.00 | 4000.00 | 1000.00 |

*(Both entries snapshot the same post-operation wallet state.)*

---

### 8.4 Immutability

Ledger entries are **never updated or deleted**. Financial corrections are made by writing new compensating entries that reference the original. This mirrors standard double-entry bookkeeping and is an audit requirement.

---

### 8.5 Atomicity Requirement

Every wallet operation must:
1. Update the wallet's balance columns.
2. Write the corresponding ledger entry (or pair of entries).
3. Increment the wallet's `version` counter.

All three steps execute inside the same database transaction. There is no scenario in which a balance changes without a corresponding ledger entry.

---

### 8.6 Platform Fee Accounting

Platform fees are credited to the `platform_accounts` record for the relevant currency. This is not a user wallet — it is an internal financial account. Every fee credit writes a corresponding `platform_ledger_entries` row.

**End-to-end traceability requirement:** Every platform fee credit must be paired with explicit user-side deduction entries that occurred in the same settlement transaction. All entries — user-side and platform-side — carry the same `reference_id` (the bet_id). This means that for any fee collected, the following audit query must always resolve correctly:

```
SELECT * FROM ledger_entries WHERE reference_id = :bet_id
  → shows all user-side deductions that funded the fee

SELECT * FROM platform_ledger_entries WHERE reference_id = :bet_id
  → shows the platform fee credit that was funded by those deductions

Sum of user deductions − Sum of user credits = platform_fee amount ✓
```

The platform account balance can be reconciled against the sum of all `platform_ledger_entries` at any time. The sum of all user wallet balances (`available_balance + locked_balance` across all users) plus the platform account balance must always equal the sum of all deposits minus all withdrawals across the system. This is the master reconciliation invariant.

---

### 8.7 Currency Precision

All monetary values are stored as `decimal(15,2)`. All arithmetic must use decimal arithmetic — never floating-point. Rounding rule for fee calculations is an open item *(PO-06)* and must be resolved before implementation. The recommended default is **round half-up** to the nearest cent, with any sub-cent remainder credited to the platform. This must be documented and applied consistently.

---

## 9. Settlement Logic Design

### 9.1 Inputs

The Settlement Engine requires:
- The confirmed `outcome` from the `matches` table: `home_win`, `away_win`, or `draw`
- The `bets` record: `creator_prediction`, `opponent_prediction`, `stake_amount`, `status`
- The applicable fee rates from `fee_config` at the time of settlement

---

### 9.2 Settlement Path Decision

```
Given:
  match_outcome       ∈ { home_win, away_win, draw }
  creator_prediction  ∈ { home_win, away_win, draw }
  opponent_prediction ∈ { home_win, away_win, draw }
                      where opponent_prediction ≠ creator_prediction

Decision:
  IF   creator_prediction  == match_outcome  → PATH A: Creator wins
  ELIF opponent_prediction == match_outcome  → PATH B: Opponent wins
  ELSE                                       → PATH C: No winner
```

**Why PATH C is possible:** User A and User B each hold one of three possible outcomes. The match produces exactly one outcome. The only way neither user wins is if the match produces the third outcome — the one neither user selected. This is a valid, expected scenario.

**It is impossible for both users to win simultaneously** (they hold different predictions; only one outcome occurs).

---

### 9.3 Settlement Path A / B — There Is a Winner

**Fund flow overview:**
- Both users' locked stakes are **consumed** (deducted from `locked_balance`) in full.
- The winner receives a payout credited to their **`available_balance`**.
- The payout equals 90% of the total pool (both stakes combined).
- The platform receives 10% of the total pool as fee.
- The loser receives nothing. Their stake is fully consumed.
- The original locked stake is not "returned" to either user — it is consumed and replaced by the payout for the winner.

**Arithmetic (stake_amount = S, winner_fee_rate = r_w):**

```
total_pool    = S × 2
platform_fee  = total_pool × r_w          (e.g., S×2 × 0.10)
winner_payout = total_pool × (1 − r_w)    (e.g., S×2 × 0.90)

Sum check: platform_fee + winner_payout = total_pool ✓
```

**Numeric example — stake R1,000, winner fee 10%:**

```
total_pool    = R2,000.00
platform_fee  = R200.00  (10% of pool)
winner_payout = R1,800.00  (90% of pool, credited to winner's available_balance)
```

**Ledger entry sequence (all within one transaction, reference_id = bet_id for all entries):**

| Step | Who | Entry Type | balance_field | Direction | Amount | Notes |
|---|---|---|---|---|---|---|
| 1 | Winner | `SETTLEMENT_DEDUCT` | `locked` | debit | S | Winner's locked stake fully consumed |
| 2 | Loser | `SETTLEMENT_DEDUCT` | `locked` | debit | S | Loser's locked stake fully consumed |
| 3 | Winner | `PAYOUT_CREDIT` | `available` | credit | winner_payout | Net payout (90% of pool) credited to winner's available balance |
| 4 | Platform | `FEE_COLLECTION` | n/a | credit | platform_fee | Platform fee credited; funded by net of Steps 1+2 minus Step 3 |

**Fee traceability:** The platform fee (Step 4) is funded by the net surplus of user stake deductions over user payouts: (S + S) − winner_payout = 2S − 1.8S = 0.2S = platform_fee. All four entries share reference_id = bet_id. No funds are created or lost.

**Net balance impact:**

| Party | `available_balance` Δ | `locked_balance` Δ |
|---|---|---|
| Winner | + winner_payout (R1,800) | − S (R1,000) |
| Loser | 0 | − S (R1,000) |
| Platform | + platform_fee (R200) | n/a |

**End-to-end sum check (R1,000 stake):**
- Total deducted from user wallets: R1,000 + R1,000 = R2,000
- Credited to winner's available: R1,800
- Credited to platform: R200
- R1,800 + R200 = R2,000 ✓ No funds created or lost.

---

### 9.4 Settlement Path C — No Winner

**Fund flow overview:**
- Both users' locked stakes are **consumed** (deducted from `locked_balance`) in full.
- 5% of each user's stake is collected as platform fee (deducted first, before any refund).
- 95% of each user's stake is refunded, credited to their **`available_balance`**.
- The platform fee is explicitly sourced from user-side `FEE_DEDUCT` entries, making it fully traceable.

**Arithmetic (stake_amount = S, no_winner_fee_rate = r_n):**

```
fee_per_user    = S × r_n               (e.g., S × 0.05)
refund_per_user = S × (1 − r_n)         (e.g., S × 0.95)
total_fee       = fee_per_user × 2

Sum check: (fee_per_user + refund_per_user) × 2 = S × 2 ✓
```

**Numeric example — stake R1,000, no-winner fee 5%:**

```
fee_per_user    = R50.00   (5% of stake, deducted from locked)
refund_per_user = R950.00  (95% of stake, credited to available)
total_fee       = R100.00
```

**Ledger entry sequence (all within one transaction, reference_id = bet_id for all entries):**

| Step | Who | Entry Type | balance_field | Direction | Amount | Notes |
|---|---|---|---|---|---|---|
| 1 | User A | `FEE_DEDUCT` | `locked` | debit | fee_per_user | User A's platform fee portion deducted from locked stake |
| 2 | User A | `SETTLEMENT_DEDUCT` | `locked` | debit | refund_per_user | Remaining locked stake (refund portion) consumed |
| 3 | User A | `REFUND_CREDIT` | `available` | credit | refund_per_user | Refund credited to User A's available balance |
| 4 | User B | `FEE_DEDUCT` | `locked` | debit | fee_per_user | User B's platform fee portion deducted from locked stake |
| 5 | User B | `SETTLEMENT_DEDUCT` | `locked` | debit | refund_per_user | Remaining locked stake (refund portion) consumed |
| 6 | User B | `REFUND_CREDIT` | `available` | credit | refund_per_user | Refund credited to User B's available balance |
| 7 | Platform | `FEE_COLLECTION_NO_WINNER` | n/a | credit | total_fee | Platform fee credit funded explicitly by Steps 1 and 4 |

**Fee traceability:** Steps 1 and 4 are the explicit user-side fee deductions (FEE_DEDUCT from each user's locked balance). Step 7 is the corresponding platform-side credit. All seven entries share reference_id = bet_id. The sum of Steps 1 and 4 equals the amount in Step 7: fee_per_user + fee_per_user = total_fee ✓.

**Net balance impact:**

| Party | `available_balance` Δ | `locked_balance` Δ |
|---|---|---|
| User A | + refund_per_user (R950) | − S (R1,000) |
| User B | + refund_per_user (R950) | − S (R1,000) |
| Platform | + total_fee (R100) | n/a |

**End-to-end sum check (R1,000 stake):**
- Total deducted from User A locked: R50 (fee) + R950 (refund portion) = R1,000
- Total deducted from User B locked: R50 (fee) + R950 (refund portion) = R1,000
- Total deducted from all users: R2,000
- Credited to User A available: R950
- Credited to User B available: R950
- Credited to platform: R100
- R950 + R950 + R100 = R2,000 ✓ No funds created or lost.

---

### 9.5 Settlement Path — Void / Full Refund

**Conditions:** Match cancelled, postponed, abandoned, or admin void.

**Fund flow:** Each user's locked stake is released in full back to their `available_balance`. No fee is collected. No platform ledger entry is written.

**Arithmetic:**
```
refund_per_user = S (full stake, no fee deducted)
platform_fee    = 0
```

**Ledger entry sequence (reference_id = bet_id for all entries):**

| Step | Who | Entry Type | balance_field | Direction | Amount | Notes |
|---|---|---|---|---|---|---|
| 1 | User A | `VOID_REFUND` | `locked` | debit | S | User A's locked stake released |
| 2 | User A | `VOID_REFUND` | `available` | credit | S | Full stake restored to User A's available balance |
| 3 | User B | `VOID_REFUND` | `locked` | debit | S | User B's locked stake released |
| 4 | User B | `VOID_REFUND` | `available` | credit | S | Full stake restored to User B's available balance |

*(If the bet was only OPEN at void time — User B has no locked stake — only steps 1 and 2 apply.)*

---

### 9.6 Recording Fee Rates on the Bet

At settlement time, the Settlement Engine must write the resolved fee rates to the `bets` record:
- `applied_winner_fee_rate` if PATH A or B
- `applied_no_winner_fee_rate` if PATH C

This ensures that historical bet records are self-contained and correct even if fee rates are changed in `fee_config` later.

---

### 9.7 Idempotency Guard

Before executing any settlement:
1. Verify `bets.status = 'PENDING_SETTLEMENT'`.
2. Execute all fund movements inside one transaction.
3. The final write in the transaction must be:
   `UPDATE bets SET status = 'SETTLED', settlement_outcome = ?, ... WHERE id = ? AND status = 'PENDING_SETTLEMENT'`
4. If this update affects 0 rows, abort. Another process has already settled this bet. Log a warning and exit. Do not roll back any funds — none were moved because the update is the final step.

---

## 10. Validation Rules

### 10.1 Bet Creation Validations

| Rule | Rejection Reason |
|---|---|
| Match must exist in local `matches` table | Match not found |
| Match status must be `scheduled` | Match unavailable for betting |
| Current time must be before `kickoff_at` minus pre-kickoff buffer *(PO-05)* | Too close to kickoff |
| `creator_prediction` must be one of: `home_win`, `away_win`, `draw` | Invalid prediction value |
| `stake_amount` must be ≥ minimum stake *(PO-02)* | Below minimum stake |
| `stake_amount` must be ≤ maximum stake *(PO-02)* | Exceeds maximum stake |
| `stake_amount` must be ≤ creator's `available_balance` | Insufficient funds |
| Creator account status must be `active` | Account ineligible |

**Note:** A user may create multiple bets on the same match with any prediction, including the same prediction as a prior bet. No uniqueness constraint applies to `(creator_id, match_id)` or `(creator_id, match_id, creator_prediction)`.

---

### 10.2 Bet Acceptance Validations

| Rule | Rejection Reason |
|---|---|
| Bet must exist | Bet not found |
| Bet status must be `OPEN` | Bet no longer available |
| Current time must be before `expires_at` | Bet has expired |
| `opponent_id` must not equal `creator_id` | Cannot accept own bet |
| `opponent_prediction` must not equal `creator_prediction` | Prediction conflicts with creator |
| `opponent_prediction` must be one of the two non-creator outcomes | Invalid prediction value |
| Opponent's `available_balance` must be ≥ `stake_amount` | Insufficient funds |
| Opponent account status must be `active` | Account ineligible |

---

### 10.3 Bet Cancellation Validations

| Rule | Rejection Reason |
|---|---|
| Requesting user must be `creator_id` | Not authorised |
| Bet status must be `OPEN` | Cannot cancel a matched or settled bet |

---

## 11. Concurrency and Transaction-Safety Considerations

These are hard requirements. Financial systems fail in non-obvious ways under concurrent load.

---

### 11.1 Bet Acceptance Race Condition
**Problem:** Two users accept the same OPEN bet simultaneously.
**Solution:** Issue `SELECT FOR UPDATE` on the `bets` row when processing acceptance. First transaction acquires lock, validates OPEN, writes acceptance, transitions to MATCHED, commits. Second transaction acquires lock, finds MATCHED, returns error. No funds locked for second user.

---

### 11.2 Concurrent Wallet Operations
**Problem:** User creates two bets simultaneously, both check balance before either lock commits.
**Solution:** Use `SELECT FOR UPDATE` on the `wallets` row within the bet creation transaction. Alternatively, use optimistic locking via the `version` counter: `UPDATE wallets SET available_balance = ?, locked_balance = ?, version = version + 1 WHERE id = ? AND version = ?`. If 0 rows are affected, retry. If balance is now insufficient after retry, reject.

For MVP, `SELECT FOR UPDATE` on the wallet row is the simpler and safer choice. It serialises wallet operations for a single user, which is acceptable at MVP scale.

---

### 11.3 Duplicate Settlement Prevention
**Problem:** Settlement job triggers twice due to cron overlap or webhook retry.
**Solution:** Two independent guards:
1. **Status conditional update:** `WHERE status = 'PENDING_SETTLEMENT'` in the final settlement write. If 0 rows, abort.
2. **Event deduplication:** Incoming match result events are checked against `processed_events` before triggering settlement. Duplicates are discarded.

Both guards must be present. Either alone is sufficient in most cases; together they cover edge cases where the event is new but the settlement already ran.

---

### 11.4 Atomic Status + Money Transitions
**Problem:** A status change and its associated money movements must both succeed or both fail.
**Solution:** Every state transition involving money wraps the status update and all wallet/ledger writes in a single database transaction. If any write fails, the full transaction rolls back and the bet returns to its previous status automatically.

---

### 11.5 Keep Transactions Short
**Guidance:** Perform all validation reads (balance checks, status checks, fee rate lookups) before opening the transaction. Inside the transaction, execute only the writes and the final atomic status check. Long-held locks cause deadlocks and timeouts downstream.

---

### 11.6 Idempotent Webhook Processing
**Problem:** Match result webhooks may be delivered more than once.
**Solution:** On receipt, check the provider's event ID against `processed_events`. If present, discard and return HTTP 200. If absent, insert into `processed_events` first (within the same transaction that triggers settlement), then proceed.

---

## 12. Suggested API Surface (High Level)

All endpoints REST. Authentication via Bearer JWT. All monetary values serialised as decimal strings — never floating-point numbers — in all request and response payloads.

---

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Authenticate; receive JWT |
| POST | `/auth/logout` | Invalidate token |

---

### Matches
| Method | Endpoint | Description |
|---|---|---|
| GET | `/matches` | List upcoming available matches (paginated; filterable by competition, date) |
| GET | `/matches/:id` | Get single match detail |

---

### Bets
| Method | Endpoint | Description |
|---|---|---|
| POST | `/bets` | Create a new bet (User A) |
| GET | `/bets/open` | Public feed of OPEN bets only (paginated; filterable by match, stake range). Requires authentication for MVP. Returns only bets in OPEN status that have not yet reached kickoff. |
| GET | `/bets/my` | Get the authenticated user's full bet history across all statuses (paginated) |
| GET | `/bets/:id` | Get single bet detail |
| POST | `/bets/:id/accept` | Accept a bet as User B (include `opponent_prediction` in body) |
| POST | `/bets/:id/cancel` | Cancel a bet (User A, OPEN status only) |

**Routing note:** `/bets/open` and `/bets/my` are static path segments and must be registered before the dynamic `/bets/:id` route to avoid the static segments being interpreted as `id` values.

---

### Wallet
| Method | Endpoint | Description |
|---|---|---|
| GET | `/wallet` | Get wallet balances: `available_balance`, `locked_balance`, and computed `total_balance` (= available + locked), and `currency` |
| GET | `/wallet/transactions` | Paginated ledger history for the authenticated user |
| POST | `/wallet/deposit` | Initiate deposit (MVP: manual / stub) |
| POST | `/wallet/withdraw` | Initiate withdrawal request |

**Note on `total_balance` in the API response:** `total_balance` is a computed field returned in the API response for convenience. It is not stored in the `wallets` table. The server computes it as `available_balance + locked_balance` at response serialisation time.

---

### Notifications
| Method | Endpoint | Description |
|---|---|---|
| GET | `/notifications` | Get notifications (paginated) |
| POST | `/notifications/:id/read` | Mark notification as read |

---

### Admin (role: `admin`)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/admin/bets` | View and filter all bets |
| POST | `/admin/bets/:id/void` | Void a bet (requires reason) |
| POST | `/admin/matches/:id/result` | Manually set or override match result |
| GET | `/admin/users` | List users |
| POST | `/admin/users/:id/suspend` | Suspend a user account |
| GET | `/admin/ledger` | View platform-wide ledger entries |
| GET | `/admin/platform/balance` | View platform fee account balance and history |
| GET | `/admin/fee-config` | View current and historical fee rates |
| POST | `/admin/fee-config` | Set a new fee rate (effective from a given timestamp) |

---

### Internal / Webhooks
| Method | Endpoint | Description |
|---|---|---|
| POST | `/webhooks/match-result` | Receive match result notification from data provider |

---

## 13. Admin and Operations Considerations

### 13.1 Match Result Override
Admins must be able to manually confirm or override a match result when the automated feed fails or delivers incorrect data. Requirements:
- Mandatory reason field (recorded in `bet_events` with admin actor ID)
- Triggers the normal settlement flow
- Irreversible once settlement executes

---

### 13.2 Manual Bet Voiding
Admins must be able to void any bet in OPEN, MATCHED, or PENDING_SETTLEMENT status. Voiding triggers the full refund path (no fee). Reason is mandatory. Logged to `bet_events`.

---

### 13.3 Reconciliation Tooling
A daily reconciliation report must verify:
- Sum of all user `available_balance` + `locked_balance` (across all wallets) = sum of all deposits − sum of all withdrawals − sum of all platform fees collected
- Every wallet's balance matches the sum computed from its ledger entries
- Platform account balance matches the sum of `platform_ledger_entries`
- For every `platform_ledger_entries` row: the linked user-side ledger entries (same `reference_id`) sum to the correct fee amount
- Any discrepancy triggers an immediate admin alert and a hold on the affected wallet(s)

---

### 13.4 Settlement Monitoring
Operations must be alerted if any bet remains in `PENDING_SETTLEMENT` beyond a configurable threshold (e.g., 4 hours after match kickoff). A "stuck bets" dashboard view is required for ops triage.

---

### 13.5 Fee Rate Configuration
Fee rates in `fee_config` are admin-editable. New rates take effect from the `effective_from` timestamp. Old rates are never deleted — they are retained for historical accuracy. The Settlement Engine always applies the rate active at the time of settlement, and records it on the `bets` row.

---

### 13.6 Data Retention
Ledger entries and `bet_events` are retained indefinitely. Bet and user records are retained for a minimum of 7 years for financial compliance purposes. *(Legal obligations must be confirmed for the applicable jurisdiction — PO-12.)*

---

## 14. Risks, Ambiguities, and Required Clarifications

### 14.1 Open Product Decisions (Require PO Input)

| # | Question | Impact |
|---|---|---|
| PO-01 | What currency is supported at launch? ZAR only? | Wallet and ledger schema; platform account setup |
| PO-02 | What are the minimum and maximum stake amounts? | Required for validation rules |
| PO-04 | What happens to a MATCHED bet when its match is postponed — void or carry over to the rescheduled date? | Significant settlement logic branch |
| PO-05 | How many minutes before kickoff should bet creation be locked? | Validation cutoff rule |
| PO-06 | What rounding rule applies to fee arithmetic? (Recommended: half-up; remainder to platform) | Financial precision requirement |
| PO-07 | Is KYC / identity verification required before a user can bet? | Auth and onboarding scope |
| PO-08 | What payment methods are in scope for deposit and withdrawal at MVP? | Wallet module scope |
| PO-09 | Should User A be able to see who has viewed their bet before acceptance? | Privacy and feed design |
| PO-10 | Should an OPEN bet auto-expire if no one accepts within X hours, even if kickoff has not yet passed? | Adds a time-based expiry dimension separate from kickoff |
| PO-11 | Which notification channels are required at MVP: in-app only, or also push / email / SMS? | Notification module scope |
| PO-12 | Does the platform require a gambling licence for the target jurisdiction? | Legal and compliance — highest business risk. South Africa's National Gambling Act requires a licence to operate. |

---

### 14.2 Technical Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Third-party match data provider downtime | High | Cache all data locally. Define a settlement timeout. Build a manual result-override path. Evaluate provider SLAs before selection. |
| Race condition on bet acceptance | High | `SELECT FOR UPDATE` on bet row. Load-test this path before launch. |
| Incorrect fee rounding causing ledger drift | Medium | Decimal arithmetic throughout. Automated reconciliation tests. |
| Duplicate settlement execution | High | Status conditional update + event deduplication. Both guards required. |
| Regulatory non-compliance | Critical | Legal review before launch. Operating without a gambling licence in South Africa is a criminal offence under the National Gambling Act. |
| User funds locked indefinitely (UNDER_REVIEW) | Medium | Define a maximum review period. Notify affected users. |
| Wallet balance drift over time | Medium | Daily automated reconciliation with alerts on any discrepancy greater than zero. |

---

### 14.3 Design Decisions Made (Record)

| Decision | Rationale |
|---|---|
| VOIDED bets carry no platform fee | Platform should not profit from outcomes it does not control (match authority decisions). Full refund preserves user trust. |
| Settlement engine is a separate module from Bet Management | Settlement is a financial operation with different atomicity and idempotency requirements. Separation prevents business logic from leaking into payment flows. |
| Ledger is immutable and append-only | Standard financial industry practice. Enables full audit trail and balance reconstruction from first principles. |
| Ledger entries snapshot both balance fields | Allows point-in-time wallet reconstruction without full history replay. Supports efficient dispute resolution. |
| Platform fees go to a dedicated `platform_accounts` entity | Makes fee revenue auditable, reportable, and reconcilable as a first-class financial account, not a side effect. |
| Platform fee entries and user deduction entries share `reference_id` (bet_id) | Every rand of platform fee revenue is traceable to the exact user-side deductions that sourced it. Enables end-to-end audit and reconciliation. |
| Fee rates stored in `fee_config`, applied rates recorded on `bets` | Allows fee changes without redeployment; historical bets remain accurate regardless of future rate changes. |
| `total_balance` is computed, not stored | Storing a derived value creates a consistency risk. `available_balance + locked_balance` is always the authoritative total; the sum is computed on read. |
| Multiple bets per user per match are allowed (PO-03a and PO-03b: YES) | Users may create multiple bets on the same match with different predictions or the same prediction. No uniqueness constraint prevents this. Locking in this decision removes ambiguity from validation rules and schema design. |
| MVP is a monolith with clear module boundaries | Faster to build and easier to debug. Module boundaries allow future extraction to services when load demands it. |
| `SELECT FOR UPDATE` on wallet rows at MVP | Simpler than optimistic locking and safe at MVP scale. Can be changed to optimistic locking if wallet contention becomes a bottleneck. |
| `GET /bets/open` is a dedicated endpoint separate from `GET /bets/my` | Public bet discovery and personal history are distinct use cases with different access control requirements. A dedicated open-feed endpoint is cleaner than relying on query parameters for status filtering. |

---

*End of Specification — Version 0.3*
*Next step: Product Owner resolution of all remaining PO-## items, particularly PO-06 (rounding) and PO-12 (licensing), before database schema generation and implementation planning begin.*
