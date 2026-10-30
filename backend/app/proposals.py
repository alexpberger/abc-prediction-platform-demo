"""Paper proposals stored next to the market catalog.

A new proposal is stored when confidence beats the catalog price of the chosen
side. Its size is the Kelly fraction of the paper cash available then, and that
cash is stored with the proposal. A later page load can fill in the settlement
time and the Kalshi result for a row that does not have them yet. Cash results
are derived on read.
"""

import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.market_data import (
    TIMEOUT_SECONDS,
    MarketDataUnavailable,
    MarketSettlement,
    _parse_time,
    current_snapshot,
    fetch_market_settlement,
    query_catalog,
)
from app.schemas.markets import ContractQuote, EventQuote
from app.schemas.proposals import (
    Outcome,
    Proposal,
    ProposalDraft,
    ProposalList,
    ProposalTrace,
    ProposalView,
    ProposalViewList,
    Side,
    SkipReason,
    TraceCall,
    TraceContract,
    TraceEvent,
    TraceOpening,
)


class ProposalRejected(Exception):
    """The proposal names a contract that is not on that event."""


class ProposalAlreadyStored(Exception):
    """The contract already has a row in the proposal file."""

    def __init__(self) -> None:
        super().__init__("That contract already has a paper proposal.")


class ProposalSearchRejected(Exception):
    """The run did not record a search of a contract that is still in the future."""


class ProposalStoreError(Exception):
    """The proposal file cannot be read or written."""


class ProposalSkipped(Exception):
    """The draft has no edge, or the Kelly stake is below one contract."""

    def __init__(self, reason: SkipReason) -> None:
        self.reason = reason
        super().__init__(reason)


