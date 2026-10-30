"""In-process paper agent.

The agent lists the events in memory, then reads the contracts of the one
event it chooses. Those tool results are stored with the proposal. It calls
Azure OpenAI through the Responses API and does not send an order to Kalshi.
"""

import os

from pydantic import ValidationError

from app.proposals import (
    ProposalSkipped,
    SearchLog,
    accept_proposal,
    get_event_contracts as catalog_contracts,
    list_events as catalog_events,
    omit_proposed_contracts,
)
from app.schemas.proposals import AgentChoice, ProposalDraft, ProposalRun, ProposalTrace

_INSTRUCTIONS = (
    "You propose one paper trade. Call list_events first and choose one event. "
    "Then call get_event_contracts with that event ticker and choose exactly one "
    "contract from its response. A contract that already has a stored proposal "
    "is omitted. Use only tickers those tools returned. "
    "Return the event ticker, the contract ticker, a side of yes or no, "
    "a short hypothesis, and one sentence on why you chose that event. "
    "Confidence is your probability, from 0 to 1, that the side you choose wins. "
    "The server stores the trade only when that probability is above the price of that side."
)


class AgentNotConfigured(Exception):
    """The process has no Azure OpenAI endpoint or deployment name."""


class AgentResponseError(Exception):
    """The model did not return a proposal."""


async def propose() -> ProposalRun:
    """Ask the model for one draft and store it when it has an edge the bankroll can buy."""
    draft, trace = await ask_model()
    try:
        stored = accept_proposal(draft, trace)
    except ProposalSkipped as exc:
        return ProposalRun(skip=exc.reason)
    return ProposalRun(proposal=stored)


async def ask_model() -> tuple[ProposalDraft, ProposalTrace]:
    """Run one Responses API call. Tests replace this with a fake draft and trace."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    model = os.environ.get("AZURE_OPENAI_CHAT_MODEL", "").strip()
    if not endpoint or not model:
        raise AgentNotConfigured

    from agent_framework import tool
    from agent_framework.openai import OpenAIChatClient

    log = SearchLog()

    @tool
    def list_events() -> list[dict[str, object]]:
        """List open events. Each row is one event, not a contract."""
        rows = catalog_events()
        log.record_events(rows)
        return rows

    @tool
    def get_event_contracts(event_ticker: str) -> list[dict[str, object]]:
        """Return the contracts for one event ticker from list_events."""
        rows = omit_proposed_contracts(catalog_contracts(event_ticker))
        log.record_contracts(event_ticker, rows)
        return rows

    credential = _azure_credential()
    try:
        agent = OpenAIChatClient(
            model=model,
            azure_endpoint=endpoint,
            credential=credential,
        ).as_agent(
            name="PaperProposal",
            instructions=_INSTRUCTIONS,
            tools=[list_events, get_event_contracts],
        )
        result = await agent.run(
            "Propose one paper trade from the current events.",
            options={"response_format": AgentChoice},
        )
    finally:
        await credential.close()
    choice = _choice(result)
    return choice, log.finish(choice.event_reason)


def _azure_credential():
    """Use the job identity when Azure sets a client id, otherwise the CLI."""
    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    if client_id:
        from azure.identity.aio import ManagedIdentityCredential

        return ManagedIdentityCredential(client_id=client_id)
    from azure.identity.aio import AzureCliCredential

    return AzureCliCredential()


def _choice(result: object) -> AgentChoice:
    value = getattr(result, "value", None)
    if isinstance(value, AgentChoice):
        return value
    if isinstance(value, dict):
        try:
            return AgentChoice.model_validate(value)
        except ValidationError as exc:
            raise AgentResponseError("The model did not return a proposal.") from exc
    raise AgentResponseError("The model did not return a proposal.")
