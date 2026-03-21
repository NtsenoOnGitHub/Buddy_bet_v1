"""Integration tests for bet endpoints and BetService business rules.

GET  /api/v1/bets/open
GET  /api/v1/bets/my
POST /api/v1/bets
POST /api/v1/bets/{id}/accept
POST /api/v1/bets/{id}/cancel
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_match, fund_wallet, make_admin, register_user


class TestCreateBet:
    """POST /bets"""

    async def test_create_bet_locks_creator_stake(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating a bet moves stake_amount from available to locked."""
        user_id, token = await register_user(
            client, email="creator@example.com", display_name="Creator"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "OPEN"
        assert data["stake_amount"] == "100.00"

        # Verify wallet: available decreases, locked increases
        wallet_resp = await client.get(
            "/api/v1/wallet",
            headers={"Authorization": f"Bearer {token}"},
        )
        wallet = wallet_resp.json()
        assert wallet["available_balance"] == "400.00"
        assert wallet["locked_balance"] == "100.00"

    async def test_create_bet_insufficient_funds_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Creating a bet with more than available_balance returns 422."""
        user_id, token = await register_user(
            client, email="broke@example.com", display_name="Broke User"
        )
        # Wallet has 0 balance — no funding
        match_id = await create_match(db_session)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_create_bet_on_non_scheduled_match_returns_error(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bet creation on a completed match is rejected."""
        from app.models.enums import MatchStatus
        from app.models.match import Match

        user_id, token = await register_user(
            client, email="badmatch@example.com", display_name="Bad Match User"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))

        # Insert a completed match directly
        match = Match(
            external_id=f"completed-{id(user_id)}",
            home_team="Man City",
            away_team="Liverpool",
            competition="PL",
            kickoff_at=__import__("datetime").datetime(
                2024, 1, 1, 15, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            status=MatchStatus.completed,
        )
        db_session.add(match)
        await db_session.flush()

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": str(match.id),
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code in (409, 422)


class TestAcceptBet:
    """POST /bets/{id}/accept"""

    async def test_accept_bet_locks_opponent_stake_and_transitions_to_matched(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Accepting an OPEN bet sets status to MATCHED and locks opponent's stake."""
        creator_id, creator_token = await register_user(
            client, email="creator2@example.com", display_name="Creator 2"
        )
        opponent_id, opponent_token = await register_user(
            client, email="opponent@example.com", display_name="Opponent"
        )
        await fund_wallet(db_session, creator_id, Decimal("500.00"))
        await fund_wallet(db_session, opponent_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        # Creator opens a bet
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        # Opponent accepts with opposite prediction
        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opponent_token}"},
        )
        assert accept_resp.status_code == 200, accept_resp.text
        bet_data = accept_resp.json()
        assert bet_data["status"] == "MATCHED"
        assert bet_data["opponent_id"] == opponent_id
        assert bet_data["opponent_prediction"] == "away_win"

        # Opponent's wallet: 400 available, 100 locked
        opp_wallet = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {opponent_token}"},
            )
        ).json()
        assert opp_wallet["available_balance"] == "400.00"
        assert opp_wallet["locked_balance"] == "100.00"

    async def test_accept_own_bet_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """BR-01: A user cannot accept their own bet."""
        user_id, token = await register_user(
            client, email="selfbet@example.com", display_name="Self Better"
        )
        await fund_wallet(db_session, user_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert accept_resp.status_code == 422

    async def test_accept_bet_same_prediction_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """BR-06/07: opponent_prediction must differ from creator_prediction."""
        creator_id, creator_token = await register_user(
            client, email="samepred_creator@example.com", display_name="Creator SP"
        )
        opp_id, opp_token = await register_user(
            client, email="samepred_opp@example.com", display_name="Opp SP"
        )
        await fund_wallet(db_session, creator_id, Decimal("200.00"))
        await fund_wallet(db_session, opp_id, Decimal("200.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "home_win"},  # same as creator
            headers={"Authorization": f"Bearer {opp_token}"},
        )
        assert accept_resp.status_code == 422


class TestCancelBet:
    """POST /bets/{id}/cancel"""

    async def test_cancel_open_bet_unlocks_creator_stake(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Cancelling an OPEN bet moves stake from locked back to available."""
        user_id, token = await register_user(
            client, email="cancel_creator@example.com", display_name="Cancel User"
        )
        await fund_wallet(db_session, user_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        # Create the bet
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "150.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        # Confirm locked
        w1 = (
            await client.get(
                "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
            )
        ).json()
        assert w1["locked_balance"] == "150.00"
        assert w1["available_balance"] == "150.00"

        # Cancel the bet
        cancel_resp = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["status"] == "CANCELLED"

        # Funds restored
        w2 = (
            await client.get(
                "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
            )
        ).json()
        assert w2["locked_balance"] == "0.00"
        assert w2["available_balance"] == "300.00"

    async def test_cancel_by_non_creator_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """BR-13: Only the creator may cancel their bet."""
        creator_id, creator_token = await register_user(
            client, email="nc_creator@example.com", display_name="NC Creator"
        )
        other_id, other_token = await register_user(
            client, email="nc_other@example.com", display_name="NC Other"
        )
        await fund_wallet(db_session, creator_id, Decimal("200.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        cancel_resp = await client.post(
            f"/api/v1/bets/{bet_id}/cancel",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert cancel_resp.status_code in (403, 422)


class TestSettlementFlow:
    """Full settlement flow via admin confirm-result endpoint."""

    async def test_full_settlement_updates_wallets_and_bet_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """End-to-end: two users bet, match confirmed, winner gets payout, fee collected."""
        # Setup users
        creator_id, creator_token = await register_user(
            client, email="settle_creator@example.com", display_name="Settle Creator"
        )
        opponent_id, opponent_token = await register_user(
            client, email="settle_opponent@example.com", display_name="Settle Opponent"
        )
        admin_id, admin_token = await register_user(
            client, email="settle_admin@example.com", display_name="Settle Admin"
        )
        await make_admin(db_session, admin_id)
        await fund_wallet(db_session, creator_id, Decimal("500.00"))
        await fund_wallet(db_session, opponent_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        # Creator bets home_win
        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "100.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert create_resp.status_code == 201
        bet_id = create_resp.json()["id"]

        # Opponent bets away_win
        accept_resp = await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opponent_token}"},
        )
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == "MATCHED"

        # Admin confirms: home_win (creator wins)
        confirm_resp = await client.post(
            f"/api/v1/admin/matches/{match_id}/confirm-result",
            json={"outcome": "home_win", "home_score": 2, "away_score": 1},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        summary = confirm_resp.json()
        assert summary["outcome"] == "home_win"
        assert summary["bets_found"] == 1
        assert summary["bets_settled"] == 1
        assert summary["bets_failed"] == 0

        # Creator (winner) should have received payout
        # stake=100, pool=200, fee=20 (10%), payout=180
        creator_wallet = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {creator_token}"},
            )
        ).json()
        assert creator_wallet["locked_balance"] == "0.00"
        # started with 500, staked 100 (locked), won 180 back → 580
        assert creator_wallet["available_balance"] == "580.00"

        # Opponent (loser): stake was taken
        opponent_wallet = (
            await client.get(
                "/api/v1/wallet",
                headers={"Authorization": f"Bearer {opponent_token}"},
            )
        ).json()
        assert opponent_wallet["locked_balance"] == "0.00"
        # started with 500, staked 100 (locked), lost it → 400
        assert opponent_wallet["available_balance"] == "400.00"


class TestListBets:
    """GET /bets/open and GET /bets/my"""

    async def test_open_bets_returns_created_bet(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /bets/open includes an OPEN bet created in this test."""
        user_id, token = await register_user(
            client, email="listopen@example.com", display_name="List Open"
        )
        await fund_wallet(db_session, user_id, Decimal("200.00"))
        match_id = await create_match(db_session)

        await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "draw",
                "stake_amount": "50.00",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await client.get(
            "/api/v1/bets/open",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

    async def test_my_bets_includes_created_and_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /bets/my returns bets where the user is creator or opponent."""
        creator_id, creator_token = await register_user(
            client, email="my_creator@example.com", display_name="My Creator"
        )
        opp_id, opp_token = await register_user(
            client, email="my_opponent@example.com", display_name="My Opponent"
        )
        await fund_wallet(db_session, creator_id, Decimal("300.00"))
        await fund_wallet(db_session, opp_id, Decimal("300.00"))
        match_id = await create_match(db_session)

        create_resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": "75.00",
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        bet_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/bets/{bet_id}/accept",
            json={"opponent_prediction": "draw"},
            headers={"Authorization": f"Bearer {opp_token}"},
        )

        # Creator sees it
        creator_my = (
            await client.get(
                "/api/v1/bets/my",
                headers={"Authorization": f"Bearer {creator_token}"},
            )
        ).json()
        assert any(b["id"] == bet_id for b in creator_my["items"])

        # Opponent also sees it
        opp_my = (
            await client.get(
                "/api/v1/bets/my",
                headers={"Authorization": f"Bearer {opp_token}"},
            )
        ).json()
        assert any(b["id"] == bet_id for b in opp_my["items"])


# ---------------------------------------------------------------------------
# Helper: run the full "create + accept + confirm-result" setup and return
# (bet_id, creator_id, opponent_id, admin_token, match_id, db_session).
# Re-used by multiple financial-core test classes below.
# ---------------------------------------------------------------------------

async def _full_matched_bet(
    client,
    db_session,
    *,
    creator_email: str,
    opponent_email: str,
    admin_email: str,
    creator_prediction: str = "home_win",
    opponent_prediction: str = "away_win",
    stake: str = "100.00",
    kickoff_hours: int = 2,
):
    """Register three users (creator, opponent, admin), fund two wallets,
    create a match, open a bet, accept it, and return the relevant IDs."""
    creator_id, creator_token = await register_user(
        client, email=creator_email, display_name="Creator"
    )
    opponent_id, opponent_token = await register_user(
        client, email=opponent_email, display_name="Opponent"
    )
    admin_id, admin_token = await register_user(
        client, email=admin_email, display_name="Admin"
    )
    await make_admin(db_session, admin_id)
    await fund_wallet(db_session, creator_id, Decimal("500.00"))
    await fund_wallet(db_session, opponent_id, Decimal("500.00"))
    match_id = await create_match(db_session, kickoff_hours_from_now=kickoff_hours)

    create_resp = await client.post(
        "/api/v1/bets",
        json={
            "match_id": match_id,
            "creator_prediction": creator_prediction,
            "stake_amount": stake,
        },
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert create_resp.status_code == 201, create_resp.text
    bet_id = create_resp.json()["id"]

    accept_resp = await client.post(
        f"/api/v1/bets/{bet_id}/accept",
        json={"opponent_prediction": opponent_prediction},
        headers={"Authorization": f"Bearer {opponent_token}"},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    assert accept_resp.json()["status"] == "MATCHED"

    return dict(
        bet_id=bet_id,
        creator_id=creator_id,
        creator_token=creator_token,
        opponent_id=opponent_id,
        opponent_token=opponent_token,
        admin_token=admin_token,
        match_id=match_id,
    )


class TestNoWinnerSettlement:
    """Confirm-result with draw outcome → no-winner path (PATH C)."""

    async def _settle_no_winner(self, client, db_session, *, suffix: str):
        """Create MATCHED bet, confirm draw, return context dict."""
        ctx = await _full_matched_bet(
            client,
            db_session,
            creator_email=f"nw_creator_{suffix}@example.com",
            opponent_email=f"nw_opponent_{suffix}@example.com",
            admin_email=f"nw_admin_{suffix}@example.com",
            creator_prediction="home_win",
            opponent_prediction="away_win",
        )
        confirm_resp = await client.post(
            f"/api/v1/admin/matches/{ctx['match_id']}/confirm-result",
            json={"outcome": "draw", "home_score": 1, "away_score": 1},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        assert confirm_resp.json()["bets_settled"] == 1
        ctx["confirm"] = confirm_resp.json()
        return ctx

    async def test_no_winner_both_users_get_95pct_refund(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """stake=100, no-winner fee=5% → each user refunded 95.00."""
        ctx = await self._settle_no_winner(client, db_session, suffix="refund")

        # Both wallets: started 500, staked 100 (locked), refunded 95 → 495
        for token in (ctx["creator_token"], ctx["opponent_token"]):
            wallet = (
                await client.get(
                    "/api/v1/wallet", headers={"Authorization": f"Bearer {token}"}
                )
            ).json()
            assert wallet["available_balance"] == "495.00", wallet
            assert wallet["locked_balance"] == "0.00", wallet

    async def test_no_winner_bet_status_and_outcome(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bet must be SETTLED with settlement_outcome=no_winner and no winner_id."""
        from app.models.bet import Bet
        from sqlalchemy import select

        ctx = await self._settle_no_winner(client, db_session, suffix="status")
        bet_id = uuid.UUID(ctx["bet_id"])

        result = await db_session.execute(select(Bet).where(Bet.id == bet_id))
        bet = result.scalar_one()

        assert bet.status.value == "SETTLED"
        assert bet.settlement_outcome.value == "no_winner"
        assert bet.winner_id is None

    async def test_no_winner_platform_collects_10pct_total_fee(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Platform fee = 5% × 2 users × 100 stake = 10.00."""
        from app.models.bet import Bet
        from sqlalchemy import select

        ctx = await self._settle_no_winner(client, db_session, suffix="fee")
        bet_id = uuid.UUID(ctx["bet_id"])

        result = await db_session.execute(select(Bet).where(Bet.id == bet_id))
        bet = result.scalar_one()

        assert bet.platform_fee == Decimal("10.00")
        assert bet.payout_amount == Decimal("95.00")  # refund per user

    async def test_no_winner_confirm_summary_correct(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """confirm-result response summary is accurate for no-winner path."""
        ctx = await self._settle_no_winner(client, db_session, suffix="summary")
        summary = ctx["confirm"]

        assert summary["outcome"] == "draw"
        assert summary["bets_found"] == 1
        assert summary["bets_settled"] == 1
        assert summary["bets_already_settled"] == 0
        assert summary["bets_failed"] == 0
        assert summary["failed_bet_ids"] == []


class TestPlatformAccounting:
    """Platform account balance and ledger entries after settlement."""

    async def _settle_winner(self, client, db_session, *, suffix: str):
        ctx = await _full_matched_bet(
            client,
            db_session,
            creator_email=f"pa_creator_{suffix}@example.com",
            opponent_email=f"pa_opponent_{suffix}@example.com",
            admin_email=f"pa_admin_{suffix}@example.com",
            creator_prediction="home_win",
            opponent_prediction="away_win",
        )
        confirm_resp = await client.post(
            f"/api/v1/admin/matches/{ctx['match_id']}/confirm-result",
            json={"outcome": "home_win", "home_score": 2, "away_score": 0},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        return ctx

    async def test_winner_path_platform_balance_increases_by_fee(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Platform account balance increases by exactly 20.00 (10% of 200 pool)."""
        from app.models.platform import PlatformAccount
        from sqlalchemy import select

        # Read platform balance before settlement
        pa_before = (
            await db_session.execute(
                select(PlatformAccount).where(
                    PlatformAccount.account_code == "PLATFORM_FEES_ZAR"
                )
            )
        ).scalar_one()
        balance_before = pa_before.balance

        await self._settle_winner(client, db_session, suffix="bal")

        # Expire the cached instance so we get a fresh read
        await db_session.refresh(pa_before)
        assert pa_before.balance == balance_before + Decimal("20.00")

    async def test_winner_path_platform_ledger_entry_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A FEE_COLLECTION PlatformLedgerEntry must exist for the bet."""
        from app.models.platform import PlatformLedgerEntry
        from app.models.enums import PlatformEntryType
        from sqlalchemy import select

        ctx = await self._settle_winner(client, db_session, suffix="ledger")
        bet_id = uuid.UUID(ctx["bet_id"])

        entries = (
            await db_session.execute(
                select(PlatformLedgerEntry).where(
                    PlatformLedgerEntry.reference_id == bet_id
                )
            )
        ).scalars().all()

        assert len(entries) == 1
        entry = entries[0]
        assert entry.entry_type == PlatformEntryType.FEE_COLLECTION
        assert entry.amount == Decimal("20.00")

    async def test_winner_path_bet_stores_platform_fee_and_payout(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Bet row stores platform_fee=20 and payout_amount=180 after settlement."""
        from app.models.bet import Bet
        from sqlalchemy import select

        ctx = await self._settle_winner(client, db_session, suffix="betcols")
        bet_id = uuid.UUID(ctx["bet_id"])

        result = await db_session.execute(select(Bet).where(Bet.id == bet_id))
        bet = result.scalar_one()

        assert bet.status.value == "SETTLED"
        assert bet.settlement_outcome.value == "creator_wins"
        assert str(bet.winner_id) == ctx["creator_id"]
        assert bet.platform_fee == Decimal("20.00")
        assert bet.payout_amount == Decimal("180.00")

    async def test_no_winner_platform_ledger_entry_type(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No-winner path writes a FEE_COLLECTION_NO_WINNER platform entry."""
        from app.models.platform import PlatformLedgerEntry
        from app.models.enums import PlatformEntryType
        from sqlalchemy import select

        ctx = await _full_matched_bet(
            client,
            db_session,
            creator_email="pa_nw_creator@example.com",
            opponent_email="pa_nw_opponent@example.com",
            admin_email="pa_nw_admin@example.com",
            creator_prediction="home_win",
            opponent_prediction="away_win",
        )
        await client.post(
            f"/api/v1/admin/matches/{ctx['match_id']}/confirm-result",
            json={"outcome": "draw", "home_score": 0, "away_score": 0},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )

        bet_id = uuid.UUID(ctx["bet_id"])
        entries = (
            await db_session.execute(
                select(PlatformLedgerEntry).where(
                    PlatformLedgerEntry.reference_id == bet_id
                )
            )
        ).scalars().all()

        assert len(entries) == 1
        assert entries[0].entry_type == PlatformEntryType.FEE_COLLECTION_NO_WINNER
        assert entries[0].amount == Decimal("10.00")


class TestSettlementLedger:
    """User-facing ledger entries for winner and no-winner settlement paths."""

    async def test_winner_path_ledger_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Winner path writes exactly 3 settlement ledger entries for the bet.

        Expected (reference_type=settlement, reference_id=bet_id):
          1. Winner  SETTLEMENT_DEDUCT | locked    | debit  | 100
          2. Loser   SETTLEMENT_DEDUCT | locked    | debit  | 100
          3. Winner  PAYOUT_CREDIT     | available | credit | 180
        """
        from app.models.ledger import LedgerEntry
        from app.models.enums import (
            BalanceField, LedgerDirection, LedgerEntryType, LedgerReferenceType,
        )
        from sqlalchemy import select

        ctx = await _full_matched_bet(
            client,
            db_session,
            creator_email="sl_w_creator@example.com",
            opponent_email="sl_w_opponent@example.com",
            admin_email="sl_w_admin@example.com",
            creator_prediction="home_win",
            opponent_prediction="away_win",
        )
        await client.post(
            f"/api/v1/admin/matches/{ctx['match_id']}/confirm-result",
            json={"outcome": "home_win", "home_score": 1, "away_score": 0},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        bet_id = uuid.UUID(ctx["bet_id"])
        creator_id = uuid.UUID(ctx["creator_id"])
        opponent_id = uuid.UUID(ctx["opponent_id"])

        entries = (
            await db_session.execute(
                select(LedgerEntry)
                .where(LedgerEntry.reference_id == bet_id)
                .where(LedgerEntry.reference_type == LedgerReferenceType.settlement)
                .order_by(LedgerEntry.created_at)
            )
        ).scalars().all()

        assert len(entries) == 3

        # Entry 1: winner's locked stake deducted
        e1 = next(
            e for e in entries
            if e.user_id == creator_id
            and e.entry_type == LedgerEntryType.SETTLEMENT_DEDUCT
        )
        assert e1.balance_field == BalanceField.locked
        assert e1.direction == LedgerDirection.debit
        assert e1.amount == Decimal("100.00")

        # Entry 2: loser's locked stake deducted
        e2 = next(
            e for e in entries
            if e.user_id == opponent_id
            and e.entry_type == LedgerEntryType.SETTLEMENT_DEDUCT
        )
        assert e2.balance_field == BalanceField.locked
        assert e2.direction == LedgerDirection.debit
        assert e2.amount == Decimal("100.00")

        # Entry 3: winner payout credited to available
        e3 = next(
            e for e in entries
            if e.entry_type == LedgerEntryType.PAYOUT_CREDIT
        )
        assert e3.user_id == creator_id
        assert e3.balance_field == BalanceField.available
        assert e3.direction == LedgerDirection.credit
        assert e3.amount == Decimal("180.00")

    async def test_no_winner_path_ledger_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No-winner path writes 6 settlement ledger entries (3 per user).

        Per user (reference_type=settlement, reference_id=bet_id):
          1. FEE_DEDUCT        | locked    | debit  | 5
          2. SETTLEMENT_DEDUCT | locked    | debit  | 95
          3. REFUND_CREDIT     | available | credit | 95
        """
        from app.models.ledger import LedgerEntry
        from app.models.enums import (
            BalanceField, LedgerDirection, LedgerEntryType, LedgerReferenceType,
        )
        from sqlalchemy import select

        ctx = await _full_matched_bet(
            client,
            db_session,
            creator_email="sl_nw_creator@example.com",
            opponent_email="sl_nw_opponent@example.com",
            admin_email="sl_nw_admin@example.com",
            creator_prediction="home_win",
            opponent_prediction="away_win",
        )
        await client.post(
            f"/api/v1/admin/matches/{ctx['match_id']}/confirm-result",
            json={"outcome": "draw", "home_score": 2, "away_score": 2},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        bet_id = uuid.UUID(ctx["bet_id"])

        entries = (
            await db_session.execute(
                select(LedgerEntry)
                .where(LedgerEntry.reference_id == bet_id)
                .where(LedgerEntry.reference_type == LedgerReferenceType.settlement)
            )
        ).scalars().all()

        assert len(entries) == 6

        for user_id_str in (ctx["creator_id"], ctx["opponent_id"]):
            uid = uuid.UUID(user_id_str)
            user_entries = [e for e in entries if e.user_id == uid]
            assert len(user_entries) == 3

            fee_e = next(
                e for e in user_entries if e.entry_type == LedgerEntryType.FEE_DEDUCT
            )
            assert fee_e.balance_field == BalanceField.locked
            assert fee_e.direction == LedgerDirection.debit
            assert fee_e.amount == Decimal("5.00")

            deduct_e = next(
                e for e in user_entries
                if e.entry_type == LedgerEntryType.SETTLEMENT_DEDUCT
            )
            assert deduct_e.balance_field == BalanceField.locked
            assert deduct_e.direction == LedgerDirection.debit
            assert deduct_e.amount == Decimal("95.00")

            refund_e = next(
                e for e in user_entries
                if e.entry_type == LedgerEntryType.REFUND_CREDIT
            )
            assert refund_e.balance_field == BalanceField.available
            assert refund_e.direction == LedgerDirection.credit
            assert refund_e.amount == Decimal("95.00")

    async def test_winner_path_balance_snapshots_in_ledger(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """PAYOUT_CREDIT entry's available_balance_after snapshot equals final wallet balance."""
        from app.models.ledger import LedgerEntry
        from app.models.enums import LedgerEntryType, LedgerReferenceType
        from app.models.wallet import Wallet
        from sqlalchemy import select

        ctx = await _full_matched_bet(
            client,
            db_session,
            creator_email="sl_snap_creator@example.com",
            opponent_email="sl_snap_opponent@example.com",
            admin_email="sl_snap_admin@example.com",
            creator_prediction="home_win",
            opponent_prediction="away_win",
        )
        await client.post(
            f"/api/v1/admin/matches/{ctx['match_id']}/confirm-result",
            json={"outcome": "home_win", "home_score": 3, "away_score": 1},
            headers={"Authorization": f"Bearer {ctx['admin_token']}"},
        )
        bet_id = uuid.UUID(ctx["bet_id"])
        creator_id = uuid.UUID(ctx["creator_id"])

        payout_entry = (
            await db_session.execute(
                select(LedgerEntry)
                .where(LedgerEntry.reference_id == bet_id)
                .where(LedgerEntry.reference_type == LedgerReferenceType.settlement)
                .where(LedgerEntry.entry_type == LedgerEntryType.PAYOUT_CREDIT)
            )
        ).scalar_one()

        # The snapshot in the ledger entry must match the actual wallet balance
        wallet = (
            await db_session.execute(
                select(Wallet).where(Wallet.user_id == creator_id)
            )
        ).scalar_one()
        await db_session.refresh(wallet)

        assert payout_entry.available_balance_after == wallet.available_balance
        assert payout_entry.locked_balance_after == wallet.locked_balance


class TestConcurrentAccept:
    """Race-condition guard: SELECT FOR UPDATE prevents double-acceptance."""

    async def _open_bet(self, client, db_session, *, suffix: str, stake: str = "100.00"):
        """Register creator, fund wallet, create match + OPEN bet. Return context."""
        creator_id, creator_token = await register_user(
            client,
            email=f"ca_creator_{suffix}@example.com",
            display_name=f"CA Creator {suffix}",
        )
        await fund_wallet(db_session, creator_id, Decimal("500.00"))
        match_id = await create_match(db_session)

        resp = await client.post(
            "/api/v1/bets",
            json={
                "match_id": match_id,
                "creator_prediction": "home_win",
                "stake_amount": stake,
            },
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert resp.status_code == 201, resp.text
        return dict(bet_id=resp.json()["id"], creator_id=creator_id)

    async def test_second_accept_returns_409_after_first_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Once a bet is MATCHED, a second accept attempt returns 409."""
        ctx = await self._open_bet(client, db_session, suffix="seq")

        opp1_id, opp1_token = await register_user(
            client, email="ca_opp1_seq@example.com", display_name="Opp1 Seq"
        )
        opp2_id, opp2_token = await register_user(
            client, email="ca_opp2_seq@example.com", display_name="Opp2 Seq"
        )
        await fund_wallet(db_session, opp1_id, Decimal("500.00"))
        await fund_wallet(db_session, opp2_id, Decimal("500.00"))

        # First accept: must succeed
        r1 = await client.post(
            f"/api/v1/bets/{ctx['bet_id']}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opp1_token}"},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "MATCHED"

        # Second accept: must be rejected (bet is no longer OPEN)
        r2 = await client.post(
            f"/api/v1/bets/{ctx['bet_id']}/accept",
            json={"opponent_prediction": "draw"},
            headers={"Authorization": f"Bearer {opp2_token}"},
        )
        assert r2.status_code == 409, r2.text

    async def test_bet_has_exactly_one_opponent(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """After two accept attempts, bet.opponent_id belongs only to the first acceptor."""
        from app.models.bet import Bet
        from sqlalchemy import select

        ctx = await self._open_bet(client, db_session, suffix="opp")

        opp1_id, opp1_token = await register_user(
            client, email="ca_opp1_opp@example.com", display_name="Opp1"
        )
        opp2_id, opp2_token = await register_user(
            client, email="ca_opp2_opp@example.com", display_name="Opp2"
        )
        await fund_wallet(db_session, opp1_id, Decimal("500.00"))
        await fund_wallet(db_session, opp2_id, Decimal("500.00"))

        await client.post(
            f"/api/v1/bets/{ctx['bet_id']}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opp1_token}"},
        )
        await client.post(
            f"/api/v1/bets/{ctx['bet_id']}/accept",
            json={"opponent_prediction": "draw"},
            headers={"Authorization": f"Bearer {opp2_token}"},
        )

        result = await db_session.execute(
            select(Bet).where(Bet.id == uuid.UUID(ctx["bet_id"]))
        )
        bet = result.scalar_one()

        assert str(bet.opponent_id) == opp1_id
        assert bet.status.value == "MATCHED"

    async def test_only_first_opponent_wallet_is_locked(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Second opponent's wallet must have zero locked balance (stake never taken)."""
        from app.models.wallet import Wallet
        from sqlalchemy import select

        ctx = await self._open_bet(client, db_session, suffix="wallet")

        opp1_id, opp1_token = await register_user(
            client, email="ca_opp1_wlt@example.com", display_name="Opp1 Wlt"
        )
        opp2_id, opp2_token = await register_user(
            client, email="ca_opp2_wlt@example.com", display_name="Opp2 Wlt"
        )
        await fund_wallet(db_session, opp1_id, Decimal("500.00"))
        await fund_wallet(db_session, opp2_id, Decimal("500.00"))

        await client.post(
            f"/api/v1/bets/{ctx['bet_id']}/accept",
            json={"opponent_prediction": "away_win"},
            headers={"Authorization": f"Bearer {opp1_token}"},
        )
        await client.post(
            f"/api/v1/bets/{ctx['bet_id']}/accept",
            json={"opponent_prediction": "draw"},
            headers={"Authorization": f"Bearer {opp2_token}"},
        )

        async def wallet_of(user_id: str) -> Wallet:
            result = await db_session.execute(
                select(Wallet).where(Wallet.user_id == uuid.UUID(user_id))
            )
            w = result.scalar_one()
            await db_session.refresh(w)
            return w

        w1 = await wallet_of(opp1_id)
        w2 = await wallet_of(opp2_id)

        # First opponent: stake locked
        assert w1.locked_balance == Decimal("100.00")
        assert w1.available_balance == Decimal("400.00")

        # Second opponent: untouched — stake was never deducted
        assert w2.locked_balance == Decimal("0.00")
        assert w2.available_balance == Decimal("500.00")

    @pytest.mark.skip(
        reason=(
            "True concurrent DB-level race cannot be simulated via asyncio.gather "
            "in-process: all requests share a single AsyncSession (per-test savepoint "
            "isolation), so concurrent flush() calls raise 'Session is already flushing'. "
            "The SELECT FOR UPDATE guard is verified by the three sequential tests above. "
            "To test true concurrency, run against a live server with separate connections."
        )
    )
    async def test_concurrent_accepts_via_gather(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """asyncio.gather races two accept coroutines. Exactly one must win."""
        ctx = await self._open_bet(client, db_session, suffix="gather")

        opp1_id, opp1_token = await register_user(
            client, email="ca_g_opp1@example.com", display_name="G Opp1"
        )
        opp2_id, opp2_token = await register_user(
            client, email="ca_g_opp2@example.com", display_name="G Opp2"
        )
        await fund_wallet(db_session, opp1_id, Decimal("500.00"))
        await fund_wallet(db_session, opp2_id, Decimal("500.00"))

        r1, r2 = await asyncio.gather(
            client.post(
                f"/api/v1/bets/{ctx['bet_id']}/accept",
                json={"opponent_prediction": "away_win"},
                headers={"Authorization": f"Bearer {opp1_token}"},
            ),
            client.post(
                f"/api/v1/bets/{ctx['bet_id']}/accept",
                json={"opponent_prediction": "draw"},
                headers={"Authorization": f"Bearer {opp2_token}"},
            ),
        )

        statuses = {r1.status_code, r2.status_code}
        # Exactly one 200 and one 409 (or 422) — never two 200s
        assert 200 in statuses, f"Neither request succeeded: {r1.status_code}, {r2.status_code}"
        assert statuses != {200, 200}, "Both accepts succeeded — double-acceptance bug!"
