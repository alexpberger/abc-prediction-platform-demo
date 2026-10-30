"""Paper proposals over the in-memory event catalog."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market_data import (
    MarketDataUnavailable,
    MarketSettlement,
    clear_snapshot,
    current_snapshot,
    install_snapshot,
    query_catalog,
)
from app.proposals import (
    ProposalAlreadyStored,
    ProposalRejected,
    ProposalSearchRejected,
    ProposalSkipped,
    SearchLog,
    accept_proposal,
    get_event_contracts,
    list_events,
    load_proposals,
    omit_proposed_contracts,
    proposal_view,
    proposal_views,
    proposals_path,
    refresh_outcomes,
)
from app.schemas.markets import MarketQuote
from app.schemas.proposals import (
    ProposalDraft,
    ProposalTrace,
    TraceCall,
    TraceContract,
    TraceEvent,
    TraceOpening,
)

NOW = datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _empty_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARKET_CATALOG_PATH", str(tmp_path / "market-catalog.json"))
    monkeypatch.setenv("PROPOSALS_PATH", str(tmp_path / "proposals.json"))
    monkeypatch.setattr("app.proposals._search_clock", lambda: NOW)
    clear_snapshot()
    yield
    clear_snapshot()


def test_list_events_returns_events_not_contracts() -> None:
    install_snapshot(_two_events(), NOW)

    events = list_events()

    assert [event["event_ticker"] for event in events] == ["KXCPI", "KXJOBS"]
    jobs = next(event for event in events if event["event_ticker"] == "KXJOBS")
    assert jobs["title"] == "Jobs report"
    assert jobs["contract_count"] == 2
    assert jobs["yes_price_low"] == "0.2500"
    assert jobs["yes_price_high"] == "0.6100"
    assert "ticker" not in jobs
    assert "contracts" not in jobs


def test_list_events_reads_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    moment = datetime.now(timezone.utc)
    monkeypatch.setattr("app.proposals._search_clock", lambda: moment)
    markets = [
        _contract(
            f"KXECON-{index:02d}",
            f"KXECON-{index:02d}",
            "Economics",
            moment + timedelta(days=1),
            "Econ print",
            "above",
            "0.5000",
        )
        for index in range(51)
    ]
    install_snapshot(markets, moment)

    assert len(list_events()) == 51


def test_get_event_contracts_returns_only_the_requested_event() -> None:
    install_snapshot(_two_events(), NOW)

    jobs = get_event_contracts("KXJOBS")
    prices = get_event_contracts("KXCPI")

    assert [contract["ticker"] for contract in jobs] == ["KXJOBS-4", "KXJOBS-5"]
    assert jobs[0]["strike_label"] == "above 4"
    assert jobs[0]["settlement_time"] == _iso(NOW + timedelta(days=1))
    assert [contract["ticker"] for contract in prices] == ["KXCPI-1"]
    assert get_event_contracts("KXMISSING") == []


def test_list_events_omits_an_event_that_has_reached_settlement() -> None:
    install_snapshot(
        [
            *_two_events(),
            _contract("KXPAST-1", "KXPAST", "Economics", NOW, "Past print", "above", "0.5000"),
        ],
        NOW,
    )

    assert [event["event_ticker"] for event in list_events()] == ["KXCPI", "KXJOBS"]
    assert get_event_contracts("KXPAST") == []
    assert [contract["ticker"] for contract in get_event_contracts("KXJOBS")] == ["KXJOBS-4", "KXJOBS-5"]
    shown = query_catalog(category=None, resolves_within="3d", page=1, now=NOW)
    assert "KXPAST" in [event.event_ticker for event in shown.events]


def test_accept_proposal_appends_a_contract_from_the_chosen_event() -> None:
    install_snapshot(_two_events(), NOW)

    stored = accept_proposal(_draft("KXJOBS", "KXJOBS-5"), _trace_for("KXJOBS", "KXJOBS-5"))
    again = accept_proposal(
        _draft("KXCPI", "KXCPI-1", hypothesis="Prices cool."),
        _trace_for("KXCPI", "KXCPI-1"),
    )

    assert stored.catalog_pulled_at == NOW
    assert stored.proposed_at is not None
    assert stored.proposed_at.tzinfo is not None
    assert [item.ticker for item in load_proposals()] == ["KXJOBS-5", "KXCPI-1"]
    assert again.hypothesis == "Prices cool."
    assert proposals_path().exists()


def test_accept_proposal_rejects_a_contract_already_in_the_table() -> None:
    install_snapshot(_two_events(), NOW)
    accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))
    other = accept_proposal(_draft("KXJOBS", "KXJOBS-5"), _trace_for("KXJOBS", "KXJOBS-5"))

    with pytest.raises(ProposalAlreadyStored):
        accept_proposal(_draft("KXJOBS", "KXJOBS-4", side="no"), _trace_for("KXJOBS", "KXJOBS-4"))

    assert [item.ticker for item in load_proposals()] == ["KXJOBS-4", "KXJOBS-5"]
    assert other.ticker == "KXJOBS-5"


def test_proposed_contracts_are_omitted_from_the_next_search() -> None:
    install_snapshot(_two_events(), NOW)
    accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))

    shown = omit_proposed_contracts(get_event_contracts("KXJOBS"))

    assert [contract["ticker"] for contract in get_event_contracts("KXJOBS")] == ["KXJOBS-4", "KXJOBS-5"]
    assert [contract["ticker"] for contract in shown] == ["KXJOBS-5"]


def test_post_rejects_a_contract_already_in_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)
    accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))
    monkeypatch.setattr("app.agent.ask_model", _fake_draft("KXJOBS", "KXJOBS-4"))

    response = TestClient(create_app()).post("/api/proposals")

    assert response.status_code == 422
    assert response.json()["detail"] == "That contract already has a paper proposal."
    assert [item.ticker for item in load_proposals()] == ["KXJOBS-4"]


def test_accept_proposal_records_when_it_was_made() -> None:
    install_snapshot(_two_events(), NOW)
    before = datetime.now(timezone.utc)

    stored = accept_proposal(_draft("KXJOBS", "KXJOBS-5"), _trace_for("KXJOBS", "KXJOBS-5"))

    after = datetime.now(timezone.utc)
    assert stored.proposed_at is not None
    assert before <= stored.proposed_at <= after
    assert load_proposals()[0].proposed_at == stored.proposed_at


def test_load_proposals_allows_a_missing_proposed_at() -> None:
    proposals_path().parent.mkdir(parents=True, exist_ok=True)
    proposals_path().write_text(
        json.dumps(
            {
                "proposals": [
                    {
                        "event_ticker": "KXJOBS",
                        "ticker": "KXJOBS-4",
                        "side": "yes",
                        "hypothesis": "The strike is cheap.",
                        "confidence": 0.7,
                        "catalog_pulled_at": "2026-10-22T18:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_proposals()

    assert loaded[0].ticker == "KXJOBS-4"
    assert loaded[0].proposed_at is None
    assert loaded[0].yes_price is None
    assert loaded[0].entry_price is None
    assert loaded[0].quantity is None
    assert loaded[0].kelly_fraction is None
    assert loaded[0].bankroll is None
    assert loaded[0].trace is None
    assert proposal_view(loaded[0], NOW).trace is None
    view = proposal_view(loaded[0], NOW)
    assert view.cost is None
    assert view.payout is None
    assert view.realized_pnl is None


def test_accept_proposal_rejects_a_ticker_from_another_event() -> None:
    install_snapshot(_two_events(), NOW)
    trace = _trace_for("KXCPI", "KXCPI-1")
    foreign = trace.opened[0].contracts[0].model_copy(update={"ticker": "KXJOBS-4"})
    opening = trace.opened[0].model_copy(update={"contracts": [*trace.opened[0].contracts, foreign]})
    trace = trace.model_copy(update={"opened": [opening]})

    with pytest.raises(ProposalRejected):
        accept_proposal(_draft("KXCPI", "KXJOBS-4"), trace)

    assert load_proposals() == []
    assert not proposals_path().exists()


def test_accept_proposal_stores_the_search_trace() -> None:
    install_snapshot(_two_events(), NOW)

    stored = accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))

    assert stored.trace is not None
    assert stored.trace.event_reason == "The release is soon."
    assert stored.trace.searched_at == NOW
    assert stored.trace.catalog_pulled_at == NOW
    assert any(event.event_ticker == "KXJOBS" for event in stored.trace.events)
    assert stored.trace.calls[0].name == "list_events"
    assert stored.trace.opened[0].event_ticker == "KXJOBS"
    assert any(contract.ticker == "KXJOBS-4" for contract in stored.trace.opened[0].contracts)
    loaded = load_proposals()
    assert loaded[0].trace is not None
    assert loaded[0].trace.event_reason == "The release is soon."
    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    assert "outcome" not in raw["proposals"][0]
    assert raw["proposals"][0]["trace"]["event_reason"] == "The release is soon."


def test_accept_proposal_rejects_a_search_that_never_listed_events() -> None:
    install_snapshot(_two_events(), NOW)
    trace = _trace_for("KXJOBS", "KXJOBS-4")
    trace = trace.model_copy(update={"calls": [call for call in trace.calls if call.name != "list_events"]})

    with pytest.raises(ProposalSearchRejected):
        accept_proposal(_draft("KXJOBS", "KXJOBS-4"), trace)

    assert load_proposals() == []
    assert not proposals_path().exists()


def test_accept_proposal_rejects_a_search_that_never_opened_the_event() -> None:
    install_snapshot(_two_events(), NOW)

    with pytest.raises(ProposalSearchRejected):
        accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXCPI", "KXCPI-1"))

    assert load_proposals() == []
    assert not proposals_path().exists()


def test_accept_proposal_rejects_a_contract_that_has_reached_settlement() -> None:
    install_snapshot(_two_events(), NOW)
    trace = _trace_for("KXJOBS", "KXJOBS-4")
    opening = trace.opened[0]
    contracts = [
        contract.model_copy(update={"settlement_time": _iso(NOW)})
        if contract.ticker == "KXJOBS-4"
        else contract
        for contract in opening.contracts
    ]
    trace = trace.model_copy(update={"opened": [opening.model_copy(update={"contracts": contracts})]})

    with pytest.raises(ProposalSearchRejected):
        accept_proposal(_draft("KXJOBS", "KXJOBS-4"), trace)

    assert load_proposals() == []
    assert not proposals_path().exists()


def test_search_log_keeps_the_last_event_list() -> None:
    install_snapshot(_two_events(), NOW)
    log = SearchLog()
    log.record_events(list_events())
    log.record_events(
        [
            {
                "event_ticker": "KXONLY",
                "title": "Only print",
                "category": "Economics",
                "contract_count": 1,
                "yes_price_low": "0.4000",
                "yes_price_high": "0.4000",
                "settlement_time": _iso(NOW + timedelta(days=1)),
            }
        ]
    )
    log.record_contracts("KXJOBS", get_event_contracts("KXJOBS"))

    trace = log.finish("The jobs print is the one to read.")

    assert [event.event_ticker for event in trace.events] == ["KXONLY"]
    assert [call.name for call in trace.calls] == ["list_events", "list_events", "get_event_contracts"]
    assert trace.calls[2].event_ticker == "KXJOBS"
    assert trace.catalog_pulled_at == NOW
    assert trace.searched_at == NOW
    assert [contract.ticker for contract in trace.opened[0].contracts] == ["KXJOBS-4", "KXJOBS-5"]


def test_missing_catalog_raises() -> None:
    with pytest.raises(MarketDataUnavailable):
        list_events()


def test_post_stores_a_matching_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)
    monkeypatch.setattr("app.agent.ask_model", _fake_draft("KXJOBS", "KXJOBS-4"))
    monkeypatch.setattr("app.proposals.fetch_market_settlement", _unavailable)
    client = TestClient(create_app())

    response = client.post("/api/proposals")

    assert response.status_code == 200
    body = response.json()["proposal"]
    assert body["event_ticker"] == "KXJOBS"
    assert body["ticker"] == "KXJOBS-4"
    assert body["side"] == "yes"
    assert body["confidence"] == 0.7
    assert body["kelly_fraction"] == "0.2308"
    assert body["bankroll"] == "10000.0000"
    assert body["quantity"] == 3783
    assert isinstance(body["proposed_at"], str) and body["proposed_at"]
    listed = client.get("/api/proposals")
    assert listed.status_code == 200
    assert listed.json()["proposals"][0]["ticker"] == "KXJOBS-4"


def test_post_skips_when_confidence_does_not_beat_the_price(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)

    async def ask() -> tuple[ProposalDraft, ProposalTrace]:
        return _draft("KXJOBS", "KXJOBS-4", confidence=0.5), _trace_for("KXJOBS", "KXJOBS-4")

    monkeypatch.setattr("app.agent.ask_model", ask)
    monkeypatch.setattr("app.proposals.fetch_market_settlement", _unavailable)

    response = TestClient(create_app()).post("/api/proposals")

    assert response.status_code == 200
    body = response.json()
    assert body["proposal"] is None
    assert body["skip"] == "edge"
    assert load_proposals() == []


def test_post_returns_the_search_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)
    monkeypatch.setattr("app.agent.ask_model", _fake_draft("KXJOBS", "KXJOBS-4"))
    monkeypatch.setattr("app.proposals.fetch_market_settlement", _unavailable)
    client = TestClient(create_app())

    response = client.post("/api/proposals")

    assert response.status_code == 200
    trace = response.json()["proposal"]["trace"]
    assert trace["event_reason"] == "The release is soon."
    assert any(event["event_ticker"] == "KXJOBS" for event in trace["events"])
    assert trace["calls"][0]["name"] == "list_events"
    listed = client.get("/api/proposals")
    assert listed.status_code == 200
    assert listed.json()["proposals"][0]["trace"]["event_reason"] == "The release is soon."


def test_post_rejects_a_run_with_no_recorded_search(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)

    async def ask() -> tuple[ProposalDraft, ProposalTrace]:
        trace = _trace_for("KXJOBS", "KXJOBS-4")
        return _draft("KXJOBS", "KXJOBS-4"), trace.model_copy(update={"calls": [], "events": [], "opened": []})

    monkeypatch.setattr("app.agent.ask_model", ask)
    client = TestClient(create_app())

    response = client.post("/api/proposals")

    assert response.status_code == 422
    assert response.json()["detail"] == "The proposal has no recorded search of a future contract."
    assert load_proposals() == []


def test_post_rejects_a_ticker_from_another_event(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)
    monkeypatch.setattr("app.agent.ask_model", _fake_draft("KXCPI", "KXJOBS-4"))

    response = TestClient(create_app()).post("/api/proposals")

    assert response.status_code == 422
    assert load_proposals() == []


def test_post_reports_a_missing_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agent.ask_model", _fake_draft("KXJOBS", "KXJOBS-4"))

    response = TestClient(create_app()).post("/api/proposals")

    assert response.status_code == 502


def test_post_reports_missing_azure_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    install_snapshot(_two_events(), NOW)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_MODEL", raising=False)

    response = TestClient(create_app()).post("/api/proposals")

    assert response.status_code == 503
    assert load_proposals() == []


def test_get_reports_an_unreadable_proposal_file() -> None:
    proposals_path().write_text("{", encoding="utf-8")

    response = TestClient(create_app()).get("/api/proposals")

    assert response.status_code == 500


def test_proposals_path_follows_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom.json"
    monkeypatch.setenv("PROPOSALS_PATH", str(custom))

    assert proposals_path() == custom


def test_default_proposals_path_is_backend_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPOSALS_PATH", raising=False)

    assert proposals_path().parts[-3:] == ("backend", ".data", "proposals.json")


def test_accept_proposal_records_the_event_settlement_time() -> None:
    install_snapshot(_two_events(), NOW)

    stored = accept_proposal(_draft("KXJOBS", "KXJOBS-5"), _trace_for("KXJOBS", "KXJOBS-5"))

    assert stored.settlement_time == NOW + timedelta(days=1)
    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    assert "outcome" not in raw["proposals"][0]
    assert "result" not in raw["proposals"][0]


def test_accept_proposal_stores_the_yes_price_for_one_contract() -> None:
    install_snapshot(_two_events(), NOW)

    stored = accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))

    assert stored.yes_price == "0.6100"
    assert stored.entry_price == "0.6100"
    assert stored.kelly_fraction == "0.2308"
    assert stored.bankroll == "10000.0000"
    assert stored.quantity == 3783
    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    assert raw["proposals"][0]["yes_price"] == "0.6100"
    assert raw["proposals"][0]["entry_price"] == "0.6100"
    assert raw["proposals"][0]["kelly_fraction"] == "0.2308"
    assert raw["proposals"][0]["bankroll"] == "10000.0000"
    assert raw["proposals"][0]["quantity"] == 3783
    for key in ("outcome", "cost", "payout", "realized_pnl"):
        assert key not in raw["proposals"][0]


def test_accept_proposal_sizes_a_no_bet_from_one_minus_yes() -> None:
    install_snapshot(_two_events(), NOW)

    stored = accept_proposal(
        _draft("KXJOBS", "KXJOBS-5", side="no", confidence=0.8),
        _trace_for("KXJOBS", "KXJOBS-5"),
    )

    assert stored.yes_price == "0.2500"
    assert stored.entry_price == "0.7500"
    assert stored.kelly_fraction == "0.2000"
    assert stored.quantity == 2666


def test_accept_proposal_skips_when_confidence_does_not_beat_the_price() -> None:
    install_snapshot(_two_events(), NOW)

    with pytest.raises(ProposalSkipped) as below:
        accept_proposal(_draft("KXJOBS", "KXJOBS-4", confidence=0.5), _trace_for("KXJOBS", "KXJOBS-4"))
    assert below.value.reason == "edge"

    with pytest.raises(ProposalSkipped) as equal:
        accept_proposal(_draft("KXJOBS", "KXJOBS-4", confidence=0.61), _trace_for("KXJOBS", "KXJOBS-4"))
    assert equal.value.reason == "edge"
    assert load_proposals() == []


def test_accept_proposal_skips_when_the_price_cannot_be_beaten() -> None:
    settles = NOW + timedelta(days=1)
    for price in (None, "1.2000", "0.0000", "1.0000"):
        install_snapshot(
            [_contract("KXJOBS-4", "KXJOBS", "Economics", settles, "Jobs report", "above 4", price)],
            NOW,
        )
        with pytest.raises(ProposalSkipped) as caught:
            accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))
        assert caught.value.reason == "edge"
    assert load_proposals() == []


def test_accept_proposal_skips_when_the_kelly_stake_is_below_one_contract() -> None:
    install_snapshot(_two_events(), NOW)

    with pytest.raises(ProposalSkipped) as caught:
        accept_proposal(
            _draft("KXJOBS", "KXJOBS-4", confidence=0.61001),
            _trace_for("KXJOBS", "KXJOBS-4"),
        )

    assert caught.value.reason == "size"
    assert load_proposals() == []


def test_accept_proposal_reserves_the_cost_of_an_open_bet() -> None:
    install_snapshot(_two_events(), NOW)

    first = accept_proposal(_draft("KXJOBS", "KXJOBS-4"), _trace_for("KXJOBS", "KXJOBS-4"))
    second = accept_proposal(_draft("KXJOBS", "KXJOBS-5"), _trace_for("KXJOBS", "KXJOBS-5"))

    assert first.quantity == 3783
    assert first.bankroll == "10000.0000"
    assert second.kelly_fraction == "0.6000"
    assert second.bankroll == "7692.3700"
    assert second.quantity == 18461


def test_accept_proposal_sizes_from_cash_returned_by_a_settled_win() -> None:
    install_snapshot(_two_events(), NOW)
    _write_rows([_priced(ticker="KXOLD-1", event_ticker="KXOLD", quantity=10, result="yes")])

    assert proposal_views(load_proposals(), NOW).bankroll == "10003.9000"
    stored = accept_proposal(_draft("KXJOBS", "KXJOBS-5"), _trace_for("KXJOBS", "KXJOBS-5"))

    assert stored.quantity == 24009
    assert stored.bankroll == "10003.9000"
    assert proposal_views(load_proposals(), NOW).bankroll == "4001.6500"


def test_realized_pnl_follows_the_one_contract_payoff() -> None:
    _write_rows(
        [
            _priced(result="yes"),
            _priced(ticker="KXJOBS-5", result="no"),
            _priced(ticker="KXCPI-1", event_ticker="KXCPI", side="no", yes_price="0.2500", entry_price="0.7500", result="no"),
        ]
    )

    views = [proposal_view(item, NOW) for item in load_proposals()]

    assert views[0].cost == "0.6100"
    assert views[0].payout == "1.0000"
    assert views[0].realized_pnl == "0.3900"
    assert views[1].payout == "0.0000"
    assert views[1].realized_pnl == "-0.6100"
    assert views[2].realized_pnl == "0.2500"


def test_open_and_pending_rows_have_cost_and_no_realized_pnl() -> None:
    later = NOW + timedelta(days=1)
    past = NOW - timedelta(hours=1)
    _write_rows(
        [
            _priced(settlement_time=_iso(later)),
            _priced(ticker="KXCPI-1", event_ticker="KXCPI", yes_price="0.4000", entry_price="0.4000", settlement_time=_iso(past)),
        ]
    )

    views = [proposal_view(item, NOW) for item in load_proposals()]

    assert views[0].outcome == "open"
    assert views[0].cost == "0.6100"
    assert views[0].payout is None
    assert views[0].realized_pnl is None
    assert views[1].outcome == "pending"
    assert views[1].cost == "0.4000"
    assert views[1].payout is None
    assert views[1].realized_pnl is None


def test_realized_total_sums_only_settled_priced_rows() -> None:
    later = NOW + timedelta(days=1)
    _write_rows(
        [
            _priced(result="yes"),
            _priced(ticker="KXJOBS-5", result="no"),
            _priced(ticker="KXCPI-1", event_ticker="KXCPI", settlement_time=_iso(later)),
            _row(ticker="KXOLD-1", event_ticker="KXOLD", result="yes"),
        ]
    )

    listed = proposal_views(load_proposals(), NOW)

    assert listed.realized_total == "-0.2200"
    assert [item.realized_pnl for item in listed.proposals] == ["0.3900", "-0.6100", None, None]


def test_realized_total_of_zero_is_a_decimal_string() -> None:
    _write_rows(
        [
            _priced(yes_price="0.5000", entry_price="0.5000", result="yes"),
            _priced(ticker="KXJOBS-5", yes_price="0.5000", entry_price="0.5000", result="no"),
        ]
    )

    assert proposal_views(load_proposals(), NOW).realized_total == "0.0000"


def test_refresh_keeps_the_paper_price_and_omits_cash_fields() -> None:
    _write_rows([_priced()])

    refresh_outcomes(now=NOW, lookup=lambda ticker: _settled(ticker, "yes"))

    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    stored = raw["proposals"][0]
    assert stored["yes_price"] == "0.6100"
    assert stored["entry_price"] == "0.6100"
    assert stored["quantity"] == 1
    assert stored["result"] == "yes"
    for key in ("outcome", "cost", "payout", "realized_pnl"):
        assert key not in stored


def test_get_proposals_returns_the_realized_total() -> None:
    _write_rows([_priced(result="yes")])

    response = TestClient(create_app()).get("/api/proposals")

    assert response.status_code == 200
    body = response.json()
    assert body["realized_total"] == "0.3900"
    assert body["bankroll"] == "10000.3900"
    assert body["proposals"][0]["realized_pnl"] == "0.3900"
    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    for key in ("outcome", "cost", "payout", "realized_pnl"):
        assert key not in raw["proposals"][0]


def test_refresh_records_a_matching_result_as_won() -> None:
    _write_rows([_row()])

    refreshed = refresh_outcomes(now=NOW, lookup=lambda ticker: _settled(ticker, "yes"))

    assert refreshed[0].result == "yes"
    assert _outcome(refreshed[0]) == "won"
    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    assert raw["proposals"][0]["result"] == "yes"
    assert "outcome" not in raw["proposals"][0]


def test_refresh_records_the_other_result_as_lost() -> None:
    _write_rows([_row()])

    refreshed = refresh_outcomes(now=NOW, lookup=lambda ticker: _settled(ticker, "no"))

    assert refreshed[0].result == "no"
    assert _outcome(refreshed[0]) == "lost"


def test_refresh_does_not_call_kalshi_before_settlement() -> None:
    later = NOW + timedelta(days=1)
    _write_rows([_row(settlement_time=_iso(later))])

    refreshed = refresh_outcomes(now=NOW, lookup=_unexpected_lookup)

    assert refreshed[0].result is None
    assert _outcome(refreshed[0]) == "open"


def test_refresh_keeps_an_empty_result_pending() -> None:
    past = NOW - timedelta(hours=1)
    _write_rows([_row()])

    refreshed = refresh_outcomes(
        now=NOW,
        lookup=lambda _ticker: MarketSettlement(result=None, settlement_time=past),
    )

    assert refreshed[0].result is None
    assert refreshed[0].settlement_time == past
    assert _outcome(refreshed[0]) == "pending"


def test_refresh_remembers_a_future_settlement_time() -> None:
    later = NOW + timedelta(days=1)
    calls: list[str] = []

    def lookup(ticker: str) -> MarketSettlement:
        calls.append(ticker)
        return MarketSettlement(result=None, settlement_time=later)

    _write_rows([_row()])
    refresh_outcomes(now=NOW, lookup=lookup)
    refresh_outcomes(now=NOW, lookup=lookup)

    assert calls == ["KXJOBS-4"]
    assert load_proposals()[0].settlement_time == later


def test_refresh_returns_the_list_when_one_lookup_fails() -> None:
    _write_rows([_row(), _row(ticker="KXCPI-1", event_ticker="KXCPI")])

    def lookup(ticker: str) -> MarketSettlement:
        if ticker == "KXJOBS-4":
            raise MarketDataUnavailable
        return _settled(ticker, "no")

    refreshed = refresh_outcomes(now=NOW, lookup=lookup)

    assert [item.ticker for item in refreshed] == ["KXJOBS-4", "KXCPI-1"]
    assert refreshed[0].result is None
    assert _outcome(refreshed[0]) == "pending"
    assert refreshed[1].result == "no"
    assert _outcome(refreshed[1]) == "lost"


def test_get_proposals_reports_whether_the_side_won() -> None:
    _write_rows([_row(result="yes")])
    client = TestClient(create_app())

    response = client.get("/api/proposals")

    assert response.status_code == 200
    assert response.json()["proposals"][0]["outcome"] == "won"
    raw = json.loads(proposals_path().read_text(encoding="utf-8"))
    assert "outcome" not in raw["proposals"][0]


def test_fetch_market_settlement_reads_a_published_result() -> None:
    import httpx

    from app.market_data import fetch_market_settlement

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/markets/KXEURUSD-26OCT2610-B1.119") or (
            "KXEURUSD-26OCT2610-B1.119" in request.url.path
        )
        return httpx.Response(
            200,
            json={
                "market": {
                    "result": "yes",
                    "expected_expiration_time": "2026-10-26T14:00:00Z",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = fetch_market_settlement(client, "KXEURUSD-26OCT2610-B1.119")

    assert found.result == "yes"
    assert found.settlement_time == datetime(2026, 10, 26, 14, tzinfo=timezone.utc)


def test_fetch_market_settlement_treats_an_empty_result_as_unsettled() -> None:
    import httpx

    from app.market_data import fetch_market_settlement

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"market": {"result": "", "close_time": "2026-10-27T14:00:00Z"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = fetch_market_settlement(client, "KXJOBS-4")

    assert found.result is None
    assert found.settlement_time == datetime(2026, 10, 27, 14, tzinfo=timezone.utc)


def _unavailable(_client: object, _ticker: str) -> MarketSettlement:
    raise MarketDataUnavailable


def _unexpected_lookup(_ticker: str) -> MarketSettlement:
    raise AssertionError("Kalshi was called")


def _settled(ticker: str, result: str) -> MarketSettlement:
    assert ticker
    return MarketSettlement(result=result, settlement_time=NOW - timedelta(hours=1))


def _outcome(proposal: object) -> str:
    from app.proposals import proposal_view
    from app.schemas.proposals import Proposal

    assert isinstance(proposal, Proposal)
    return proposal_view(proposal, NOW).outcome


def _write_rows(rows: list[dict[str, object]]) -> None:
    proposals_path().parent.mkdir(parents=True, exist_ok=True)
    proposals_path().write_text(json.dumps({"proposals": rows}), encoding="utf-8")


def _row(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "event_ticker": "KXJOBS",
        "ticker": "KXJOBS-4",
        "side": "yes",
        "hypothesis": "The strike is cheap.",
        "confidence": 0.7,
        "catalog_pulled_at": "2026-10-22T18:00:00Z",
        "proposed_at": "2026-10-22T18:05:00Z",
    }
    body.update(overrides)
    return body


def _two_events() -> list[MarketQuote]:
    settles = NOW + timedelta(days=1)
    return [
        _contract("KXJOBS-4", "KXJOBS", "Economics", settles, "Jobs report", "above 4", "0.6100"),
        _contract("KXJOBS-5", "KXJOBS", "Economics", settles, "Jobs report", "above 5", "0.2500"),
        _contract("KXCPI-1", "KXCPI", "Financials", settles, "CPI print", "above 3", "0.4000"),
    ]


def _priced(**overrides: object) -> dict[str, object]:
    body = _row(
        yes_price="0.6100",
        entry_price="0.6100",
        quantity=1,
    )
    body.update(overrides)
    return body


def _contract(
    ticker: str,
    event_ticker: str,
    category: str,
    resolves_at: datetime,
    title: str,
    strike: str,
    yes_price: str | None,
) -> MarketQuote:
    return MarketQuote(
        ticker=ticker,
        event_ticker=event_ticker,
        event_title=title,
        strike_label=strike,
        question=f"{title} USD",
        category=category,  # type: ignore[arg-type]
        yes_price=yes_price,
        volume="1.00",
        open_interest="1.00",
        market_count=1,
        mutually_exclusive=True,
        status="active",
        settlement_time=_iso(resolves_at),
    )


def _draft(
    event_ticker: str,
    ticker: str,
    hypothesis: str = "The strike is cheap.",
    side: str = "yes",
    confidence: float = 0.7,
) -> ProposalDraft:
    return ProposalDraft(
        event_ticker=event_ticker,
        ticker=ticker,
        side=side,  # type: ignore[arg-type]
        hypothesis=hypothesis,
        confidence=confidence,
    )


def _fake_draft(event_ticker: str, ticker: str):
    async def ask() -> tuple[ProposalDraft, ProposalTrace]:
        return _draft(event_ticker, ticker), _trace_for(event_ticker, ticker)

    return ask


def _trace_for(event_ticker: str, ticker: str) -> ProposalTrace:
    catalog = current_snapshot()
    if catalog is None:
        return _trace_without_catalog(event_ticker, ticker)
    events = list_events()
    contracts = get_event_contracts(event_ticker)
    return ProposalTrace(
        searched_at=NOW,
        catalog_pulled_at=catalog.pulled_at,
        events=[TraceEvent.model_validate(event) for event in events],
        calls=[
            TraceCall(name="list_events"),
            TraceCall(name="get_event_contracts", event_ticker=event_ticker),
        ],
        opened=[
            TraceOpening(
                event_ticker=event_ticker,
                contracts=[TraceContract.model_validate(contract) for contract in contracts],
            )
        ],
        event_reason="The release is soon.",
    )


def _trace_without_catalog(event_ticker: str, ticker: str) -> ProposalTrace:
    """A complete search record used when the catalog is missing.

    Acceptance then fails on the catalog read, which is the 502 the API reports.
    """
    settles = _iso(NOW + timedelta(days=1))
    return ProposalTrace(
        searched_at=NOW,
        catalog_pulled_at=NOW,
        events=[
            TraceEvent(
                event_ticker=event_ticker,
                title="Missing catalog",
                category="Economics",
                contract_count=1,
                settlement_time=settles,
            )
        ],
        calls=[
            TraceCall(name="list_events"),
            TraceCall(name="get_event_contracts", event_ticker=event_ticker),
        ],
        opened=[
            TraceOpening(
                event_ticker=event_ticker,
                contracts=[
                    TraceContract(
                        ticker=ticker,
                        strike_label="above",
                        yes_price="0.5000",
                        settlement_time=settles,
                    )
                ],
            )
        ],
        event_reason="The release is soon.",
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
