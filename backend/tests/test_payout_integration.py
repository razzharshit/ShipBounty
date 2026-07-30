from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.bounty_domain import ClaimStatus, PayoutAttemptState, PayoutState
from app.models.notification import DomainEvent
from app.models.payout_integration import (
    LedgerEntryType,
    TreasuryApprovalDecision,
    TreasuryEnvironment,
)
from app.services.bounty_service import create_payout
from app.models.score import ImmutableRecordError
from app.services.payout_integration_service import (
    PayoutControlError,
    PayoutProviderUnavailable,
    approve_treasury_payout,
    create_treasury_account,
    reconcile_payout,
    reconcile_treasury_balance,
    set_treasury_pause,
    submit_payout,
    treasury_ledger_balances,
)
from app.services.payout_providers import (
    BaseSepoliaCustodyProvider,
    DestinationValidation,
    PayoutProviderStatus,
    PayoutSubmissionRequest,
    PayoutSubmissionResult,
    ProviderTransferStatus,
    TreasuryBalanceResult,
)
from test_bounty_domain import _approved_claim_graph


class FakePayoutProvider:
    key = "fake"

    def __init__(self):
        self.submission_calls = 0
        self.fail_next_submission = False
        self.balance = Decimal("874.5")
        self.status = PayoutProviderStatus(
            provider_reference="provider-payout-1",
            status=ProviderTransferStatus.SUBMITTED,
            transaction_hash="0x" + "1" * 64,
            confirmations=0,
            raw_response={"status": "submitted"},
        )

    def validate_destination(self, *, destination, chain, currency):
        return DestinationValidation(
            valid=bool(destination),
            normalized_destination=destination.lower(),
        )

    def submit(self, request):
        self.submission_calls += 1
        if self.fail_next_submission:
            self.fail_next_submission = False
            raise RuntimeError("custody timeout")
        return PayoutSubmissionResult(
            provider_reference="provider-payout-1",
            status=ProviderTransferStatus.SUBMITTED,
            transaction_hash="0x" + "1" * 64,
            explorer_url="https://explorer.test/tx/" + "1" * 64,
            simulation_result={"passed": True},
            raw_response={"status": "submitted"},
        )

    def get_status(self, provider_reference):
        return self.status

    def find_by_idempotency_key(self, idempotency_key):
        return None

    def build_explorer_url(self, transaction_hash):
        return f"https://explorer.test/tx/{transaction_hash}"

    def get_balance(
        self, *, treasury_address, asset_contract_address, currency
    ):
        return TreasuryBalanceResult(
            observed_balance=self.balance,
            raw_response={"balance": str(self.balance)},
        )


def _integrated_payout(
    db,
    provider,
    *,
    opening_balance=Decimal("1000"),
    per_payout_limit=Decimal("500"),
):
    graph = _approved_claim_graph(db)
    treasury = create_treasury_account(
        db,
        organization=graph["repository"].organization,
        provider_key=provider.key,
        environment=TreasuryEnvironment.TESTNET,
        chain="base",
        currency="USDC",
        treasury_address="treasury:test",
        asset_contract_address=None,
        asset_decimals=6,
        custody_model="off_chain",
        opening_balance=opening_balance,
        per_payout_limit=per_payout_limit,
        daily_spending_limit=Decimal("750"),
        manual_approval_threshold=Decimal("100"),
        standard_required_approvals=1,
        high_value_required_approvals=2,
        required_confirmations=2,
        simulation_required=True,
        provider_config={"account": "test"},
        created_by_user_id=graph["approver"].id,
        providers={provider.key: provider},
    )
    set_treasury_pause(
        db,
        treasury=treasury,
        paused=False,
        reason="Test treasury activated",
    )
    payout, _ = create_payout(
        db,
        claim=graph["claim"],
        idempotency_key="integrated-payout-0001",
        treasury_account=treasury,
    )
    return graph, treasury, payout


def _approve_high_value_payout(db, graph, payout, provider):
    first, _ = approve_treasury_payout(
        db,
        payout=payout,
        approver_user_id=graph["approver"].id,
        decision=TreasuryApprovalDecision.APPROVED,
        reason="First treasury signer",
        providers={provider.key: provider},
    )
    assert payout.state == PayoutState.CREATED
    second, _ = approve_treasury_payout(
        db,
        payout=payout,
        approver_user_id=graph["second_approver"].id,
        decision=TreasuryApprovalDecision.APPROVED,
        reason="Second treasury signer",
        providers={provider.key: provider},
    )
    return first, second


