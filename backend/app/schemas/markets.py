"""Catalog models for the stored market snapshot."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["Economics", "Financials"]
ResolvesWithin = Literal["24h", "3d"]


class MarketQuote(BaseModel):
    ticker: str = Field(min_length=1)
    event_ticker: str = Field(min_length=1)
    event_title: str = ""
    strike_label: str | None = None
    question: str = Field(min_length=1)
    category: Category
    yes_price: str | None = None
    volume: str = ""
    close_time: str | None = None
    open_interest: str = ""
    market_count: int = Field(ge=1)
    mutually_exclusive: bool
    collateral_return_type: str | None = None
    strike_type: str | None = None
    floor_strike: str | None = None
    cap_strike: str | None = None
    status: str = Field(min_length=1)
    settlement_time: str = Field(min_length=1)
    settlement_source: str | None = None
    rules_primary: str | None = None
    rules_url: str | None = None


class ContractQuote(BaseModel):
    ticker: str = Field(min_length=1)
    strike_label: str | None = None
    strike_type: str | None = None
    floor_strike: str | None = None
    cap_strike: str | None = None
    yes_price: str | None = None
    volume: str = ""
    open_interest: str = ""
    status: str = Field(min_length=1)
    close_time: str | None = None
    rules_primary: str | None = None


class EventQuote(BaseModel):
    event_ticker: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: Category
    contract_count: int = Field(ge=1)
    yes_price_low: str | None = None
    yes_price_high: str | None = None
    volume: str = ""
    open_interest: str = ""
    close_time: str | None = None
    settlement_time: str = Field(min_length=1)
    mutually_exclusive: bool
    collateral_return_type: str | None = None
    settlement_source: str | None = None
    rules_primary: str | None = None
    rules_url: str | None = None
    contracts: list[ContractQuote]


class MarketListResponse(BaseModel):
    events: list[EventQuote]
    pulled_at: datetime
    total: int = Field(ge=0)
    event_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    match_event_count: int = Field(ge=0)
    page: int = Field(ge=1)
    page_count: int = Field(ge=1)
