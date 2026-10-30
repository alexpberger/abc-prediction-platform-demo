"""Paper proposals produced by the local agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["yes", "no"]


class ProposalDraft(BaseModel):
    """The fields the model chooses. The catalog time is added by the server."""

    event_ticker: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    side: Side
    hypothesis: str = Field(min_length=1)
    confidence: float = Field(
        ge=0,
        le=1,
        description="Probability that the chosen side wins.",
    )


class AgentChoice(ProposalDraft):
    """The model response. The event sentence is stored on the trace."""

    event_reason: str = Field(min_length=1)


class TraceEvent(BaseModel):
    """One event the agent was shown. This is a tool result, not the model's retelling."""

    event_ticker: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    contract_count: int = Field(ge=1)
    yes_price_low: str | None = None
    yes_price_high: str | None = None
    settlement_time: str = Field(min_length=1)


class TraceContract(BaseModel):
    """One contract returned for an event the agent opened."""

    ticker: str = Field(min_length=1)
    strike_label: str | None = None
    yes_price: str | None = None
    settlement_time: str = Field(min_length=1)


class TraceCall(BaseModel):
    """One tool call, in the order the run made it."""

    name: Literal["list_events", "get_event_contracts"]
    event_ticker: str | None = None


class TraceOpening(BaseModel):
    """The contracts returned for one get_event_contracts call."""

    event_ticker: str = Field(min_length=1)
    contracts: list[TraceContract]


class ProposalTrace(BaseModel):
    """What the server showed the model during the run that produced a proposal."""

    searched_at: datetime
    catalog_pulled_at: datetime
    events: list[TraceEvent]
    calls: list[TraceCall]
    opened: list[TraceOpening]
    event_reason: str = Field(min_length=1)


class Proposal(ProposalDraft):
    """A stored paper proposal.

    Older files may omit proposed_at, the paper price, the Kelly fraction, the
    bankroll that fraction was applied to, and the trace.
    """

    catalog_pulled_at: datetime
    proposed_at: datetime | None = None
    settlement_time: datetime | None = None
    result: Side | None = None
    yes_price: str | None = None
    entry_price: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    kelly_fraction: str | None = None
    bankroll: str | None = None
    trace: ProposalTrace | None = None


class ProposalList(BaseModel):
    proposals: list[Proposal]


Outcome = Literal["open", "pending", "won", "lost"]


class ProposalView(Proposal):
    """A proposal plus the outcome and cash result derived for the page.

    The file does not store the derived fields.
    """

    outcome: Outcome
    cost: str | None = None
    payout: str | None = None
    realized_pnl: str | None = None


SkipReason = Literal["edge", "size"]


class ProposalRun(BaseModel):
    """One agent run. A skip means nothing was stored."""

    proposal: Proposal | None = None
    skip: SkipReason | None = None


class ProposalRunView(BaseModel):
    """The run as the page receives it."""

    proposal: ProposalView | None = None
    skip: SkipReason | None = None


class ProposalViewList(BaseModel):
    proposals: list[ProposalView]
    realized_total: str | None = None
    bankroll: str