def test_high_value_payout_requires_two_approvals_and_reserves_ledger(
    session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "PAYOUTS_EMERGENCY_PAUSED", False)
    db = session_factory()
    try:
        provider = FakePayoutProvider()
        graph, treasury, payout = _integrated_payout(db, provider)

        first, second = _approve_high_value_payout(
            db, graph, payout, provider
        )
        balances = treasury_ledger_balances(db, treasury)

        assert first.approver_user_id != second.approver_user_id
        assert payout.state == PayoutState.AUTHORIZED
        assert payout.authorized_by_user_id == graph["second_approver"].id
        assert balances == {
            "available": Decimal("874.500000"),
            "reserved": Decimal("125.500000"),
            "settled": Decimal("0.000000"),
        }
        assert treasury.ledger_entries[0].entry_type == LedgerEntryType.RESERVATION
    finally:
        db.close()


def test_emergency_and_treasury_pauses_block_authorization(
    session_factory, monkeypatch
):
    db = session_factory()
    try:
        provider = FakePayoutProvider()
        graph, treasury, payout = _integrated_payout(db, provider)
        treasury_id = treasury.id
        payout_id = payout.id
        approver_id = graph["approver"].id
        db.commit()

        with pytest.raises(PayoutControlError, match="emergency pause"):
            approve_treasury_payout(
                db,
                payout=payout,
                approver_user_id=approver_id,
                decision=TreasuryApprovalDecision.APPROVED,
                reason=None,
                providers={provider.key: provider},
            )
        db.rollback()

        monkeypatch.setattr(settings, "PAYOUTS_EMERGENCY_PAUSED", False)
        treasury = db.get(type(treasury), treasury_id)
        payout = db.get(type(payout), payout_id)
        set_treasury_pause(
            db,
            treasury=treasury,
            paused=True,
            reason="Emergency drill",
        )
        with pytest.raises(PayoutControlError, match="Treasury is paused"):
            approve_treasury_payout(
                db,
                payout=payout,
                approver_user_id=approver_id,
                decision=TreasuryApprovalDecision.APPROVED,
                reason=None,
                providers={provider.key: provider},
            )
    finally:
        db.rollback()
        db.close()


def test_spending_limit_blocks_reservation(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "PAYOUTS_EMERGENCY_PAUSED", False)
    db = session_factory()
    try:
        provider = FakePayoutProvider()
        graph, treasury, payout = _integrated_payout(
            db, provider, per_payout_limit=Decimal("100")
        )

        with pytest.raises(PayoutControlError, match="per-payout limit"):
            approve_treasury_payout(
                db,
                payout=payout,
                approver_user_id=graph["approver"].id,
                decision=TreasuryApprovalDecision.APPROVED,
                reason="Should not reserve",
                providers={provider.key: provider},
            )

        assert payout.state == PayoutState.CREATED
        assert treasury_ledger_balances(db, treasury)["reserved"] == 0
    finally:
        db.rollback()
        db.close()


def test_ledger_entries_are_immutable(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "PAYOUTS_EMERGENCY_PAUSED", False)
    db = session_factory()
    try:
        provider = FakePayoutProvider()
        graph, treasury, payout = _integrated_payout(db, provider)
        _approve_high_value_payout(db, graph, payout, provider)
        entry = treasury.ledger_entries[0]
        entry.available_delta = Decimal("0")

        with pytest.raises(ImmutableRecordError, match="insert-only"):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_provider_submission_and_confirmation_reconcile_ledger(
    session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "PAYOUTS_EMERGENCY_PAUSED", False)
    monkeypatch.setattr(settings, "PAYOUTS_ENABLED", True)
    db = session_factory()
    try:
        provider = FakePayoutProvider()
        graph, treasury, payout = _integrated_payout(db, provider)
        _approve_high_value_payout(db, graph, payout, provider)

        attempt, created = submit_payout(
            db,
            payout=payout,
            idempotency_key="provider-submit-0001",
            providers={provider.key: provider},
        )
        assert created is True
        assert attempt.state == PayoutAttemptState.SUBMITTED
        assert attempt.simulation_result == {"passed": True}
        assert payout.state == PayoutState.SUBMITTED
        assert payout.transaction_hash == "0x" + "1" * 64
        assert payout.explorer_url.startswith("https://explorer.test/")

        provider.status = PayoutProviderStatus(
            provider_reference="provider-payout-1",
            status=ProviderTransferStatus.CONFIRMED,
            transaction_hash=payout.transaction_hash,
            confirmations=2,
            raw_response={"status": "confirmed", "confirmations": 2},
        )
        reconciliation = reconcile_payout(
            db, payout=payout, providers={provider.key: provider}
        )
        balances = treasury_ledger_balances(db, treasury)
        balance_snapshot = reconcile_treasury_balance(
            db, treasury=treasury, providers={provider.key: provider}
        )

        assert reconciliation.outcome.value == "confirmed"
        assert payout.state == PayoutState.CONFIRMED
        assert graph["claim"].status == ClaimStatus.PAID
        assert balances == {
            "available": Decimal("874.500000"),
            "reserved": Decimal("0.000000"),
            "settled": Decimal("125.500000"),
        }
        assert balance_snapshot.observed_balance == Decimal("874.500000")
        assert treasury.observed_balance == Decimal("874.5")
        assert (
            db.query(DomainEvent)
            .filter(DomainEvent.event_type == "payout.confirmed")
            .count()
            == 1
        )
    finally:
        db.close()