def proposals_path() -> Path:
    """Path of the append-only proposal file."""
    configured = os.environ.get("PROPOSALS_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / ".data" / "proposals.json"


def list_events() -> list[dict[str, object]]:
    """Return one row per visible event, without its contracts."""
    _pulled_at, events = _visible_events()
    return [_event_row(event) for event in events]


def get_event_contracts(event_ticker: str) -> list[dict[str, object]]:
    """Return the contracts of one event. An unknown event returns an empty list."""
    _pulled_at, events = _visible_events()
    event = _find_event(events, event_ticker)
    if event is None:
        return []
    return [_contract_row(event, contract) for contract in event.contracts]


def omit_proposed_contracts(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Drop contracts that already have a stored paper proposal."""
    taken = {proposal.ticker for proposal in load_proposals()}
    if not taken:
        return rows
    return [row for row in rows if row.get("ticker") not in taken]


class SearchLog:
    """Tool results for one agent run. The last event list is the one offered."""

    def __init__(self) -> None:
        self.searched_at = _utc(_search_clock())
        self.calls: list[TraceCall] = []
        self._event_lists: list[list[dict[str, object]]] = []
        self.openings: list[TraceOpening] = []
        self.catalog_pulled_at: datetime | None = None

    def record_events(self, rows: list[dict[str, object]]) -> None:
        """Record one list_events result. A later call replaces the offered list."""
        catalog = current_snapshot()
        if catalog is not None:
            self.catalog_pulled_at = catalog.pulled_at
        self.calls.append(TraceCall(name="list_events"))
        self._event_lists.append(rows)

    def record_contracts(self, event_ticker: str, rows: list[dict[str, object]]) -> None:
        """Record one get_event_contracts result, including an empty response."""
        self.calls.append(TraceCall(name="get_event_contracts", event_ticker=event_ticker))
        self.openings.append(
            TraceOpening(
                event_ticker=event_ticker,
                contracts=[TraceContract.model_validate(row) for row in rows],
            )
        )

    def finish(self, event_reason: str) -> ProposalTrace:
        """Build the trace. The offered events are the last list_events result."""
        rows = self._event_lists[-1] if self._event_lists else []
        return ProposalTrace(
            searched_at=self.searched_at,
            catalog_pulled_at=self.catalog_pulled_at or self.searched_at,
            events=[TraceEvent.model_validate(row) for row in rows],
            calls=self.calls,
            opened=self.openings,
            event_reason=event_reason,
        )


def load_proposals() -> list[Proposal]:
    """Return the stored proposals. A missing file is an empty list."""
    path = proposals_path()
    if not path.exists():
        return []
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        return ProposalList.model_validate(body).proposals
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ProposalStoreError("The proposal file cannot be read.") from exc


def accept_proposal(draft: ProposalDraft, trace: ProposalTrace) -> Proposal:
    """Store a draft when it is new, the search and catalog accept it, and it has an edge."""
    stored = load_proposals()
    if any(proposal.ticker == draft.ticker for proposal in stored):
        raise ProposalAlreadyStored
    _require_search(draft, trace)
    pulled_at, events = _visible_events()
    event = _find_event(events, draft.event_ticker)
    contract = None if event is None else _find_contract(event, draft.ticker)
    if event is None or contract is None:
        raise ProposalRejected
    priced = _side_price(contract.yes_price, draft.side)
    if priced is None:
        raise ProposalSkipped("edge")
    yes_price, entry_price, entry = priced
    fraction = _kelly_fraction(draft.confidence, entry)
    if fraction is None:
        raise ProposalSkipped("edge")
    cash = _bankroll_cash(stored)
    quantity = _contracts(fraction, cash, entry)
    if quantity < 1:
        raise ProposalSkipped("size")
    proposal = Proposal(
        event_ticker=draft.event_ticker,
        ticker=draft.ticker,
        side=draft.side,
        hypothesis=draft.hypothesis,
        confidence=draft.confidence,
        catalog_pulled_at=pulled_at,
        proposed_at=datetime.now(timezone.utc),
        settlement_time=_parse_time(event.settlement_time),
        yes_price=yes_price,
        entry_price=entry_price,
        quantity=quantity,
        kelly_fraction=_money(fraction),
        bankroll=_money(cash),
        trace=trace,
    )
    _append(proposal)
    return proposal


def refresh_outcomes(
    now: datetime | None = None,
    lookup: Callable[[str], MarketSettlement] | None = None,
) -> list[Proposal]:
    """Fill missing results from Kalshi, then return the stored proposals.

    A row is looked up only when it has no result and its settlement time is
    unknown or already past. One failed lookup leaves that row unchanged.
    """
    moment = _utc(now or datetime.now(timezone.utc))
    stored = load_proposals()
    tickers = list(
        dict.fromkeys(proposal.ticker for proposal in stored if _needs_lookup(proposal, moment))
    )
    if not tickers:
        return stored
    found = _lookup_results(tickers, lookup)
    changed = False
    refreshed: list[Proposal] = []
    for proposal in stored:
        if not _needs_lookup(proposal, moment):
            refreshed.append(proposal)
            continue
        settlement = found.get(proposal.ticker)
        if settlement is None:
            refreshed.append(proposal)
            continue
        updated = _apply_settlement(proposal, settlement)
        changed = changed or updated != proposal
        refreshed.append(updated)
    if changed:
        _write(refreshed)
    return refreshed


def proposal_view(proposal: Proposal, now: datetime | None = None) -> ProposalView:
    """Add the derived outcome and cash result. These values are not written."""
    moment = _utc(now or datetime.now(timezone.utc))
    cost, payout, realized = _position_cash(proposal)
    return ProposalView(
        event_ticker=proposal.event_ticker,
        ticker=proposal.ticker,
        side=proposal.side,
        hypothesis=proposal.hypothesis,
        confidence=proposal.confidence,
        catalog_pulled_at=proposal.catalog_pulled_at,
        proposed_at=proposal.proposed_at,
        settlement_time=proposal.settlement_time,
        result=proposal.result,
        yes_price=proposal.yes_price,
        entry_price=proposal.entry_price,
        quantity=proposal.quantity,
        kelly_fraction=proposal.kelly_fraction,
        bankroll=proposal.bankroll,
        trace=proposal.trace,
        outcome=outcome_for(proposal, moment),
        cost=cost,
        payout=payout,
        realized_pnl=realized,
    )


def proposal_views(proposals: list[Proposal], now: datetime | None = None) -> ProposalViewList:
    """Derive a page list. The total is null when no settled row has a price."""
    views = [proposal_view(proposal, now) for proposal in proposals]
    return ProposalViewList(
        proposals=views,
        realized_total=realized_total(views),
        bankroll=_money(_bankroll_cash(proposals)),
    )


def realized_total(views: list[ProposalView]) -> str | None:
    """Sum settled priced rows. A net of zero is a decimal string, not null."""
    amounts: list[Decimal] = []
    for view in views:
        amount = _dollars(view.realized_pnl)
        if amount is not None:
            amounts.append(amount)
    if not amounts:
        return None
    return _money(sum(amounts, _ZERO))


def outcome_for(proposal: Proposal, now: datetime) -> Outcome:
    """Won or lost once Kalshi has a result. Open before settlement, then pending."""
    if proposal.result is not None:
        return "won" if proposal.result == proposal.side else "lost"
    moment = _utc(now)
    if proposal.settlement_time is not None and _utc(proposal.settlement_time) > moment:
        return "open"
    return "pending"


def _search_clock() -> datetime:
    """Clock for the agent catalog. Tests freeze it. proposed_at uses the wall clock."""
    return datetime.now(timezone.utc)


def _visible_events() -> tuple[datetime, list[EventQuote]]:
    """Events that settle after the search clock and within 3 days.

    The market page calls query_catalog itself and still includes events already past.
    """
    moment = _utc(_search_clock())
    events: list[EventQuote] = []
    page = 1
    while True:
        response = query_catalog(category=None, resolves_within="3d", page=page, now=moment)
        events.extend(event for event in response.events if _settles_after(event.settlement_time, moment))
        if page >= response.page_count:
            return response.pulled_at, events
        page += 1


def _settles_after(settlement_time: str, moment: datetime) -> bool:
    settles = _parse_time(settlement_time)
    return settles is not None and settles > moment


def _event_row(event: EventQuote) -> dict[str, object]:
    return {
        "event_ticker": event.event_ticker,
        "title": event.title,
        "category": event.category,
        "contract_count": event.contract_count,
        "yes_price_low": event.yes_price_low,
        "yes_price_high": event.yes_price_high,
        "settlement_time": event.settlement_time,
    }


def _contract_row(event: EventQuote, contract: ContractQuote) -> dict[str, object]:
    return {
        "ticker": contract.ticker,
        "strike_label": contract.strike_label,
        "yes_price": contract.yes_price,
        "settlement_time": event.settlement_time,
    }


def _require_search(draft: ProposalDraft, trace: ProposalTrace) -> None:
    """Refuse a run that did not list events, open the chosen event, and pick a future contract."""
    listed = any(call.name == "list_events" for call in trace.calls)
    opened_call = any(
        call.name == "get_event_contracts" and call.event_ticker == draft.event_ticker
        for call in trace.calls
    )
    in_list = any(event.event_ticker == draft.event_ticker for event in trace.events)
    opening = _last_opening(trace, draft.event_ticker)
    contract = None
    if opening is not None:
        contract = next((item for item in opening.contracts if item.ticker == draft.ticker), None)
    settles = None if contract is None else _parse_time(contract.settlement_time)
    if not listed or not opened_call or not in_list or contract is None or settles is None:
        raise ProposalSearchRejected
    if settles <= _utc(trace.searched_at):
        raise ProposalSearchRejected


def _last_opening(trace: ProposalTrace, event_ticker: str) -> TraceOpening | None:
    found: TraceOpening | None = None
    for opening in trace.opened:
        if opening.event_ticker == event_ticker:
            found = opening
    return found


def _find_event(events: list[EventQuote], event_ticker: str) -> EventQuote | None:
    for event in events:
        if event.event_ticker == event_ticker:
            return event
    return None


def _find_contract(event: EventQuote, ticker: str) -> ContractQuote | None:
    for contract in event.contracts:
        if contract.ticker == ticker:
            return contract
    return None


_ZERO = Decimal("0")
_ONE = Decimal("1")
_QUANTUM = Decimal("0.0001")
_BANKROLL = Decimal("10000")


def _side_price(yes_price: str | None, side: Side) -> tuple[str, str, Decimal] | None:
    """Catalog yes price and the price of the chosen side. An unusable yes price is omitted."""
    yes = _dollars(yes_price)
    if yes is None or yes < _ZERO or yes > _ONE:
        return None
    entry = yes if side == "yes" else _ONE - yes
    return _money(yes), _money(entry), entry


def _kelly_fraction(confidence: float, entry: Decimal) -> Decimal | None:
    """Full Kelly fraction of the bankroll. None when confidence does not beat the price."""
    if entry <= _ZERO or entry >= _ONE:
        return None
    probability = Decimal(str(confidence))
    if probability <= entry:
        return None
    return (probability - entry) / (_ONE - entry)


def _contracts(fraction: Decimal, cash: Decimal, entry: Decimal) -> int:
    """Whole contracts bought with the Kelly stake. The price is the cost of one."""
    if cash <= _ZERO or entry <= _ZERO:
        return 0
    return int((cash * fraction) / entry)


def _bankroll_cash(proposals: list[Proposal]) -> Decimal:
    """Cash left from $10,000 after settled results and the cost of contracts still open."""
    cash = _BANKROLL
    for proposal in proposals:
        entry = _dollars(proposal.entry_price)
        if entry is None or proposal.quantity is None or entry < _ZERO or entry > _ONE:
            continue
        cost = entry * proposal.quantity
        if proposal.result is None:
            cash -= cost
            continue
        payout = _ONE * proposal.quantity if proposal.result == proposal.side else _ZERO
        cash += payout - cost
    return cash


def _position_cash(proposal: Proposal) -> tuple[str | None, str | None, str | None]:
    """Cost for a priced row. Payout and P&L wait until Kalshi has a result."""
    entry = _dollars(proposal.entry_price)
    if entry is None or proposal.quantity is None or entry < _ZERO or entry > _ONE:
        return None, None, None
    cost = entry * proposal.quantity
    if proposal.result is None:
        return _money(cost), None, None
    payout = _ONE * proposal.quantity if proposal.result == proposal.side else _ZERO
    return _money(cost), _money(payout), _money(payout - cost)


def _dollars(value: str | None) -> Decimal | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _money(value: Decimal) -> str:
    return f"{value.quantize(_QUANTUM):.4f}"


def _needs_lookup(proposal: Proposal, now: datetime) -> bool:
    if proposal.result is not None:
        return False
    if proposal.settlement_time is None:
        return True
    return _utc(proposal.settlement_time) <= now


def _lookup_results(
    tickers: list[str],
    lookup: Callable[[str], MarketSettlement] | None,
) -> dict[str, MarketSettlement | None]:
    if lookup is not None:
        return {ticker: _one_lookup(ticker, lookup) for ticker in tickers}
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        return {ticker: _fetch_or_none(client, ticker) for ticker in tickers}


def _fetch_or_none(client: httpx.Client, ticker: str) -> MarketSettlement | None:
    try:
        return fetch_market_settlement(client, ticker)
    except MarketDataUnavailable:
        return None


def _one_lookup(
    ticker: str,
    lookup: Callable[[str], MarketSettlement],
) -> MarketSettlement | None:
    try:
        return lookup(ticker)
    except MarketDataUnavailable:
        return None


def _apply_settlement(proposal: Proposal, settlement: MarketSettlement) -> Proposal:
    updates: dict[str, object] = {}
    if settlement.result in ("yes", "no"):
        updates["result"] = settlement.result
    if settlement.settlement_time is not None:
        updates["settlement_time"] = settlement.settlement_time
    if not updates:
        return proposal
    return proposal.model_copy(update=updates)


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _append(proposal: Proposal) -> None:
    stored = load_proposals()
    stored.append(proposal)
    _write(stored)


def _write(stored: list[Proposal]) -> None:
    path = proposals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = ProposalList(proposals=stored).model_dump(mode="json", exclude_none=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise ProposalStoreError("The proposal file cannot be written.") from exc
