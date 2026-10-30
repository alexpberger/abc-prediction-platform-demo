import { useEffect, useRef, useState } from "react";

import section from "./section.module.css";
import styles from "./PnlPage.module.css";

type Side = "yes" | "no";

type Outcome = "won" | "lost" | "pending" | "open";

type Proposal = {
  ticker: string;
  side: Side;
  confidence: number;
  proposed_at: string | null;
  outcome: Outcome;
  entry_price: string | null;
  kelly_fraction: string | null;
  bankroll: string | null;
  quantity: number | null;
  cost: string | null;
  payout: string | null;
  realized_pnl: string | null;
};

type ReadState = "loading" | "ready" | "error";

export function PnlPage() {
  const [readState, setReadState] = useState<ReadState>("loading");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [realizedTotal, setRealizedTotal] = useState<string | null>(null);
  const [bankroll, setBankroll] = useState<string | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  useEffect(() => {
    document.title = "Profit & Loss — ABC Prediction Platform";
  }, []);

  useEffect(() => {
    const alive = { current: true };
    void loadBook(alive, setReadState, setProposals, setRealizedTotal, setBankroll);
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
      <h1 className={section.title}>Profit & Loss</h1>
      <hr className={section.accentRule} />
      <div className={section.copy}>
        <p>
          Each row is one stored proposal. The entry price is the catalog price
          at the time of that proposal, and the cost is the stake for the
          contracts bought then. No order was sent to Kalshi.
        </p>
      </div>
      <div className={section.toolbar}>
        {proposals.length === 0 ? (
          <p>
            {readState === "loading"
              ? "Loading the paper book."
              : readState === "error"
                ? "The paper book could not be loaded."
                : "No paper proposal has been stored."}
          </p>
        ) : null}
      </div>
      {readState === "ready" ? (
        <p className={section.status}>{bookSummary(proposals, realizedTotal, bankroll)}</p>
      ) : null}
      {proposals.length > 0 ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Contract</th>
                <th scope="col">Side</th>
                <th scope="col">Entry</th>
                <th scope="col">Cost</th>
                <th scope="col">Payout</th>
                <th scope="col">P&L</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
                {proposals.map((proposal, index) => (
                  <tr key={`${proposal.proposed_at ?? "stored"}-${proposal.ticker}-${index}`}>
                    <td className={styles.nowrap}>{formatProposedAt(proposal.proposed_at)}</td>
                    <td>{proposal.ticker}</td>
                    <td>{proposal.side === "yes" ? "Yes" : "No"}</td>
                    <td className={styles.nowrap}>{formatDollars(proposal.entry_price)}</td>
                    <td className={styles.nowrap}>{formatDollars(proposal.cost)}</td>
                    <td className={styles.nowrap}>{formatDollars(proposal.payout)}</td>
                    <td className={styles.nowrap}>{formatDollars(proposal.realized_pnl, true)}</td>
                    <td className={styles.nowrap}>
                      <button
                        className={styles.detailsButton}
                        type="button"
                        aria-label={`Details for ${proposal.ticker}`}
                        onClick={() => setOpenIndex(index)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {openProposal ? <DetailsPanel proposal={openProposal} onClose={() => setOpenIndex(null)} /> : null}
    </section>
  );
}

function DetailsPanel({ proposal, onClose }: { proposal: Proposal; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <aside
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="stake-details-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.panelHeader}>
          <h2 id="stake-details-title" className={styles.panelTitle}>
            Stake
          </h2>
          <button ref={closeRef} type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className={styles.panelSection}>
          <p>{proposal.ticker}</p>
          <p>{proposal.side === "yes" ? "Yes" : "No"}</p>
          {stakeCopy(proposal).map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      </aside>
    </div>
  );
}

function stakeCopy(proposal: Proposal): string[] {
  const entry = formatDollars(proposal.entry_price) || "—";
  const cost = formatDollars(proposal.cost) || "—";
  const quantity = typeof proposal.quantity === "number" ? proposal.quantity : null;
  const kelly = proposal.kelly_fraction ? formatPercent(proposal.kelly_fraction) : null;
  if (kelly && proposal.entry_price && quantity !== null) {
    const bought = quantity === 1 ? "1 contract was bought" : `${quantity} contracts were bought`;
    const cash = formatDollars(proposal.bankroll ?? null);
    const sizing = cash
      ? `Kelly is ${kelly}, and the bankroll was ${cash}, so ${bought} at ${entry}.`
      : `Kelly is ${kelly}. The bankroll at the time was not recorded, and ${bought} at ${entry}.`;
    return [sizing, `The cost is ${cost}. The count is rounded down to a whole contract.`];
  }
  if (proposal.entry_price && quantity !== null) {
    const contracts = quantity === 1 ? "1 contract" : `${quantity} contracts`;
    return [
      `The Kelly fraction was not recorded. The stake is ${contracts} at ${entry}, so the cost is ${cost}.`,
    ];
  }
  return ["The Kelly fraction was not recorded. This row has no entry price."];
}

function formatPercent(value: string | null): string {
  if (value === null || value === "") {
    return "—";
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "—";
  }
  const percent = (parsed * 100).toFixed(2).replace(/\.?0+$/, "");
  return `${percent}%`;
}

function bookSummary(
  proposals: Proposal[],
  realizedTotal: string | null,
  bankroll: string | null,
): string {
  const open = proposals.filter((proposal) => proposal.outcome === "open").length;
  const unpriced = proposals.filter((proposal) => proposal.entry_price === null).length;
  const parts = [
    `Cash left in the $10,000 paper bankroll is ${formatDollars(bankroll) || "—"}.`,
  ];
  if (proposals.length === 0) {
    return parts[0];
  }
  parts.push(
    realizedTotal === null
      ? "No settled paper contract has a price yet."
      : `Realized P&L is ${formatDollars(realizedTotal, true)}.`,
    "Each row is one stored proposal.",
  );
  if (open > 0) {
    parts.push(open === 1 ? "1 is still open." : `${open} are still open.`);
  }
  if (unpriced > 0) {
    parts.push(unpriced === 1 ? "1 has no price." : `${unpriced} have no price.`);
  }
  return parts.join(" ");
}

async function loadBook(
  alive: { current: boolean },
  setReadState: (state: ReadState) => void,
  setProposals: (proposals: Proposal[]) => void,
  setRealizedTotal: (total: string | null) => void,
  setBankroll: (bankroll: string | null) => void,
) {
  try {
    const response = await fetch("/api/proposals");
    if (!response.ok) {
      if (alive.current) {
        setReadState("error");
      }
      return;
    }
    const body = (await response.json()) as {
      proposals?: Proposal[];
      realized_total?: string | null;
      bankroll?: string | null;
    };
    if (!alive.current) {
      return;
    }
    setProposals(body.proposals ?? []);
    setRealizedTotal(body.realized_total ?? null);
    setBankroll(body.bankroll ?? null);
    setReadState("ready");
  } catch {
    if (alive.current) {
      setReadState("error");
    }
  }
}

function formatDollars(value: string | null, signed = false): string {
  if (value === null || value === "") {
    return "";
  }
  const negative = value.startsWith("-");
  const body = negative ? value.slice(1) : value;
  const [whole, fraction = ""] = body.split(".");
  if (!/^\d+$/.test(whole)) {
    return value;
  }
  const scale = `${fraction}0000`.slice(0, 4);
  if (!/^\d{4}$/.test(scale)) {
    return value;
  }
  const shown = scale.endsWith("00") ? `${whole}.${scale.slice(0, 2)}` : `${whole}.${scale}`;
  if (negative) {
    return `-$${shown}`;
  }
  if (signed && Number(whole) + Number(scale) > 0) {
    return `+$${shown}`;
  }
  return `$${shown}`;
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
