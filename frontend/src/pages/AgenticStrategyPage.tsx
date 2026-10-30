import { useEffect, useRef, useState } from "react";

import section from "./section.module.css";
import styles from "./AgenticStrategyPage.module.css";

type Side = "yes" | "no";

type Outcome = "won" | "lost" | "pending" | "open";

type TraceEvent = {
  event_ticker: string;
  title: string;
  category: string;
  contract_count: number;
  yes_price_low: string | null;
  yes_price_high: string | null;
  settlement_time: string;
};

type TraceContract = {
  ticker: string;
  strike_label: string | null;
  yes_price: string | null;
  settlement_time: string;
};

type TraceOpening = {
  event_ticker: string;
  contracts: TraceContract[];
};

type ProposalTrace = {
  searched_at: string;
  catalog_pulled_at: string;
  events: TraceEvent[];
  calls: { name: string; event_ticker?: string | null }[];
  opened: TraceOpening[];
  event_reason: string;
};

type Proposal = {
  event_ticker: string;
  ticker: string;
  side: Side;
  hypothesis: string;
  confidence: number;
  entry_price: string | null;
  kelly_fraction: string | null;
  proposed_at: string | null;
  settlement_time: string | null;
  outcome: Outcome;
  trace: ProposalTrace | null;
};

type ReadState = "loading" | "ready" | "error";

