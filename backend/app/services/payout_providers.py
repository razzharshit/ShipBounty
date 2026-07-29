from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable
from urllib.parse import quote

import requests

from app.analysis.base import stable_hash
from app.core.config import settings


EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")


class ProviderTransferStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass(frozen=True)
class DestinationValidation:
    valid: bool
    normalized_destination: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PayoutSubmissionRequest:
    payout_id: int
    idempotency_key: str
    amount: Decimal
    currency: str
    chain: str
    destination: str
    treasury_address: str
    asset_contract_address: str | None
    asset_decimals: int
    simulation_required: bool
    provider_config: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PayoutSubmissionResult:
    provider_reference: str
    status: ProviderTransferStatus
    transaction_hash: str | None = None
    confirmations: int = 0
    explorer_url: str | None = None
    simulation_result: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class PayoutProviderStatus:
    provider_reference: str
    status: ProviderTransferStatus
    transaction_hash: str | None = None
    confirmations: int = 0
    raw_response: dict = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class TreasuryBalanceResult:
    observed_balance: Decimal
    raw_response: dict = field(default_factory=dict)


@runtime_checkable
class TreasuryBalanceProvider(Protocol):
    def get_balance(
        self,
        *,
        treasury_address: str,
        asset_contract_address: str | None,
        currency: str,
    ) -> TreasuryBalanceResult:
        ...


class PayoutProvider(ABC):
    key: str

    @abstractmethod
    def validate_destination(
        self, *, destination: str, chain: str, currency: str
    ) -> DestinationValidation:
        raise NotImplementedError

    @abstractmethod
    def submit(
        self, request: PayoutSubmissionRequest
    ) -> PayoutSubmissionResult:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, provider_reference: str) -> PayoutProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def find_by_idempotency_key(
        self, idempotency_key: str
    ) -> PayoutProviderStatus | None:
        """Recover a possibly-created transfer after an ambiguous submission."""
        raise NotImplementedError

    @abstractmethod
    def build_explorer_url(self, transaction_hash: str) -> str | None:
        raise NotImplementedError


class LedgerPayoutProvider(PayoutProvider):
    """Deterministic off-chain provider used before external custody is enabled."""

    key = "ledger"
    _transfers_by_idempotency_key: dict[str, PayoutProviderStatus] = {}

    def validate_destination(
        self, *, destination: str, chain: str, currency: str
    ) -> DestinationValidation:
        value = destination.strip()
        if not value:
            return DestinationValidation(False, reason="Destination is empty")
        return DestinationValidation(True, normalized_destination=value)

    def submit(
        self, request: PayoutSubmissionRequest
    ) -> PayoutSubmissionResult:
        reference = "ledger_" + stable_hash(
            {
                "payout_id": request.payout_id,
                "idempotency_key": request.idempotency_key,
                "amount": str(request.amount),
                "currency": request.currency,
                "destination": request.destination,
            }
        )[:32]
        transaction_hash = f"ledger:{reference}"
        status = PayoutProviderStatus(
            provider_reference=reference,
            status=ProviderTransferStatus.CONFIRMED,
            transaction_hash=transaction_hash,
            confirmations=1,
            raw_response={"mode": "off_chain", "settled": True},
        )
        self._transfers_by_idempotency_key[request.idempotency_key] = status
        return PayoutSubmissionResult(
            provider_reference=reference,
            status=ProviderTransferStatus.CONFIRMED,
            transaction_hash=transaction_hash,
            confirmations=1,
            simulation_result={"mode": "off_chain", "passed": True},
            raw_response={
                "mode": "off_chain",
                "message": "Settled by the deterministic off-chain ledger",
            },
        )

    def get_status(self, provider_reference: str) -> PayoutProviderStatus:
        for status in self._transfers_by_idempotency_key.values():
            if status.provider_reference == provider_reference:
                return status
        raise LookupError("Ledger transfer was not found")

    def find_by_idempotency_key(
        self, idempotency_key: str
    ) -> PayoutProviderStatus | None:
        return self._transfers_by_idempotency_key.get(idempotency_key)

    def build_explorer_url(self, transaction_hash: str) -> str | None:
        return None


