"""The scheduled proposal run and its Azure credential."""

import pytest

from app import agent, daily
from app.market_data import MarketDataUnavailable
from app.proposals import ProposalRejected
from app.schemas.proposals import ProposalRun


def test_daily_pulls_the_catalog_then_proposes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def refresh(client: object) -> None:
        calls.append("refresh")

    async def propose() -> ProposalRun:
        calls.append("propose")
        return ProposalRun()

    monkeypatch.setattr(daily, "refresh_catalog", refresh)
    monkeypatch.setattr(daily, "propose", propose)

    daily.main()

    assert calls == ["refresh", "propose"]


def test_daily_exits_when_the_pull_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def refresh(client: object) -> None:
        raise MarketDataUnavailable("Market data is unavailable.")

    def propose() -> object:
        raise AssertionError("propose should not run")

    monkeypatch.setattr(daily, "refresh_catalog", refresh)
    monkeypatch.setattr(daily, "propose", propose)

    with pytest.raises(SystemExit) as caught:
        daily.main()

    assert caught.value.code == 1


def test_daily_exits_when_the_proposal_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily, "refresh_catalog", lambda client: None)

    async def propose() -> object:
        raise ProposalRejected

    monkeypatch.setattr(daily, "propose", propose)

    with pytest.raises(SystemExit) as caught:
        daily.main()

    assert caught.value.code == 1


def test_daily_exits_cleanly_when_the_proposal_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(daily, "refresh_catalog", lambda client: None)

    async def propose() -> ProposalRun:
        return ProposalRun(skip="edge")

    monkeypatch.setattr(daily, "propose", propose)

    daily.main()

    assert "Confidence did not beat the market price." in capsys.readouterr().out


def test_client_id_selects_managed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    import azure.identity.aio as identity

    created: dict[str, str] = {}

    class FakeManagedIdentity:
        def __init__(self, client_id: str) -> None:
            created["client_id"] = client_id

    monkeypatch.setattr(identity, "ManagedIdentityCredential", FakeManagedIdentity)
    monkeypatch.setenv("AZURE_CLIENT_ID", "job-identity")

    credential = agent._azure_credential()

    assert isinstance(credential, FakeManagedIdentity)
    assert created["client_id"] == "job-identity"


def test_missing_client_id_selects_cli_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    import azure.identity.aio as identity

    class FakeCli:
        def __init__(self) -> None:
            pass

    monkeypatch.setattr(identity, "AzureCliCredential", FakeCli)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    assert isinstance(agent._azure_credential(), FakeCli)
