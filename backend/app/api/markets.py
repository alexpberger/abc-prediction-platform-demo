"""Catalog route over the stored market snapshot."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.market_data import MarketDataUnavailable, query_catalog
from app.schemas.markets import Category, MarketListResponse, ResolvesWithin

router = APIRouter()


@router.get("/markets", response_model=MarketListResponse)
def list_markets(
    category: Annotated[Category | None, Query()] = None,
    resolves_within: Annotated[ResolvesWithin, Query()] = "3d",
    page: Annotated[int, Query(ge=1)] = 1,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> MarketListResponse:
    """Return one page of the economic and financial catalog."""
    try:
        return query_catalog(
            category=category,
            resolves_within=resolves_within,
            page=page,
            q=q,
        )
    except MarketDataUnavailable:
        raise HTTPException(
            status_code=502,
            detail="Market data is unavailable.",
        ) from None