class BaseSepoliaCustodyProvider(PayoutProvider):
    """
    Testnet-only adapter for an external Safe/custody service.

    The custody service owns transaction construction, simulation, multisig
    signatures, and broadcast. This application never receives a treasury key.
    """

    key = "base_sepolia_custody"
    chain = "base-sepolia"
    currency = "USDC"

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout_seconds: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _require_configured(self) -> None:
        if not self.base_url:
            raise RuntimeError("Base Sepolia custody provider URL is not configured")

    @staticmethod
    def _response_json(response: requests.Response) -> dict:
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("Custody provider returned a non-object response")
        return value

    def validate_destination(
        self, *, destination: str, chain: str, currency: str
    ) -> DestinationValidation:
        if chain.lower() != self.chain:
            return DestinationValidation(
                False, reason="Provider only supports Base Sepolia"
            )
        if currency.upper() != self.currency:
            return DestinationValidation(
                False, reason="Provider only supports USDC"
            )
        if not EVM_ADDRESS.fullmatch(destination):
            return DestinationValidation(
                False, reason="Destination must be a 20-byte EVM address"
            )
        return DestinationValidation(
            True, normalized_destination=destination.lower()
        )

    def submit(
        self, request: PayoutSubmissionRequest
    ) -> PayoutSubmissionResult:
        self._require_configured()
        validation = self.validate_destination(
            destination=request.destination,
            chain=request.chain,
            currency=request.currency,
        )
        if not validation.valid:
            raise ValueError(validation.reason or "Invalid payout destination")
        if (
            request.asset_contract_address or ""
        ).lower() != settings.BASE_SEPOLIA_USDC_CONTRACT.lower():
            raise ValueError("Treasury does not use the configured Base Sepolia USDC")
        payload = {
            "payout_id": request.payout_id,
            "chain_id": settings.BASE_SEPOLIA_CHAIN_ID,
            "chain": self.chain,
            "currency": self.currency,
            "asset_contract_address": settings.BASE_SEPOLIA_USDC_CONTRACT,
            "asset_decimals": request.asset_decimals,
            "amount": str(request.amount),
            "destination": validation.normalized_destination,
            "treasury_address": request.treasury_address,
            "custody_model": "multisig",
            "provider_config": request.provider_config,
        }
        simulation_result: dict = {}
        if request.simulation_required:
            simulation_response = requests.post(
                f"{self.base_url}/v1/payouts/simulate",
                json=payload,
                headers=self._headers(request.idempotency_key),
                timeout=self.timeout_seconds,
            )
            simulation_result = self._response_json(simulation_response)
            if not simulation_result.get("passed"):
                raise RuntimeError(
                    simulation_result.get("error")
                    or "Custody provider simulation failed"
                )
        response = requests.post(
            f"{self.base_url}/v1/payouts",
            json=payload,
            headers=self._headers(request.idempotency_key),
            timeout=self.timeout_seconds,
        )
        body = self._response_json(response)
        provider_reference = str(body.get("provider_reference") or "")
        if not provider_reference:
            raise RuntimeError("Custody provider omitted provider_reference")
        status = ProviderTransferStatus(body.get("status", "pending"))
        transaction_hash = body.get("transaction_hash")
        return PayoutSubmissionResult(
            provider_reference=provider_reference,
            status=status,
            transaction_hash=transaction_hash,
            confirmations=int(body.get("confirmations") or 0),
            explorer_url=(
                self.build_explorer_url(transaction_hash)
                if transaction_hash
                else None
            ),
            simulation_result=simulation_result,
            raw_response=body,
            error=body.get("error"),
        )

    def get_status(self, provider_reference: str) -> PayoutProviderStatus:
        self._require_configured()
        response = requests.get(
            f"{self.base_url}/v1/payouts/{provider_reference}",
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        body = self._response_json(response)
        return PayoutProviderStatus(
            provider_reference=provider_reference,
            status=ProviderTransferStatus(body.get("status", "pending")),
            transaction_hash=body.get("transaction_hash"),
            confirmations=int(body.get("confirmations") or 0),
            raw_response=body,
            error=body.get("error"),
        )

    def find_by_idempotency_key(
        self, idempotency_key: str
    ) -> PayoutProviderStatus | None:
        self._require_configured()
        response = requests.get(
            (
                f"{self.base_url}/v1/payouts/by-idempotency-key/"
                f"{quote(idempotency_key, safe='')}"
            ),
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            return None
        body = self._response_json(response)
        provider_reference = str(body.get("provider_reference") or "")
        if not provider_reference:
            raise RuntimeError("Custody provider omitted provider_reference")
        return PayoutProviderStatus(
            provider_reference=provider_reference,
            status=ProviderTransferStatus(body.get("status", "pending")),
            transaction_hash=body.get("transaction_hash"),
            confirmations=int(body.get("confirmations") or 0),
            raw_response=body,
            error=body.get("error"),
        )

    def build_explorer_url(self, transaction_hash: str) -> str | None:
        if not transaction_hash:
            return None
        return (
            f"{settings.BASE_SEPOLIA_EXPLORER_URL.rstrip('/')}"
            f"/tx/{transaction_hash}"
        )

    def get_balance(
        self,
        *,
        treasury_address: str,
        asset_contract_address: str | None,
        currency: str,
    ) -> TreasuryBalanceResult:
        self._require_configured()
        if currency.upper() != self.currency:
            raise ValueError("Provider only supports USDC balances")
        response = requests.get(
            f"{self.base_url}/v1/treasuries/{treasury_address}/balances",
            params={"asset_contract_address": asset_contract_address},
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        body = self._response_json(response)
        return TreasuryBalanceResult(
            observed_balance=Decimal(str(body["balance"])),
            raw_response=body,
        )


def configured_payout_providers() -> dict[str, PayoutProvider]:
    providers: dict[str, PayoutProvider] = {
        LedgerPayoutProvider.key: LedgerPayoutProvider(),
    }
    providers[BaseSepoliaCustodyProvider.key] = BaseSepoliaCustodyProvider(
        base_url=settings.PAYOUT_PROVIDER_BASE_URL,
        api_token=settings.PAYOUT_PROVIDER_API_TOKEN,
        timeout_seconds=settings.PAYOUT_PROVIDER_TIMEOUT_SECONDS,
    )
    return providers


def payout_provider(
    provider_key: str,
    providers: dict[str, PayoutProvider] | None = None,
) -> PayoutProvider:
    provider = (providers or configured_payout_providers()).get(provider_key)
    if provider is None:
        raise ValueError(f"Unknown payout provider: {provider_key}")
    return provider
