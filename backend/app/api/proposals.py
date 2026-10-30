"""Manual trigger for one paper proposal."""

from fastapi import APIRouter, HTTPException

from app.agent import AgentNotConfigured, AgentResponseError, propose
from app.market_data import MarketDataUnavailable
from app.proposals import (
    ProposalAlreadyStored,
    ProposalRejected,
    ProposalSearchRejected,
    ProposalStoreError,
    proposal_view,
    proposal_views,
    refresh_outcomes,
)
from app.schemas.proposals import ProposalRunView, ProposalViewList

router = APIRouter()


@router.get("/proposals", response_model=ProposalViewList)
def get_proposals() -> ProposalViewList:
    """Return stored paper proposals, filling a Kalshi result when one is published."""
    try:
        proposals = refresh_outcomes()
    except ProposalStoreError:
        raise HTTPException(
            status_code=500,
            detail="The proposal file cannot be read.",
        ) from None
    return proposal_views(proposals)


@router.post("/proposals", response_model=ProposalRunView)
async def create_proposal() -> ProposalRunView:
    """Ask the local agent for one paper proposal and store it when it has an edge."""
    try:
        run = await propose()
    except MarketDataUnavailable:
        raise HTTPException(
            status_code=502,
            detail="Market data is unavailable.",
        ) from None
    except ProposalAlreadyStored as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ProposalSearchRejected:
        raise HTTPException(
            status_code=422,
            detail="The proposal has no recorded search of a future contract.",
        ) from None
    except ProposalRejected:
        raise HTTPException(
            status_code=422,
            detail="The proposal does not match a contract on that event.",
        ) from None
    except AgentNotConfigured:
        raise HTTPException(
            status_code=503,
            detail="Azure OpenAI is not configured.",
        ) from None
    except AgentResponseError:
        raise HTTPException(
            status_code=502,
            detail="The model did not return a proposal.",
        ) from None
    except ProposalStoreError:
        raise HTTPException(
            status_code=500,
            detail="The proposal file cannot be written.",
        ) from None
    if run.proposal is None:
        return ProposalRunView(skip=run.skip)
    return ProposalRunView(proposal=proposal_view(run.proposal))
