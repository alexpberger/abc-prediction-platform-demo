"""Catalog of short-horizon Kalshi economics and financials contracts.

The live catalog is in memory. The last successful pull is also stored in
`backend/.data/market-catalog.json`, or in `MARKET_CATALOG_PATH` when that
variable is set. The production base URL lives here so a later signed order
call can use the same host. This module only reads public market data.
Fifteen-minute FX windows are excluded.
"""

import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import ceil
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from app.schemas.markets import (
    Category,
    ContractQuote,
    EventQuote,
    MarketListResponse,
    MarketQuote,
    ResolvesWithin,
)

_SETTLEMENT_FIELDS = (
    "expected_expiration_time",
    "latest_expiration_time",
    "expiration_time",
    "close_time",
)

DEFAULT_KALSHI_API_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
TIMEOUT_SECONDS = 10.0
PAGE_SIZE = 50
RESOLUTION_HORIZON = timedelta(days=3)
ALLOWED_CATEGORIES: tuple[Category, ...] = ("Economics", "Financials")
QUESTION_CONTAINS = "USD"
EXCLUDED_SERIES_SUFFIXES = ("15M",)
REFRESH_HOURS = (6, 18)
EMPTY_SNAPSHOT_RETRY_SECONDS = 5 * 60
EASTERN = ZoneInfo("America/New_York")
RESOLVES_WITHIN = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
}


class MarketDataUnavailable(Exception):
    """Kalshi did not return a usable catalog, and no snapshot is stored."""


class Catalog:
    def __init__(self, markets: tuple[MarketQuote, ...], pulled_at: datetime) -> None:
        self.markets = markets
        self.pulled_at = pulled_at


_lock = threading.Lock()
_catalog: Catalog | None = None
_refresh_started = False
_refreshing = False
_initial_refresh_done = threading.Event()


def kalshi_base_url() -> str:
    configured = os.environ.get("KALSHI_API_BASE_URL", DEFAULT_KALSHI_API_BASE_URL)
    return configured.strip().rstrip("/")


@dataclass(frozen=True)
class MarketSettlement:
    """A contract's published result, and the time Kalshi expects it to settle."""

    result: str | None
    settlement_time: datetime | None


def fetch_market_settlement(client: httpx.Client, ticker: str) -> MarketSettlement:
    """Read one contract. A yes or no result is settled. An empty result is not."""
    body = _get_json(client, f"/markets/{quote(ticker, safe='')}", {})
    market = body.get("market")
    if not isinstance(market, dict):
        raise MarketDataUnavailable
    raw = market.get("result")
    result = raw if raw in ("yes", "no") else None
    settlement_time = _parse_time(_settlement_time(market) or "")
    return MarketSettlement(result=result, settlement_time=settlement_time)