def test_ambiguous_provider_timeout_reuses_same_idempotent_attempt(
    session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "PAYOUTS_EMERGENCY_PAUSED", False)
    monkeypatch.setattr(settings, "PAYOUTS_ENABLED", True)
    db = session_factory()
    try:
        provider = FakePayoutProvider()
        graph, _, payout = _integrated_payout(db, provider)
        _approve_high_value_payout(db, graph, payout, provider)
        provider.fail_next_submission = True

        with pytest.raises(PayoutProviderUnavailable, match="custody timeout"):
            submit_payout(
                db,
                payout=payout,
                idempotency_key="provider-submit-timeout",
                providers={provider.key: provider},
            )
        db.flush()
        assert payout.state == PayoutState.SUBMISSION_UNKNOWN
        assert (
            treasury_ledger_balances(db, payout.treasury_account)["reserved"]
            == payout.amount
        )
        attempt, created = submit_payout(
            db,
            payout=payout,
            idempotency_key="provider-submit-timeout",
            providers={provider.key: provider},
        )

        assert created is False
        assert attempt.attempt_number == 1
        assert attempt.state == PayoutAttemptState.SUBMITTED
        assert provider.submission_calls == 2
    finally:
        db.close()


def test_base_sepolia_provider_rejects_wrong_chain_and_builds_explorer_url():
    provider = BaseSepoliaCustodyProvider(
        base_url="https://custody.example",
        api_token="test",
    )

    invalid = provider.validate_destination(
        destination="0x" + "a" * 40,
        chain="base",
        currency="USDC",
    )
    valid = provider.validate_destination(
        destination="0x" + "A" * 40,
        chain="base-sepolia",
        currency="USDC",
    )

    assert invalid.valid is False
    assert valid.valid is True
    assert valid.normalized_destination == "0x" + "a" * 40
    assert provider.build_explorer_url("0x123").endswith("/tx/0x123")


def test_base_sepolia_provider_simulates_before_submission(monkeypatch):
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/simulate"):
            return Response({"passed": True, "simulation_id": "sim-1"})
        return Response(
            {
                "provider_reference": "safe-proposal-1",
                "status": "submitted",
                "transaction_hash": "0x" + "2" * 64,
                "confirmations": 0,
            }
        )

    monkeypatch.setattr("app.services.payout_providers.requests.post", post)
    provider = BaseSepoliaCustodyProvider(
        base_url="https://custody.example",
        api_token="test-token",
    )
    result = provider.submit(
        PayoutSubmissionRequest(
            payout_id=10,
            idempotency_key="base-submit-001",
            amount=Decimal("15.25"),
            currency="USDC",
            chain="base-sepolia",
            destination="0x" + "a" * 40,
            treasury_address="0x" + "b" * 40,
            asset_contract_address=settings.BASE_SEPOLIA_USDC_CONTRACT,
            asset_decimals=6,
            simulation_required=True,
            provider_config={"safe": "test"},
        )
    )

    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == [
        "simulate",
        "payouts",
    ]
    assert calls[0][1]["headers"]["Idempotency-Key"] == "base-submit-001"
    assert result.simulation_result["passed"] is True
    assert result.provider_reference == "safe-proposal-1"