export function AgenticStrategyPage() {
  const [readState, setReadState] = useState<ReadState>("loading");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    document.title = "Agentic Proposals — ABC Prediction Platform";
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const alive = { current: true };
    void loadProposals(alive, setReadState, setProposals);
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (openIndex === null) {
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenIndex(null);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [openIndex]);

  const openProposal = openIndex === null ? null : proposals[openIndex] ?? null;

  return (
    <section className={section.intro}>
      <h1 className={section.title}>Agentic Proposals</h1>
      <hr className={section.accentRule} />
      <div className={section.copy}>
        <p>
          The agent lists the open events, chooses one, reads that event's
          contracts, and proposes one paper trade. Choosing the event and the
          contract is what makes the run agentic.
        </p>
        <p>
          Boundaries: one proposal per run, a contract from the event it read,
          not a contract already in this table, and no order sent to Kalshi.
        </p>
        <p>
          Each row is a paper proposal, with the time it was made. The agent
          does not place an order. Market is the catalog price of the proposed
          side, shown as a percent. A proposal is stored only when confidence is
          above that price. Kelly is the fraction of the paper bankroll staked.
          The trace shows that calculation.
        </p>
      </div>
      {proposals.length === 0 ? (
        <div className={section.toolbar}>
          <p>
            {readState === "loading"
              ? "Loading the latest proposal."
              : readState === "error"
                ? "The proposals could not be loaded."
                : "No paper proposal has been stored."}
          </p>
        </div>
      ) : null}
      {proposals.length > 0 ? (
        <>
          <p className={section.status}>{outcomeSummary(proposals)}</p>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Contract</th>
                  <th scope="col">Event</th>
                  <th scope="col">Side</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Market</th>
                  <th scope="col">Kelly</th>
                  <th scope="col">Hypothesis</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Settles in</th>
                  <th scope="col">Trace</th>
                </tr>
              </thead>
              <tbody>
                {proposals.map((proposal, index) => (
                  <tr key={`${proposal.proposed_at ?? "stored"}-${proposal.ticker}-${index}`}>
                    <td className={styles.nowrap}>{formatProposedAt(proposal.proposed_at)}</td>
                    <td>{proposal.ticker}</td>
                    <td>{proposal.event_ticker}</td>
                    <td>{proposal.side === "yes" ? "Yes" : "No"}</td>
                    <td>{Math.round(proposal.confidence * 100)}%</td>
                    <td className={styles.nowrap}>{formatPercent(proposal.entry_price)}</td>
                    <td className={styles.nowrap}>{formatPercent(proposal.kelly_fraction)}</td>
                    <td>{proposal.hypothesis}</td>
                    <td>{outcomeLabel(proposal.outcome)}</td>
                    <td className={styles.nowrap}>{timeToSettlement(proposal, now)}</td>
                    <td className={styles.nowrap}>
                      {proposal.trace ? (
                        <button
                          className={styles.traceButton}
                          type="button"
                          aria-label={`Trace for ${proposal.ticker}`}
                          onClick={() => setOpenIndex(index)}
                        >
                          Trace
                        </button>
                      ) : (
                        <span className={styles.notRecorded}>Not recorded</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
      {openProposal?.trace ? (
        <TracePanel proposal={openProposal} onClose={() => setOpenIndex(null)} />
      ) : null}
    </section>
  );
}

function TracePanel({ proposal, onClose }: { proposal: Proposal; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const trace = proposal.trace;
  useEffect(() => {
    closeRef.current?.focus();
  }, []);
  if (!trace) {
    return null;
  }

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <aside
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="proposal-trace-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.panelHeader}>
          <h2 id="proposal-trace-title" className={styles.panelTitle}>
            Search trace
          </h2>
          <button ref={closeRef} type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className={styles.panelSection}>
          <p>Search {formatProposedAt(trace.searched_at)}</p>
          <p>Catalog snapshot {formatProposedAt(trace.catalog_pulled_at)}</p>
          <p>
            Open economics and financials events that settle after this search and within 3
            days.
          </p>
        </div>
        <div className={styles.panelSection}>
          <h3>Events offered</h3>
          <p>{futureEventCount(trace)}</p>
          <div className={styles.panelTableWrap}>
            <table className={styles.panelTable}>
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Title</th>
                  <th scope="col">Category</th>
                  <th scope="col">Settles</th>
                  <th scope="col">Yes</th>
                </tr>
              </thead>
              <tbody>
                {trace.events.map((event) => {
                  const chosen = event.event_ticker === proposal.event_ticker;
                  return (
                    <tr key={event.event_ticker} className={chosen ? styles.marked : undefined}>
                      <td>
                        {event.event_ticker}
                        {chosen ? <span className={styles.chosen}>Chosen</span> : null}
                      </td>
                      <td>{event.title}</td>
                      <td>{event.category}</td>
                      <td className={styles.nowrap}>{formatProposedAt(event.settlement_time)}</td>
                      <td className={styles.nowrap}>{priceRange(event)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        <div className={styles.panelSection}>
          <h3>Why this event</h3>
          <p>{trace.event_reason}</p>
        </div>
        <div className={styles.panelSection}>
          <h3>Contracts read</h3>
          {trace.opened.map((opening, index) => (
            <div key={`${opening.event_ticker}-${index}`} className={styles.opening}>
              <p>{opening.event_ticker}</p>
              <div className={styles.panelTableWrap}>
                <table className={styles.panelTable}>
                  <thead>
                    <tr>
                      <th scope="col">Contract</th>
                      <th scope="col">Strike</th>
                      <th scope="col">Yes</th>
                      <th scope="col">Settles</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opening.contracts.map((contract) => {
                      const chosen =
                        opening.event_ticker === proposal.event_ticker &&
                        contract.ticker === proposal.ticker;
                      return (
                        <tr key={contract.ticker} className={chosen ? styles.marked : undefined}>
                          <td>
                            {contract.ticker}
                            {chosen ? (
                              <span className={styles.chosen}>
                                Chosen, {proposal.side === "yes" ? "Yes" : "No"}
                              </span>
                            ) : null}
                          </td>
                          <td>{contract.strike_label ?? "—"}</td>
                          <td className={styles.nowrap}>{contract.yes_price ?? "—"}</td>
                          <td className={styles.nowrap}>
                            {formatProposedAt(contract.settlement_time)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
        <div className={styles.panelSection}>
          <h3>Hypothesis</h3>
          <p>{proposal.hypothesis}</p>
        </div>
        <div className={styles.panelSection}>
          <h3>Kelly</h3>
          {kellyCopy(proposal).map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
        <div className={styles.panelSection}>
          <h3>Acceptance</h3>
          <p>
            {searchAccepted(proposal)
              ? "The chosen contract was among the contracts read for that event, and it settles after the search."
              : "The recorded search does not show that future contract."}
          </p>
        </div>
      </aside>
    </div>
  );
}

function futureEventCount(trace: ProposalTrace): string {
  const searched = Date.parse(trace.searched_at);
  const future = trace.events.filter((event) => Date.parse(event.settlement_time) > searched).length;
  const total = trace.events.length;
  if (future === total) {
    return future === 1
      ? "1 event settles after the search."
      : `${future} events settle after the search.`;
  }
  const verb = future === 1 ? "settles" : "settle";
  return `${future} of ${total} events ${verb} after the search.`;
}

function kellyCopy(proposal: Proposal): string[] {
  if (proposal.kelly_fraction && proposal.entry_price) {
    const confidence = plainNumber(proposal.confidence);
    const price = plainNumber(proposal.entry_price);
    const kelly = plainNumber(proposal.kelly_fraction);
    return [
      `Confidence is ${Math.round(proposal.confidence * 100)}%. The price of the chosen side is ${price}.`,
      `Kelly is (confidence − entry) / (1 − entry), which is (${confidence} − ${price}) / (1 − ${price}) = ${kelly}.`,
      `That is ${formatPercent(proposal.kelly_fraction)} of the paper bankroll.`,
    ];
  }
  if (proposal.kelly_fraction) {
    return [
      `Kelly is ${formatPercent(proposal.kelly_fraction)} of the paper bankroll. The price used in that calculation was not recorded.`,
    ];
  }
  return ["The Kelly fraction was not recorded."];
}

function plainNumber(value: number | string): string {
  const text = typeof value === "number" ? String(value) : value.trim();
  if (!/^\d+(\.\d+)?$/.test(text)) {
    return text;
  }
  return text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

function formatPercent(price: string | null): string {
  if (price === null || price === "") {
    return "—";
  }
  const value = Number(price);
  if (!Number.isFinite(value)) {
    return "—";
  }
  const percent = (value * 100).toFixed(2).replace(/\.?0+$/, "");
  return `${percent}%`;
}

function priceRange(event: TraceEvent): string {
  const low = event.yes_price_low;
  const high = event.yes_price_high;
  if (low && high) {
    return low === high ? low : `${low}–${high}`;
  }
  return low ?? high ?? "—";
}

function searchAccepted(proposal: Proposal): boolean {
  const trace = proposal.trace;
  if (!trace) {
    return false;
  }
  const searched = Date.parse(trace.searched_at);
  const openings = trace.opened.filter((opening) => opening.event_ticker === proposal.event_ticker);
  const opening = openings[openings.length - 1];
  if (!opening) {
    return false;
  }
  const contract = opening.contracts.find((item) => item.ticker === proposal.ticker);
  if (!contract) {
    return false;
  }
  return Date.parse(contract.settlement_time) > searched;
}

function timeToSettlement(proposal: Proposal, now: number): string {
  if (proposal.outcome !== "open") {
    return "";
  }
  if (!proposal.settlement_time) {
    return "—";
  }
  const settles = Date.parse(proposal.settlement_time);
  if (Number.isNaN(settles)) {
    return "—";
  }
  return formatRemaining(settles - now);
}

function formatRemaining(ms: number): string {
  if (ms < 60_000) {
    return ms > 0 ? "<1m" : "0m";
  }
  const totalMinutes = Math.floor(ms / 60_000);
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) {
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  return `${minutes}m`;
}

function outcomeLabel(outcome: Outcome): string {
  if (outcome === "won") {
    return "Won";
  }
  if (outcome === "lost") {
    return "Lost";
  }
  if (outcome === "pending") {
    return "Pending";
  }
  return "Open";
}

function outcomeSummary(proposals: Proposal[]): string {
  const counts: Record<Outcome, number> = { won: 0, lost: 0, open: 0, pending: 0 };
  for (const proposal of proposals) {
    counts[proposal.outcome] += 1;
  }
  return (["won", "lost", "open", "pending"] as const)
    .filter((outcome) => counts[outcome] > 0)
    .map((outcome) => `${counts[outcome]} ${outcome}`)
    .join(", ");
}

async function loadProposals(
  alive: { current: boolean },
  setReadState: (state: ReadState) => void,
  setProposals: (proposals: Proposal[]) => void,
) {
  try {
    const response = await fetch("/api/proposals");
    if (!response.ok) {
      if (alive.current) {
        setReadState("error");
      }
      return;
    }
    const body = (await response.json()) as { proposals?: Proposal[] };
    if (!alive.current) {
      return;
    }
    setProposals(body.proposals ?? []);
    setReadState("ready");
  } catch {
    if (alive.current) {
      setReadState("error");
    }
  }
}

/** Kalshi market clocks use US Eastern (EDT/EST). */
const EASTERN = "America/New_York";

function formatProposedAt(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    timeZone: EASTERN,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(date);
}