def catalog_path() -> Path:
    """Path of the last successful catalog pull."""
    configured = os.environ.get("MARKET_CATALOG_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / ".data" / "market-catalog.json"


def install_snapshot(markets: list[MarketQuote], pulled_at: datetime) -> None:
    """Replace the in-memory catalog. Tests use this so they do not call Kalshi."""
    moment = _aware(pulled_at)
    ordered = tuple(sorted(markets, key=lambda market: (market.settlement_time, market.ticker)))
    with _lock:
        global _catalog
        _catalog = Catalog(ordered, moment)


def load_catalog() -> bool:
    """Load the catalog file into memory. A missing or unreadable file leaves memory unchanged."""
    try:
        body = json.loads(catalog_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(body, dict):
        return False
    pulled_at = body.get("pulled_at")
    markets = body.get("markets")
    if not isinstance(pulled_at, str) or not isinstance(markets, list):
        return False
    moment = _parse_time(pulled_at)
    if moment is None:
        return False
    try:
        quotes = [MarketQuote.model_validate(item) for item in markets]
    except ValidationError:
        return False
    install_snapshot(quotes, moment)
    return True


def clear_snapshot() -> None:
    with _lock:
        global _catalog
        _catalog = None


def current_snapshot() -> Catalog | None:
    with _lock:
        return _catalog


def start_catalog_refresh() -> None:
    """Load the catalog file, then pull at 06:00 and 18:00 US Eastern.

    A snapshot from the current slot is served as it is. An older file is
    served while a new pull runs. A missing catalog is pulled immediately.
    An empty catalog retries every five minutes until a pull succeeds.
    """
    global _refresh_started
    with _lock:
        if _refresh_started:
            return
        _refresh_started = True
    if load_catalog():
        _initial_refresh_done.set()
    thread = threading.Thread(
        target=_refresh_loop,
        name="market-catalog",
        daemon=True,
    )
    thread.start()


def refresh_catalog(client: httpx.Client, *, now: datetime | None = None) -> None:
    """Pull a new snapshot. A failed later pull keeps the previous one."""
    moment = _aware(now or datetime.now(timezone.utc))
    try:
        markets = _pull_catalog(client, moment)
    except MarketDataUnavailable:
        if current_snapshot() is None:
            raise
        return
    install_snapshot(markets, moment)
    _write_catalog()


def query_catalog(
    *,
    category: Category | None,
    resolves_within: ResolvesWithin,
    page: int,
    q: str | None = None,
    now: datetime | None = None,
) -> MarketListResponse:
    _wait_for_initial_refresh()
    catalog = current_snapshot()
    if catalog is None:
        raise MarketDataUnavailable
    moment = _aware(now or datetime.now(timezone.utc))
    deadline = moment + RESOLVES_WITHIN[resolves_within]
    terms = _search_terms(q)
    visible = [market for market in catalog.markets if _catalog_visible(market)]
    matched = [
        market
        for market in visible
        if _matches(market, category=category, deadline=deadline, terms=terms)
    ]
    events = _group_events(matched)
    match_count = len(matched)
    match_event_count = len(events)
    page_count = ceil(match_event_count / PAGE_SIZE) if match_event_count else 1
    start = (page - 1) * PAGE_SIZE
    return MarketListResponse(
        events=events[start : start + PAGE_SIZE],
        pulled_at=catalog.pulled_at,
        total=len(visible),
        event_count=len({market.event_ticker for market in visible}),
        match_count=match_count,
        match_event_count=match_event_count,
        page=page,
        page_count=page_count,
    )


def seconds_until_next_refresh(now: datetime | None = None) -> float:
    """Seconds until the next 06:00 or 18:00 in US Eastern."""
    current = _eastern(now)
    slots = [_slot_on(current, hour) for hour in REFRESH_HOURS]
    upcoming = [slot if slot > current else slot + timedelta(days=1) for slot in slots]
    return (min(upcoming) - current).total_seconds()


def last_refresh_slot(now: datetime | None = None) -> datetime:
    """Most recent 06:00 or 18:00 in US Eastern, including now."""
    current = _eastern(now)
    slots = []
    for hour in REFRESH_HOURS:
        slot = _slot_on(current, hour)
        if slot > current:
            slot -= timedelta(days=1)
        slots.append(slot)
    return max(slots)


def catalog_is_current(now: datetime | None = None) -> bool:
    """True when the snapshot was pulled at or after the latest Eastern slot."""
    catalog = current_snapshot()
    if catalog is None:
        return False
    return catalog.pulled_at >= last_refresh_slot(now)


def seconds_until_next_attempt(now: datetime | None = None) -> float:
    """Seconds until the next pull. An empty catalog retries in five minutes."""
    if current_snapshot() is None:
        return float(EMPTY_SNAPSHOT_RETRY_SECONDS)
    return seconds_until_next_refresh(now)


def _refresh_loop() -> None:
    if not catalog_is_current():
        _run_pull()
    _initial_refresh_done.set()
    while True:
        time.sleep(seconds_until_next_attempt())
        _run_pull()


def _run_pull() -> None:
    with _lock:
        global _refreshing
        if _refreshing:
            return
        _refreshing = True
    try:
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                refresh_catalog(client)
        except (MarketDataUnavailable, OSError):
            pass
    finally:
        with _lock:
            _refreshing = False


def _write_catalog() -> None:
    catalog = current_snapshot()
    if catalog is None:
        return
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pulled_at": catalog.pulled_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "markets": [market.model_dump(mode="json") for market in catalog.markets],
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _eastern(now: datetime | None) -> datetime:
    return _aware(now or datetime.now(EASTERN)).astimezone(EASTERN)


def _slot_on(current: datetime, hour: int) -> datetime:
    return current.replace(hour=hour, minute=0, second=0, microsecond=0)


def _wait_for_initial_refresh() -> None:
    if _refresh_started and not _initial_refresh_done.is_set():
        _initial_refresh_done.wait()


@dataclass(frozen=True)
class _SeriesInfo:
    category: Category | None
    settlement_names: tuple[str, ...]
    rules_url: str | None


@dataclass(frozen=True)
class _EventInfo:
    category: Category
    title: str
    mutually_exclusive: bool
    collateral_return_type: str | None
    settlement_source: str | None
    rules_url: str | None


@dataclass(frozen=True)
class _PendingMarket:
    ticker: str
    event_ticker: str
    event_title: str
    yes_sub_title: str | None
    category: Category
    yes_price: str | None
    volume: str
    close_time: str | None
    open_interest: str
    mutually_exclusive: bool
    collateral_return_type: str | None
    strike_type: str | None
    floor_strike: str | None
    cap_strike: str | None
    status: str
    settlement_time: str
    settlement_source: str | None
    rules_primary: str | None
    rules_url: str | None


def _pull_catalog(client: httpx.Client, now: datetime) -> list[MarketQuote]:
    series: dict[str, _SeriesInfo] = {}
    for category in ALLOWED_CATEGORIES:
        for page in _iter_pages(client, "/series", {"category": category}, "series"):
            for item in page:
                kept = _series_info(item)
                if kept is None:
                    continue
                ticker, info = kept
                series.setdefault(ticker, info)

    events: dict[str, _EventInfo] = {}
    for page in _iter_pages(client, "/events", {"status": "open", "limit": 200}, "events"):
        for item in page:
            kept = _event_info(item, series)
            if kept is None:
                continue
            event_ticker, info = kept
            events.setdefault(event_ticker, info)

    deadline = now + RESOLUTION_HORIZON
    counts: dict[str, int] = {}
    pending: list[_PendingMarket] = []
    for page in _iter_pages(
        client,
        "/markets",
        {"status": "open", "mve_filter": "exclude", "limit": 1000},
        "markets",
    ):
        for item in page:
            if not isinstance(item, dict):
                continue
            event_ticker = _text(item.get("event_ticker"))
            if event_ticker is None:
                continue
            counts[event_ticker] = counts.get(event_ticker, 0) + 1
            event = events.get(event_ticker)
            if event is None:
                continue
            candidate = _pending_market(item, event_ticker, event)
            if candidate is None:
                continue
            settles = _parse_time(candidate.settlement_time)
            if settles is None or settles > deadline:
                continue
            pending.append(candidate)

    quotes: list[MarketQuote] = []
    for candidate in pending:
        question = _question(
            candidate.event_title,
            candidate.yes_sub_title,
            counts.get(candidate.event_ticker, 1),
        )
        if question is None or not _question_visible(question):
            continue
        try:
            quotes.append(
                MarketQuote(
                    ticker=candidate.ticker,
                    event_ticker=candidate.event_ticker,
                    event_title=candidate.event_title,
                    strike_label=candidate.yes_sub_title,
                    question=question,
                    category=candidate.category,
                    yes_price=candidate.yes_price,
                    volume=candidate.volume,
                    close_time=candidate.close_time,
                    open_interest=candidate.open_interest,
                    market_count=counts.get(candidate.event_ticker, 1),
                    mutually_exclusive=candidate.mutually_exclusive,
                    collateral_return_type=candidate.collateral_return_type,
                    strike_type=candidate.strike_type,
                    floor_strike=candidate.floor_strike,
                    cap_strike=candidate.cap_strike,
                    status=candidate.status,
                    settlement_time=candidate.settlement_time,
                    settlement_source=candidate.settlement_source,
                    rules_primary=candidate.rules_primary,
                    rules_url=candidate.rules_url,
                )
            )
        except ValidationError:
            continue
    return quotes


def _series_info(item: object) -> tuple[str, _SeriesInfo] | None:
    if not isinstance(item, dict):
        return None
    ticker = _text(item.get("ticker"))
    if ticker is None:
        return None
    category = item.get("category")
    primary: Category | None = category if category in ALLOWED_CATEGORIES else None
    return ticker, _SeriesInfo(
        category=primary,
        settlement_names=_source_names(item.get("settlement_sources")),
        rules_url=_text(item.get("contract_terms_url")) or _text(item.get("contract_url")),
    )


def _event_info(
    item: object,
    series: dict[str, _SeriesInfo],
) -> tuple[str, _EventInfo] | None:
    if not isinstance(item, dict):
        return None
    event_ticker = _text(item.get("event_ticker"))
    series_ticker = _text(item.get("series_ticker"))
    if event_ticker is None or series_ticker is None:
        return None
    if _excluded_series(series_ticker):
        return None
    info = series.get(series_ticker)
    series_category = info.category if info is not None else None
    event_category = item.get("category")
    fallback: Category | None = event_category if event_category in ALLOWED_CATEGORIES else None
    category = series_category or fallback
    if category is None:
        return None
    names = _source_names(item.get("settlement_sources"))
    if not names and info is not None:
        names = info.settlement_names
    return event_ticker, _EventInfo(
        category=category,
        title=_text(item.get("title")) or "",
        mutually_exclusive=item.get("mutually_exclusive") is True,
        collateral_return_type=_text(item.get("collateral_return_type")),
        settlement_source=", ".join(names) or None,
        rules_url=info.rules_url if info is not None else None,
    )


def _pending_market(
    item: dict[str, Any],
    event_ticker: str,
    event: _EventInfo,
) -> _PendingMarket | None:
    ticker = _text(item.get("ticker"))
    status = _text(item.get("status"))
    settlement_time = _settlement_time(item)
    if ticker is None or status is None or settlement_time is None:
        return None
    return _PendingMarket(
        ticker=ticker,
        event_ticker=event_ticker,
        event_title=event.title,
        yes_sub_title=_text(item.get("yes_sub_title")),
        category=event.category,
        yes_price=_yes_price(item),
        volume=_text(item.get("volume_fp")) or "",
        close_time=_time_text(item.get("close_time")),
        open_interest=_text(item.get("open_interest_fp")) or "",
        mutually_exclusive=event.mutually_exclusive,
        collateral_return_type=event.collateral_return_type,
        strike_type=_text(item.get("strike_type")),
        floor_strike=_strike_text(item.get("floor_strike")),
        cap_strike=_strike_text(item.get("cap_strike")),
        status=status,
        settlement_time=settlement_time,
        settlement_source=event.settlement_source,
        rules_primary=_text(item.get("rules_primary")),
        rules_url=event.rules_url,
    )


def _iter_pages(
    client: httpx.Client,
    path: str,
    params: dict[str, str | int],
    key: str,
) -> Iterator[list[object]]:
    cursor = ""
    seen: set[str] = set()
    while True:
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        body = _get_json(client, path, query)
        page = body.get(key)
        next_cursor = body.get("cursor") or ""
        if not isinstance(page, list) or not isinstance(next_cursor, str):
            raise MarketDataUnavailable
        yield page
        if not next_cursor or next_cursor in seen:
            return
        seen.add(next_cursor)
        cursor = next_cursor


def _get_json(
    client: httpx.Client,
    path: str,
    params: dict[str, str | int],
) -> dict[str, Any]:
    """Read one Kalshi page.

    The first three 429 responses use the short pause. Later ones wait longer
    so a long pull can finish.
    """
    for attempt in range(8):
        try:
            response = client.get(f"{kalshi_base_url()}{path}", params=params)
        except httpx.HTTPError as exc:
            raise MarketDataUnavailable from exc
        if response.status_code == 429 and attempt < 7:
            if attempt < 3:
                time.sleep(0.5 * (attempt + 1))
            else:
                time.sleep(2 ** (attempt - 1))
            continue
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MarketDataUnavailable from exc
        if not isinstance(body, dict):
            raise MarketDataUnavailable
        return body
    raise MarketDataUnavailable


def _group_events(markets: list[MarketQuote]) -> list[EventQuote]:
    """Group a filtered contract list into events with nested strikes."""
    grouped: dict[str, list[MarketQuote]] = {}
    for market in markets:
        grouped.setdefault(market.event_ticker, []).append(market)
    events = [_event_quote(contracts) for contracts in grouped.values()]
    events.sort(key=_event_sort_key)
    return events


def _event_quote(contracts: list[MarketQuote]) -> EventQuote:
    ordered = sorted(contracts, key=_contract_sort_key)
    first = ordered[0]
    low, high = _price_bounds(ordered)
    return EventQuote(
        event_ticker=first.event_ticker,
        title=_event_title(ordered),
        category=first.category,
        contract_count=len(ordered),
        yes_price_low=low,
        yes_price_high=high,
        volume=_sum_amounts(contract.volume for contract in ordered),
        open_interest=_sum_amounts(contract.open_interest for contract in ordered),
        close_time=_soonest(contract.close_time for contract in ordered),
        settlement_time=_soonest(contract.settlement_time for contract in ordered) or first.settlement_time,
        mutually_exclusive=first.mutually_exclusive,
        collateral_return_type=first.collateral_return_type,
        settlement_source=first.settlement_source,
        rules_primary=_rules_primary(ordered),
        rules_url=first.rules_url,
        contracts=[_contract_quote(contract) for contract in ordered],
    )


def _contract_quote(market: MarketQuote) -> ContractQuote:
    return ContractQuote(
        ticker=market.ticker,
        strike_label=market.strike_label,
        strike_type=market.strike_type,
        floor_strike=market.floor_strike,
        cap_strike=market.cap_strike,
        yes_price=market.yes_price,
        volume=market.volume,
        open_interest=market.open_interest,
        status=market.status,
        close_time=market.close_time,
        rules_primary=market.rules_primary,
    )


def _rules_primary(contracts: list[MarketQuote]) -> str | None:
    """Return the settlement text when every strike in the event shares it."""
    texts = {contract.rules_primary for contract in contracts if contract.rules_primary}
    if len(texts) == 1 and all(contract.rules_primary for contract in contracts):
        return texts.pop()
    return None


def _event_title(contracts: list[MarketQuote]) -> str:
    for contract in contracts:
        title = contract.event_title.strip()
        if title:
            return title
    return contracts[0].question


def _event_sort_key(event: EventQuote) -> tuple[datetime, str]:
    settles = _parse_time(event.settlement_time)
    if settles is None:
        settles = datetime.max.replace(tzinfo=timezone.utc)
    return settles, event.event_ticker


def _contract_sort_key(market: MarketQuote) -> tuple[int, Decimal, str, str]:
    floor = market.floor_strike
    if floor is None:
        return (1, Decimal(0), "", market.ticker)
    try:
        return (0, Decimal(floor), floor, market.ticker)
    except InvalidOperation:
        return (1, Decimal(0), floor, market.ticker)


def _price_bounds(contracts: list[MarketQuote]) -> tuple[str | None, str | None]:
    priced: list[tuple[Decimal, str]] = []
    for contract in contracts:
        if contract.yes_price is None:
            continue
        try:
            priced.append((Decimal(contract.yes_price), contract.yes_price))
        except InvalidOperation:
            continue
    if not priced:
        return None, None
    return min(priced)[1], max(priced)[1]


def _sum_amounts(values: Iterator[str]) -> str:
    total = Decimal(0)
    seen = False
    for value in values:
        text = value.strip()
        if not text:
            continue
        try:
            total += Decimal(text)
        except InvalidOperation:
            continue
        seen = True
    if not seen:
        return ""
    rendered = format(total, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _soonest(values: Iterator[str | None]) -> str | None:
    chosen: tuple[datetime, str] | None = None
    for value in values:
        if value is None:
            continue
        moment = _parse_time(value)
        if moment is None:
            continue
        if chosen is None or moment < chosen[0]:
            chosen = (moment, value)
    if chosen is None:
        return None
    return chosen[1]


def _question(event_title: str, yes_sub_title: str | None, market_count: int) -> str | None:
    title = event_title.strip()
    subtitle = yes_sub_title.strip() if yes_sub_title and yes_sub_title.strip() else ""
    if market_count > 1 and title and subtitle:
        return f"{title} — {subtitle}"
    if title:
        return title
    if subtitle:
        return subtitle
    return None


def _yes_price(item: dict[str, Any]) -> str | None:
    bid = _dollar(item.get("yes_bid_dollars"))
    ask = _dollar(item.get("yes_ask_dollars"))
    last = _dollar(item.get("last_price_dollars"))
    if bid is not None and ask is not None:
        chosen = (bid + ask) / 2
    elif last is not None:
        chosen = last
    elif bid is not None:
        chosen = bid
    elif ask is not None:
        chosen = ask
    else:
        return None
    return f"{chosen:.4f}"


def _dollar(value: object) -> Decimal | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def _settlement_time(item: dict[str, Any]) -> str | None:
    for key in _SETTLEMENT_FIELDS:
        text = _time_text(item.get(key))
        if text is not None:
            return text
    return None


def _time_text(value: object) -> str | None:
    text = _text(value)
    if text is None or _parse_time(text) is None:
        return None
    return text


def _source_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            name = _text(item)
        elif isinstance(item, dict):
            name = _text(item.get("name"))
        else:
            name = None
        if name is not None:
            names.append(name)
    return tuple(names)


def _strike_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "f").rstrip("0").rstrip(".")
    return _text(value)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _catalog_visible(market: MarketQuote) -> bool:
    return _question_visible(market.question) and not _excluded_series(market.event_ticker)


def _question_visible(question: str) -> bool:
    return QUESTION_CONTAINS in question


def _excluded_series(ticker: str) -> bool:
    return any(ticker.endswith(suffix) or f"{suffix}-" in ticker for suffix in EXCLUDED_SERIES_SUFFIXES)


def _search_terms(q: str | None) -> tuple[str, ...]:
    if q is None:
        return ()
    return tuple(part.casefold() for part in q.split() if part)


def _search_text(market: MarketQuote) -> str:
    parts = (
        market.question,
        market.event_title,
        market.strike_label,
        market.category,
        market.ticker,
        market.event_ticker,
        market.status,
        market.settlement_source,
        market.rules_primary,
        market.collateral_return_type,
        market.strike_type,
        market.floor_strike,
        market.cap_strike,
        market.volume,
        market.open_interest,
    )
    return " ".join(part for part in parts if part).casefold()


def _matches(
    market: MarketQuote,
    *,
    category: Category | None,
    deadline: datetime,
    terms: tuple[str, ...],
) -> bool:
    if category is not None and market.category != category:
        return False
    settles = _parse_time(market.settlement_time)
    if settles is None or settles > deadline:
        return False
    if not terms:
        return True
    haystack = _search_text(market)
    return all(term in haystack for term in terms)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment
