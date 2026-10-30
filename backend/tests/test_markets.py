"""Catalog rules for the stored Kalshi snapshot."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market_data import (
    MarketDataUnavailable,
    catalog_is_current,
    catalog_path,
    clear_snapshot,
    current_snapshot,
    install_snapshot,
    last_refresh_slot,
    load_catalog,
    refresh_catalog,
    seconds_until_next_attempt,
    seconds_until_next_refresh,
    start_catalog_refresh,
)
from app.schemas.markets import MarketQuote

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
EASTERN = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _empty_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARKET_CATALOG_PATH", str(tmp_path / "market-catalog.json"))
    clear_snapshot()
    yield
    clear_snapshot()


def test_snapshot_keeps_short_horizon_economics_and_financials(monkeypatch) -> None:
    monkeypatch.delenv("KALSHI_API_BASE_URL", raising=False)
    seen: list[httpx.Request] = []
    economics_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal economics_attempts
        seen.append(request)
        path = request.url.path
        if (
            path.endswith("/series")
            and request.url.params.get("category") == "Economics"
            and request.url.params.get("cursor") is None
        ):
            economics_attempts += 1
            if economics_attempts == 1:
                return httpx.Response(429, json={"error": "too many requests"})
        if path.endswith("/series"):
            return _series_page(request)
        if path.endswith("/events"):
            return _events_page(request)
        if path.endswith("/markets"):
            return _markets_page(request)
        return httpx.Response(404, json={"error": "unexpected-path"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        refresh_catalog(client, now=NOW)

    response = TestClient(create_app()).get("/api/markets")

    assert response.status_code == 200
    body = response.json()
    assert _tickers(body) == [
        "KXECON2-SOON",
        "KXBARE-KEEP",
        "KXECON-KEEP",
        "KXFIN-KEEP",
    ]
    soon, bare, keep, fin = body["events"]
    assert soon["title"] == "Jobs above consensus USD"
    assert soon["contracts"][0]["yes_price"] == "0.4200"
    assert soon["contracts"][0]["strike_label"] == "Not appended"
    assert soon["contract_count"] == 1
    assert soon["category"] == "Economics"
    assert bare["title"] == "Bare event USD"
    assert bare["category"] == "Economics"
    assert bare["mutually_exclusive"] is True
    assert keep["title"] == "Monthly payrolls USD"
    assert keep["contracts"][0]["strike_label"] == "Above consensus"
    assert keep["contracts"][0]["yes_price"] == "0.5700"
    assert keep["contract_count"] == 1
    assert keep["settlement_source"] == "BLS, BEA"
    assert keep["rules_url"] == "https://example.com/econ-terms"
    assert keep["rules_primary"] == "The payrolls print is the official BLS release."
    assert keep["mutually_exclusive"] is False
    assert keep["collateral_return_type"] == "mecnet"
    assert keep["contracts"][0]["strike_type"] == "greater"
    assert keep["contracts"][0]["floor_strike"] == "51075"
    assert keep["contracts"][0]["cap_strike"] is None
    assert keep["contracts"][0]["open_interest"] == "12.00"
    assert keep["settlement_time"] == _iso(NOW + timedelta(days=3))
    assert fin["category"] == "Financials"
    assert fin["contracts"][0]["yes_price"] == "0.3300"
    assert fin["rules_url"] == "https://example.com/fin-terms"
    assert fin["settlement_time"] == _iso(NOW + timedelta(days=3))
    assert body["total"] == 4
    assert body["event_count"] == 4
    assert body["match_count"] == 4
    assert body["match_event_count"] == 4
    assert body["page"] == 1
    assert body["page_count"] == 1
    assert "KXSPORT-SKIP" not in response.text
    assert "KXNOPUSD-SKIP" not in response.text
    assert "KXEURUSD15M-SKIP" not in response.text
    assert "kalshi-secret" not in response.text

    series_calls = [request for request in seen if request.url.path.endswith("/series")]
    assert [(call.url.params["category"], call.url.params.get("cursor")) for call in series_calls] == [
        ("Economics", None),
        ("Economics", None),
        ("Economics", "econ-2"),
        ("Financials", None),
    ]
    event_calls = [request for request in seen if request.url.path.endswith("/events")]
    assert len(event_calls) == 1
    assert event_calls[0].url.params["status"] == "open"
    market_calls = [request for request in seen if request.url.path.endswith("/markets")]
    assert len(market_calls) == 1
    assert market_calls[0].url.params["status"] == "open"
    assert market_calls[0].url.params["mve_filter"] == "exclude"
    assert "series_ticker" not in market_calls[0].url.params
    assert all(str(call.url.copy_with(query=None)).startswith(KALSHI) for call in seen)


def test_failed_refresh_keeps_the_previous_snapshot() -> None:
    previous = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
    install_snapshot([_quote("KXECON-OLD", "Economics", previous)], previous)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "kalshi-secret-detail"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        refresh_catalog(client, now=NOW)

    response = TestClient(create_app()).get("/api/markets")

    assert response.status_code == 200
    body = response.json()
    assert _tickers(body) == ["KXECON-OLD"]
    assert datetime.fromisoformat(body["pulled_at"]) == previous
    assert "kalshi-secret-detail" not in response.text


def test_first_pull_failure_is_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "kalshi-secret-detail"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MarketDataUnavailable):
            refresh_catalog(client, now=NOW)

    response = TestClient(create_app()).get("/api/markets")

    assert response.status_code == 502
    assert response.json() == {"detail": "Market data is unavailable."}
    assert "kalshi-secret-detail" not in response.text
    assert not catalog_path().exists()


def test_install_snapshot_does_not_write_the_catalog_file() -> None:
    install_snapshot([_quote("KXECON-OLD", "Economics", NOW)], NOW)

    assert current_snapshot() is not None
    assert not catalog_path().exists()


def test_successful_pull_replaces_the_catalog_file() -> None:
    with httpx.Client(transport=httpx.MockTransport(_one_contract_handler)) as client:
        refresh_catalog(client, now=NOW)

    stored = json.loads(catalog_path().read_text(encoding="utf-8"))
    assert stored["pulled_at"] == "2026-10-15T12:00:00Z"
    assert [market["ticker"] for market in stored["markets"]] == ["KXECON-FILE"]
    assert stored["markets"][0]["question"] == "Payrolls USD"
    assert stored["markets"][0]["event_title"] == "Payrolls USD"
    assert stored["markets"][0]["strike_label"] == "yes side"

    clear_snapshot()
    assert load_catalog() is True
    response = TestClient(create_app()).get("/api/markets")

    assert response.status_code == 200
    assert _tickers(response.json()) == ["KXECON-FILE"]
    assert response.json()["pulled_at"] == "2026-10-15T12:00:00Z"


def test_failed_pull_leaves_the_catalog_file() -> None:
    with httpx.Client(transport=httpx.MockTransport(_one_contract_handler)) as client:
        refresh_catalog(client, now=NOW)
    original = catalog_path().read_text(encoding="utf-8")
    clear_snapshot()
    assert load_catalog() is True

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "kalshi-secret-detail"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        refresh_catalog(client, now=NOW)

    assert catalog_path().read_text(encoding="utf-8") == original
    assert [market.ticker for market in current_snapshot().markets] == ["KXECON-FILE"]  # type: ignore[union-attr]


def test_unreadable_catalog_file_is_ignored() -> None:
    catalog_path().write_text("{", encoding="utf-8")

    assert load_catalog() is False
    response = TestClient(create_app()).get("/api/markets")

    assert response.status_code == 502


def test_invalid_catalog_file_does_not_replace_memory() -> None:
    previous = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
    install_snapshot([_quote("KXECON-OLD", "Economics", previous)], previous)
    catalog_path().parent.mkdir(parents=True, exist_ok=True)
    catalog_path().write_text(
        json.dumps({"pulled_at": "2026-10-14T06:00:00Z", "markets": [{}]}),
        encoding="utf-8",
    )

    assert load_catalog() is False
    assert [market.ticker for market in current_snapshot().markets] == ["KXECON-OLD"]  # type: ignore[union-attr]


def test_startup_serves_the_stored_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    quote = _quote("KXECON-OLD", "Economics", NOW + timedelta(days=1))
    catalog_path().parent.mkdir(parents=True, exist_ok=True)
    catalog_path().write_text(
        json.dumps(
            {
                "pulled_at": "2026-10-14T06:00:00Z",
                "markets": [quote.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    clear_snapshot()

    class IdleThread:
        def __init__(self, *, target: object, name: str, daemon: bool) -> None:
            del target, name, daemon

        def start(self) -> None:
            return None

    monkeypatch.setattr("app.market_data.threading.Thread", IdleThread)
    from app import market_data

    market_data._refresh_started = False
    market_data._initial_refresh_done.clear()
    try:
        start_catalog_refresh()
        response = TestClient(create_app()).get("/api/markets")
    finally:
        market_data._refresh_started = True
        market_data._initial_refresh_done.set()

    assert response.status_code == 200
    assert _tickers(response.json()) == ["KXECON-OLD"]


def test_catalog_path_follows_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom.json"
    monkeypatch.setenv("MARKET_CATALOG_PATH", str(custom))

    assert catalog_path() == custom


def test_default_catalog_path_is_backend_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKET_CATALOG_PATH", raising=False)

    assert catalog_path().parts[-3:] == ("backend", ".data", "market-catalog.json")


def test_pages_and_filters_the_snapshot() -> None:
    moment = datetime.now(timezone.utc)
    markets = [
        _quote(
            f"KXECON-{index:02d}",
            "Economics",
            moment + timedelta(days=2),
        )
        for index in range(51)
    ]
    markets.append(_quote("KXFIN-SOON", "Financials", moment + timedelta(hours=2)))
    markets.append(_quote("KXFIN-LATER", "Financials", moment + timedelta(days=4)))
    install_snapshot(markets, moment)
    client = TestClient(create_app())

    first = client.get("/api/markets")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["total"] == 53
    assert first_body["event_count"] == 53
    assert first_body["match_count"] == 52
    assert first_body["match_event_count"] == 52
    assert first_body["page"] == 1
    assert first_body["page_count"] == 2
    assert len(first_body["events"]) == 50
    assert "KXFIN-LATER" not in first.text

    second = client.get("/api/markets", params={"page": 2})
    assert second.status_code == 200
    assert len(second.json()["events"]) == 2
    assert second.json()["page_count"] == 2

    financials = client.get("/api/markets", params={"category": "Financials"})
    assert _tickers(financials.json()) == [
        "KXFIN-SOON",
    ]
    assert financials.json()["total"] == 53
    assert financials.json()["event_count"] == 53
    assert financials.json()["match_count"] == 1
    assert financials.json()["match_event_count"] == 1

    soon = client.get("/api/markets", params={"resolves_within": "24h"})
    assert _tickers(soon.json()) == ["KXFIN-SOON"]
    assert soon.json()["match_count"] == 1

    both = client.get(
        "/api/markets",
        params={"category": "Economics", "resolves_within": "24h"},
    )
    assert both.json()["events"] == []
    assert both.json()["match_count"] == 0
    assert both.json()["match_event_count"] == 0
    assert both.json()["total"] == 53
    assert both.json()["page_count"] == 1


def test_search_filters_the_snapshot() -> None:
    moment = datetime.now(timezone.utc)
    payrolls = _quote("KXECON-PAY", "Economics", moment + timedelta(days=1)).model_copy(
        update={
            "question": "Monthly payrolls above consensus USD",
            "settlement_source": "BLS",
        }
    )
    funds = _quote("KXFIN-FUNDS", "Financials", moment + timedelta(hours=2)).model_copy(
        update={"question": "Fed funds above the USD range"}
    )
    install_snapshot([payrolls, funds], moment)
    client = TestClient(create_app())

    found = client.get("/api/markets", params={"q": "payROLLS"})
    assert _tickers(found.json()) == ["KXECON-PAY"]
    assert found.json()["match_count"] == 1
    assert found.json()["total"] == 2

    words = client.get("/api/markets", params={"q": "fed range"})
    assert _tickers(words.json()) == ["KXFIN-FUNDS"]

    source = client.get("/api/markets", params={"q": "bls"})
    assert _tickers(source.json()) == ["KXECON-PAY"]

    event = client.get("/api/markets", params={"q": "KXFIN-FUNDS-EVENT"})
    assert _tickers(event.json()) == ["KXFIN-FUNDS"]

    narrowed = client.get(
        "/api/markets",
        params={"q": "above", "category": "Financials"},
    )
    assert _tickers(narrowed.json()) == ["KXFIN-FUNDS"]

    missing = client.get("/api/markets", params={"q": "payrolls sports"})
    assert missing.json()["events"] == []
    assert missing.json()["match_count"] == 0
    assert missing.json()["total"] == 2

    blank = client.get("/api/markets", params={"q": "   "})
    assert blank.json()["match_count"] == 2


def test_groups_contracts_under_one_event() -> None:
    moment = datetime.now(timezone.utc)
    low = _quote("KXECON-LOW", "Economics", moment + timedelta(days=1)).model_copy(
        update={
            "event_ticker": "KXECON-EVENT",
            "event_title": "Payrolls USD",
            "strike_label": "Above 100",
            "question": "Payrolls USD — Above 100",
            "yes_price": "0.2500",
            "volume": "2.50",
            "open_interest": "1.00",
            "floor_strike": "200",
            "rules_primary": "The payrolls print is the official BLS release.",
        }
    )
    high = low.model_copy(
        update={
            "ticker": "KXECON-HIGH",
            "strike_label": "Above 50",
            "question": "Payrolls USD — Above 50",
            "yes_price": "0.7500",
            "volume": "1.25",
            "open_interest": "3.00",
            "floor_strike": "50",
        }
    )
    install_snapshot([low, high], moment)
    client = TestClient(create_app())

    body = client.get("/api/markets").json()

    assert body["total"] == 2
    assert body["event_count"] == 1
    assert body["match_count"] == 2
    assert body["match_event_count"] == 1
    event = body["events"][0]
    assert event["title"] == "Payrolls USD"
    assert event["rules_primary"] == "The payrolls print is the official BLS release."
    assert event["event_ticker"] == "KXECON-EVENT"
    assert event["contract_count"] == 2
    assert event["yes_price_low"] == "0.2500"
    assert event["yes_price_high"] == "0.7500"
    assert event["volume"] == "3.75"
    assert event["open_interest"] == "4"
    assert [contract["ticker"] for contract in event["contracts"]] == [
        "KXECON-HIGH",
        "KXECON-LOW",
    ]
    assert event["contracts"][0]["rules_primary"] == event["rules_primary"]

    other = high.model_copy(
        update={"rules_primary": "A different strike resolves on a later print."}
    )
    install_snapshot([low, other], moment)
    split = client.get("/api/markets").json()["events"][0]
    assert split["rules_primary"] is None
    assert [contract["rules_primary"] for contract in split["contracts"]] == [
        "A different strike resolves on a later print.",
        "The payrolls print is the official BLS release.",
    ]

    install_snapshot([low, high], moment)

    found = client.get("/api/markets", params={"q": "official BLS"})
    explained = found.json()["events"][0]
    assert found.json()["match_count"] == 2
    assert explained["rules_primary"] == "The payrolls print is the official BLS release."

    found = client.get("/api/markets", params={"q": "Above 100"})
    matched = found.json()["events"][0]
    assert found.json()["match_count"] == 1
    assert found.json()["match_event_count"] == 1
    assert matched["contract_count"] == 1
    assert matched["title"] == "Payrolls USD"
    assert matched["contracts"][0]["ticker"] == "KXECON-LOW"
    assert matched["yes_price_low"] == "0.2500"
    assert matched["yes_price_high"] == "0.2500"
    assert matched["volume"] == "2.5"


def test_old_snapshot_uses_the_question_as_the_event_title() -> None:
    moment = datetime.now(timezone.utc)
    quote = _quote("KXECON-OLD", "Economics", moment + timedelta(days=1))
    stored = quote.model_dump(mode="json")
    del stored["event_title"]
    del stored["strike_label"]
    catalog_path().parent.mkdir(parents=True, exist_ok=True)
    catalog_path().write_text(
        json.dumps({"pulled_at": "2026-10-14T06:00:00Z", "markets": [stored]}),
        encoding="utf-8",
    )

    assert load_catalog() is True
    body = TestClient(create_app()).get("/api/markets").json()

    assert body["events"][0]["title"] == "KXECON-OLD USD"
    assert body["events"][0]["rules_primary"] is None
    assert body["events"][0]["contracts"][0]["strike_label"] is None


def test_catalog_hides_fifteen_minute_events() -> None:
    moment = datetime.now(timezone.utc)
    keep = _quote("KXEURUSD-KEEP", "Financials", moment + timedelta(hours=2))
    skip = _quote("KXEURUSD15M-SKIP", "Financials", moment + timedelta(minutes=15)).model_copy(
        update={
            "event_ticker": "KXEURUSD15M-26OCT202045",
            "event_title": "EUR/USD Up or Down – 15 minutes",
            "question": "EUR/USD Up or Down – 15 minutes",
        }
    )
    install_snapshot([keep, skip], moment)

    body = TestClient(create_app()).get("/api/markets").json()

    assert _tickers(body) == ["KXEURUSD-KEEP"]
    assert body["total"] == 1
    assert body["event_count"] == 1
    assert body["match_count"] == 1
    assert body["match_event_count"] == 1


def test_event_count_is_distinct_events_in_the_catalog() -> None:
    moment = datetime.now(timezone.utc)
    shared = _quote("KXECON-A", "Economics", moment + timedelta(days=1))
    sibling = shared.model_copy(update={"ticker": "KXECON-B", "question": "Sibling payrolls USD"})
    other = _quote("KXFIN-FUNDS", "Financials", moment + timedelta(hours=2))
    install_snapshot([shared, sibling, other], moment)

    body = TestClient(create_app()).get("/api/markets").json()

    assert body["total"] == 3
    assert body["event_count"] == 2


def test_next_refresh_is_the_next_eastern_slot() -> None:
    morning = datetime(2026, 10, 15, 10, 0, tzinfo=EASTERN)
    evening = datetime(2026, 10, 15, 19, 0, tzinfo=EASTERN)
    at_open = datetime(2026, 10, 15, 6, 0, tzinfo=EASTERN)

    assert seconds_until_next_refresh(morning) == 8 * 60 * 60
    assert seconds_until_next_refresh(evening) == 11 * 60 * 60
    assert seconds_until_next_refresh(at_open) == 12 * 60 * 60
    assert last_refresh_slot(morning) == datetime(2026, 10, 15, 6, 0, tzinfo=EASTERN)
    assert last_refresh_slot(evening) == datetime(2026, 10, 15, 18, 0, tzinfo=EASTERN)
    assert last_refresh_slot(at_open) == at_open
    assert last_refresh_slot(datetime(2026, 10, 15, 5, 0, tzinfo=EASTERN)) == datetime(
        2026, 10, 14, 18, 0, tzinfo=EASTERN
    )


def test_catalog_from_the_current_slot_is_kept() -> None:
    quote = _quote("KXECON-KEEP", "Economics", datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc))
    install_snapshot([quote], datetime(2026, 10, 14, 18, 0, tzinfo=EASTERN))
    assert catalog_is_current(datetime(2026, 10, 15, 5, 59, tzinfo=EASTERN)) is True
    assert catalog_is_current(datetime(2026, 10, 15, 6, 0, tzinfo=EASTERN)) is False

    install_snapshot([quote], datetime(2026, 10, 15, 6, 0, tzinfo=EASTERN))
    assert catalog_is_current(datetime(2026, 10, 15, 7, 15, tzinfo=EASTERN)) is True

    install_snapshot([quote], datetime(2026, 10, 15, 10, 12, tzinfo=EASTERN))
    assert catalog_is_current(datetime(2026, 10, 15, 11, 0, tzinfo=EASTERN)) is True
    assert catalog_is_current(datetime(2026, 10, 15, 18, 0, tzinfo=EASTERN)) is False


def test_missing_catalog_is_not_current() -> None:
    assert catalog_is_current(datetime(2026, 10, 15, 7, 15, tzinfo=EASTERN)) is False


def test_startup_skips_a_pull_when_the_catalog_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.market_data.catalog_is_current", lambda now=None: True)
    monkeypatch.setattr("app.market_data._run_pull", lambda: calls.append("pull"))
    monkeypatch.setattr("app.market_data.time.sleep", _stop_after_wait)

    from app import market_data

    with pytest.raises(RuntimeError, match="slept"):
        market_data._refresh_loop()

    assert calls == []


def test_startup_pulls_when_the_catalog_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.market_data.catalog_is_current", lambda now=None: False)
    monkeypatch.setattr("app.market_data._run_pull", lambda: calls.append("pull"))
    monkeypatch.setattr("app.market_data.time.sleep", _stop_after_wait)

    from app import market_data

    with pytest.raises(RuntimeError, match="slept"):
        market_data._refresh_loop()

    assert calls == ["pull"]


def _stop_after_wait(_seconds: float) -> None:
    raise RuntimeError("slept")


def test_empty_snapshot_retries_in_five_minutes() -> None:
    morning = datetime(2026, 10, 15, 10, 0, tzinfo=EASTERN)
    assert seconds_until_next_attempt(morning) == 5 * 60

    previous = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
    install_snapshot([_quote("KXECON-OLD", "Economics", previous)], previous)
    assert seconds_until_next_attempt(morning) == 8 * 60 * 60


def _one_contract_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/series"):
        return httpx.Response(
            200,
            json={"series": [{"ticker": "KXECON", "category": "Economics"}], "cursor": ""},
        )
    if path.endswith("/events"):
        return httpx.Response(
            200,
            json={
                "events": [
                    {
                        "event_ticker": "KXECON-EVENT",
                        "series_ticker": "KXECON",
                        "title": "Payrolls USD",
                    }
                ],
                "cursor": "",
            },
        )
    if path.endswith("/markets"):
        return httpx.Response(
            200,
            json={
                "markets": [
                    _raw_market(
                        "KXECON-FILE",
                        "KXECON-EVENT",
                        "Payrolls",
                        _iso(NOW + timedelta(days=1)),
                    )
                ],
                "cursor": "",
            },
        )
    return httpx.Response(404, json={"error": "unexpected-path"})


def _series_page(request: httpx.Request) -> httpx.Response:
    category = request.url.params["category"]
    cursor = request.url.params.get("cursor")
    if category == "Economics" and cursor is None:
        return httpx.Response(
            200,
            json={
                "series": [
                    {
                        "ticker": "KXECON",
                        "category": "Economics",
                        "contract_url": "https://example.com/econ-contract",
                        "contract_terms_url": "https://example.com/econ-terms",
                        "settlement_sources": [{"name": "Series source"}],
                    },
                    {"ticker": "KXSPORT", "category": "Sports"},
                ],
                "cursor": "econ-2",
            },
        )
    if category == "Economics" and cursor == "econ-2":
        return httpx.Response(
            200,
            json={
                "series": [
                    {"ticker": "KXECON2", "category": "Economics"},
                    {"ticker": "KXQUIET", "category": "Economics"},
                    {"ticker": "KXBARE"},
                ],
                "cursor": "",
            },
        )
    if category == "Financials":
        return httpx.Response(
            200,
            json={
                "series": [
                    {
                        "ticker": "KXFIN",
                        "category": "Financials",
                        "contract_terms_url": "https://example.com/fin-terms",
                        "contract_url": "https://example.com/fin-ignored",
                    },
                    {"ticker": "KXEURUSD15M", "category": "Financials"},
                    {"ticker": "KXECON", "category": "Economics"},
                ],
            },
        )
    return httpx.Response(500, json={"error": "kalshi-secret"})


def _events_page(request: httpx.Request) -> httpx.Response:
    assert request.url.params["status"] == "open"
    return httpx.Response(
        200,
        json={
            "events": [
                {
                    "event_ticker": "KXECON-EVENT",
                    "series_ticker": "KXECON",
                    "title": "Monthly payrolls USD",
                    "mutually_exclusive": False,
                    "collateral_return_type": "mecnet",
                    "settlement_sources": [{"name": "BLS"}, {"name": "BEA"}],
                },
                {
                    "event_ticker": "KXECON2-EVENT",
                    "series_ticker": "KXECON2",
                    "title": "Jobs above consensus USD",
                },
                {
                    "event_ticker": "KXFIN-EVENT",
                    "series_ticker": "KXFIN",
                    "title": "Fed funds USD",
                },
                {
                    "event_ticker": "KXEURUSD15M-26OCT202045",
                    "series_ticker": "KXEURUSD15M",
                    "category": "Financials",
                    "title": "EUR/USD Up or Down – 15 minutes",
                },
                {
                    "event_ticker": "KXBARE-EVENT",
                    "series_ticker": "KXBARE",
                    "category": "Economics",
                    "title": "Bare event USD",
                    "mutually_exclusive": True,
                    "collateral_return_type": "directional",
                },
                {
                    "event_ticker": "KXNOPUSD-EVENT",
                    "series_ticker": "KXECON2",
                    "title": "Euro area CPI",
                },
                {"event_ticker": "KXSPORT-EVENT", "series_ticker": "KXSPORT"},
            ],
            "cursor": "",
        },
    )


def _markets_page(request: httpx.Request) -> httpx.Response:
    assert request.url.params["status"] == "open"
    assert request.url.params["mve_filter"] == "exclude"
    assert "series_ticker" not in request.url.params
    return httpx.Response(
        200,
        json={
            "markets": [
                _raw_market(
                    "KXECON-KEEP",
                    "KXECON-EVENT",
                    "Payrolls above consensus",
                    _iso(NOW + timedelta(days=8)),
                    expected_expiration_time=_iso(NOW + timedelta(days=3)),
                    close_time=_iso(NOW + timedelta(days=2)),
                    yes_sub_title="Above consensus",
                    open_interest_fp="12.00",
                    strike_type="greater",
                    floor_strike=51075,
                    rules_primary="The payrolls print is the official BLS release.",
                ),
                _raw_market(
                    "KXECON-LATE",
                    "KXECON-EVENT",
                    "Payrolls next month",
                    _iso(NOW + timedelta(days=8)),
                ),
                {"ticker": "KXECON-BROKEN", "event_ticker": "KXECON-EVENT"},
                _raw_market(
                    "KXECON2-SOON",
                    "KXECON2-EVENT",
                    "",
                    _iso(NOW + timedelta(days=1)),
                    yes_sub_title="Not appended",
                    omit=("yes_bid_dollars", "yes_ask_dollars"),
                    last_price_dollars="0.4200",
                ),
                _raw_market(
                    "KXFIN-KEEP",
                    "KXFIN-EVENT",
                    "Fed funds above the current range",
                    "",
                    expiration_time=_iso(NOW + timedelta(days=3)),
                    close_time=_iso(NOW + timedelta(days=2)),
                    yes_bid_dollars="0.3300",
                    omit=("yes_ask_dollars", "latest_expiration_time"),
                ),
                _raw_market(
                    "KXEURUSD15M-SKIP",
                    "KXEURUSD15M-26OCT202045",
                    "EUR/USD Up or Down – 15 minutes",
                    _iso(NOW + timedelta(minutes=15)),
                ),
                _raw_market(
                    "KXBARE-KEEP",
                    "KXBARE-EVENT",
                    "Bare contract",
                    _iso(NOW + timedelta(days=2)),
                ),
                _raw_market(
                    "KXNOPUSD-SKIP",
                    "KXNOPUSD-EVENT",
                    "Euro area CPI",
                    _iso(NOW + timedelta(days=1)),
                ),
                _raw_market(
                    "KXSPORT-SKIP",
                    "KXSPORT-EVENT",
                    "A sports contract",
                    _iso(NOW + timedelta(days=1)),
                ),
            ],
            "cursor": "",
        },
    )


def _raw_market(
    ticker: str,
    event_ticker: str,
    title: str,
    resolves_at: str,
    *,
    omit: tuple[str, ...] = (),
    **extra: object,
) -> dict[str, object]:
    market: dict[str, object] = {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "title": title,
        "yes_sub_title": "yes side",
        "status": "active",
        "yes_bid_dollars": "0.5600",
        "yes_ask_dollars": "0.5800",
        "volume_fp": "10.00",
        "latest_expiration_time": resolves_at,
    }
    market.update(extra)
    for key in omit:
        market.pop(key, None)
    return market


def _quote(ticker: str, category: str, resolves_at: datetime) -> MarketQuote:
    return MarketQuote(
        ticker=ticker,
        event_ticker=f"{ticker}-EVENT",
        question=f"{ticker} USD",
        status="active",
        volume="1.00",
        open_interest="1.00",
        market_count=1,
        mutually_exclusive=False,
        category=category,  # type: ignore[arg-type]
        settlement_time=_iso(resolves_at),
    )


def _tickers(body: dict[str, object]) -> list[str]:
    events = body["events"]
    assert isinstance(events, list)
    tickers: list[str] = []
    for event in events:
        assert isinstance(event, dict)
        contracts = event["contracts"]
        assert isinstance(contracts, list)
        for contract in contracts:
            assert isinstance(contract, dict)
            ticker = contract["ticker"]
            assert isinstance(ticker, str)
            tickers.append(ticker)
    return tickers


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
