import { useEffect, useRef, useState } from "react";

import styles from "./MarketDataPage.module.css";

type Category = "" | "Economics" | "Financials";
type ResolvesWithin = "24h" | "3d";

type ContractQuote = {
  ticker: string;
  strike_label: string | null;
  strike_type: string | null;
  floor_strike: string | null;
  cap_strike: string | null;
  yes_price: string | null;
  volume: string;
  open_interest: string;
  status: string;
  close_time: string | null;
  rules_primary: string | null;
};

type EventQuote = {
  event_ticker: string;
  title: string;
  category: "Economics" | "Financials";
  contract_count: number;
  yes_price_low: string | null;
  yes_price_high: string | null;
  volume: string;
  open_interest: string;
  close_time: string | null;
  settlement_time: string;
  mutually_exclusive: boolean;
  collateral_return_type: string | null;
  settlement_source: string | null;
  rules_url: string | null;
  rules_primary: string | null;
  contracts: ContractQuote[];
};

type MarketList = {
  events: EventQuote[];
  pulled_at: string;
  total: number;
  event_count: number;
  match_count: number;
  match_event_count: number;
  page: number;
  page_count: number;
};

type Phase = "loading" | "ready" | "error";

export function MarketDataPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [catalog, setCatalog] = useState<MarketList | null>(null);
  const [category, setCategory] = useState<Category>("");
  const [resolvesWithin, setResolvesWithin] = useState<ResolvesWithin>("3d");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [openEvents, setOpenEvents] = useState<string[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const queryRef = useRef("");

  useEffect(() => {
    document.title = "Market Data — ABC Prediction Platform";
    const handle = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      window.clearInterval(handle);
    };
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const next = search.trim();
      if (queryRef.current === next) {
        return;
      }
      queryRef.current = next;
      setQuery(next);
      setPage(1);
    }, 250);
    return () => window.clearTimeout(handle);
  }, [search]);

  useEffect(() => {
    let cancelled = false;

    async function loadPage() {
      setPhase("loading");
      try {
        const next = await fetchMarkets({ category, resolvesWithin, query, page });
        if (cancelled) {
          return;
        }
        setCatalog(next);
        setPhase("ready");
      } catch {
        if (!cancelled) {
          setPhase("error");
        }
      }
    }

    void loadPage();
    return () => {
      cancelled = true;
    };
  }, [category, resolvesWithin, query, page]);

  useEffect(() => {
    setOpenEvents([]);
  }, [category, resolvesWithin, query, page]);

  function toggleEvent(eventTicker: string) {
    setOpenEvents((current) =>
      current.includes(eventTicker)
        ? current.filter((ticker) => ticker !== eventTicker)
        : [...current, eventTicker],
    );
  }

  const ready = phase === "ready" && catalog !== null;
  const filtered = category !== "" || resolvesWithin !== "3d" || query !== "";

  return (
    <div>
      <section className={styles.intro}>
        <h1 className={styles.title}>Market Data</h1>
        <hr className={styles.accentRule} />
        <p className={styles.status}>
          Economics and financials events that resolve within 3 days and
          mention USD in the question. Fifteen-minute contracts are omitted.
          Open an event to see its contracts. The catalog is a twice-daily
          snapshot (06:00 / 18:00 EDT). It is held in memory and uses no API
          key.
        </p>
        <p className={styles.now}>Current time {formatNow(now)}.</p>
      </section>
      <div className={styles.filters}>
        <label className={styles.search}>
          Search
          <input
            type="search"
            value={search}
            maxLength={200}
            autoComplete="off"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <label>
          Category
          <select
            value={category}
            onChange={(event) => {
              setCategory(event.target.value as Category);
              setPage(1);
            }}
          >
            <option value="">All</option>
            <option value="Economics">Economics</option>
            <option value="Financials">Financials</option>
          </select>
        </label>
        <label>
          Resolves
          <select
            value={resolvesWithin}
            onChange={(event) => {
              setResolvesWithin(event.target.value as ResolvesWithin);
              setPage(1);
            }}
          >
            <option value="3d">Within 3 days</option>
            <option value="24h">Within 24 hours</option>
          </select>
        </label>
      </div>
      {phase === "loading" ? (
        <p className={styles.state}>Loading market data.</p>
      ) : null}
      {phase === "error" || ready ? (
        <div className={styles.summaryRow}>
          {phase === "error" || catalog === null ? (
            <p className={styles.state}>Market data is unavailable.</p>
          ) : (
            <p className={styles.summary}>
              Last pulled {formatPulledAt(catalog.pulled_at)}.{" "}
              {formatTotal(catalog.total, catalog.event_count)}
              {filtered
                ? ` ${formatMatch(catalog.match_count, catalog.match_event_count)}`
                : ""}
            </p>
          )}
        </div>
      ) : null}
      {ready && catalog.match_count === 0 ? (
        <p className={styles.state}>
          {catalog.total === 0
            ? "No contracts are in the catalog."
            : "No contracts match these filters."}
        </p>
      ) : null}
      {ready && catalog.events.length > 0 ? (
        <div className={styles.eventList}>
          {catalog.events.map((event) => {
            const open = openEvents.includes(event.event_ticker);
            return (
              <article className={styles.event} key={event.event_ticker}>
                <div className={styles.eventHeader}>
                  <button
                    type="button"
                    className={styles.eventToggle}
                    aria-expanded={open}
                    onClick={() => toggleEvent(event.event_ticker)}
                  >
                    <span>
                      <span className={styles.fieldLabel}>Event</span>
                      <span className={styles.eventTitle}>{event.title}</span>
                    </span>
                    <span>
                      <span className={styles.fieldLabel}>Category</span>
                      {event.category}
                    </span>
                    <span>
                      <span className={styles.fieldLabel}>Contracts</span>
                      {formatContractCount(event.contract_count)}
                    </span>
                    <span>
                      <span className={styles.fieldLabel}>YES price</span>
                      {formatPriceRange(event.yes_price_low, event.yes_price_high)}
                    </span>
                    <span>
                      <span className={styles.fieldLabel}>Volume</span>
                      {formatCount(event.volume)}
                    </span>
                    <span>
                      <span className={styles.fieldLabel}>Time to close</span>
                      <span className={styles.nowrap}>
                        {formatTimeToClose(event.close_time, now)}
                      </span>
                    </span>
                    <span>
                      <span className={styles.fieldLabel}>Close</span>
                      {formatDate(event.close_time)}
                    </span>
                    <span className={styles.disclosure}>
                      {open ? "Hide contracts" : "Show contracts"}
                    </span>
                  </button>
                  {event.rules_url ? (
                    <a
                      className={styles.rules}
                      href={event.rules_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Rules
                    </a>
                  ) : null}
                </div>
                {open ? (
                  <>
                    {event.rules_primary ? (
                      <p className={styles.explanation}>{event.rules_primary}</p>
                    ) : null}
                    <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th scope="col">Strike</th>
                          <th scope="col">YES price</th>
                          <th scope="col">Implied %</th>
                          <th scope="col">Volume</th>
                          <th scope="col">Close</th>
                        </tr>
                      </thead>
                      <tbody>
                        {event.contracts.map((contract) => (
                          <tr key={contract.ticker}>
                            <td>
                              <span>{formatStrike(contract)}</span>
                              {contract.rules_primary &&
                              contract.rules_primary !== event.rules_primary ? (
                                <span className={styles.strikeExplanation}>
                                  {contract.rules_primary}
                                </span>
                              ) : null}
                            </td>
                            <td>{formatCents(contract.yes_price)}</td>
                            <td>{formatPercent(contract.yes_price)}</td>
                            <td>{formatCount(contract.volume)}</td>
                            <td className={styles.nowrap}>{formatDate(contract.close_time)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    </div>
                  </>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
      {ready ? (
        <div className={styles.more}>
          <button
            type="button"
            onClick={() => setPage((current) => current - 1)}
            disabled={page <= 1}
          >
            Previous
          </button>
          <p>
            Page {catalog.page} of {catalog.page_count}
          </p>
          <button
            type="button"
            onClick={() => setPage((current) => current + 1)}
            disabled={page >= catalog.page_count}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}

async function fetchMarkets(filters: {
  category: Category;
  resolvesWithin: ResolvesWithin;
  query: string;
  page: number;
}): Promise<MarketList> {
  const params = new URLSearchParams();
  if (filters.category) {
    params.set("category", filters.category);
  }
  if (filters.query) {
    params.set("q", filters.query);
  }
  params.set("resolves_within", filters.resolvesWithin);
  params.set("page", String(filters.page));
  const response = await fetch(`/api/markets?${params}`);
  if (!response.ok) {
    throw new Error("Market data is unavailable.");
  }
  const body: unknown = await response.json();
  if (!isMarketList(body)) {
    throw new Error("Market data is unavailable.");
  }
  return body;
}

function isMarketList(value: unknown): value is MarketList {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const body = value as MarketList;
  return (
    Array.isArray(body.events) &&
    body.events.every(isEventQuote) &&
    typeof body.pulled_at === "string" &&
    typeof body.total === "number" &&
    typeof body.event_count === "number" &&
    typeof body.match_count === "number" &&
    typeof body.match_event_count === "number" &&
    typeof body.page === "number" &&
    typeof body.page_count === "number"
  );
}

function isEventQuote(value: unknown): value is EventQuote {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const event = value as EventQuote;
  return (
    typeof event.event_ticker === "string" &&
    typeof event.title === "string" &&
    (event.category === "Economics" || event.category === "Financials") &&
    typeof event.contract_count === "number" &&
    (event.yes_price_low === null || typeof event.yes_price_low === "string") &&
    (event.yes_price_high === null || typeof event.yes_price_high === "string") &&
    typeof event.volume === "string" &&
    (event.close_time === null || typeof event.close_time === "string") &&
    typeof event.settlement_time === "string" &&
    (event.rules_url === null || typeof event.rules_url === "string") &&
    (event.rules_primary === null || typeof event.rules_primary === "string") &&
    Array.isArray(event.contracts) &&
    event.contracts.every(isContractQuote)
  );
}

function isContractQuote(value: unknown): value is ContractQuote {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const contract = value as ContractQuote;
  return (
    typeof contract.ticker === "string" &&
    (contract.strike_label === null || typeof contract.strike_label === "string") &&
    (contract.yes_price === null || typeof contract.yes_price === "string") &&
    typeof contract.volume === "string" &&
    (contract.close_time === null || typeof contract.close_time === "string") &&
    (contract.rules_primary === null || typeof contract.rules_primary === "string")
  );
}

function formatTotal(total: number, eventCount: number): string {
  const contracts = total === 1 ? "1 contract" : `${total} contracts`;
  const events = eventCount === 1 ? "1 event" : `${eventCount} events`;
  return `${contracts} in the catalog, covering ${events}.`;
}

function formatMatch(count: number, eventCount: number): string {
  if (count === 0) {
    return "None match these filters.";
  }
  const contracts = count === 1 ? "1 contract matches" : `${count} contracts match`;
  const events = eventCount === 1 ? "1 event" : `${eventCount} events`;
  return `${contracts} these filters, in ${events}.`;
}

function formatContractCount(count: number): string {
  return count === 1 ? "1 contract" : `${count} contracts`;
}

function formatPriceRange(low: string | null, high: string | null): string {
  const lowText = formatCents(low);
  const highText = formatCents(high);
  if (lowText === "—" && highText === "—") {
    return "—";
  }
  if (lowText === highText) {
    return lowText;
  }
  return `${lowText}–${highText}`;
}

function formatStrike(contract: ContractQuote): string {
  const label = contract.strike_label?.trim();
  if (label) {
    return label;
  }
  const floor = contract.floor_strike?.trim();
  const cap = contract.cap_strike?.trim();
  if (floor && cap) {
    return `${floor}–${cap}`;
  }
  return floor || cap || "—";
}

function formatCents(dollars: string | null): string {
  if (dollars === null || dollars === "") {
    return "—";
  }
  const value = Number(dollars);
  if (!Number.isFinite(value)) {
    return dollars;
  }
  const cents = (value * 100).toFixed(2).replace(/\.?0+$/, "");
  return `${cents}¢`;
}

function formatPercent(dollars: string | null): string {
  if (dollars === null || dollars === "") {
    return "—";
  }
  const value = Number(dollars);
  if (!Number.isFinite(value)) {
    return "—";
  }
  const percent = (value * 100).toFixed(2).replace(/\.?0+$/, "");
  return `${percent}%`;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  return formatWhen(value);
}

function formatTimeToClose(value: string | null, now: number): string {
  if (!value) {
    return "—";
  }
  const close = new Date(value);
  if (Number.isNaN(close.getTime())) {
    return "—";
  }
  const remaining = close.getTime() - now;
  if (remaining <= 0) {
    return "Closed";
  }
  const totalMinutes = Math.floor(remaining / 60_000);
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) {
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  if (minutes > 0) {
    return `${minutes}m`;
  }
  return "<1m";
}

function formatCount(value: string): string {
  if (!value.trim()) {
    return "—";
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return value;
  }
  return parsed.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Kalshi market clocks use US Eastern (EDT/EST). */
const EASTERN = "America/New_York";

function formatPulledAt(value: string): string {
  return formatWhen(value);
}

function formatNow(now: number): string {
  return formatWhen(new Date(now).toISOString());
}

function formatWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  // dateStyle/timeStyle cannot be combined with timeZoneName in all runtimes.
  // en-US yields EDT/EST; en-GB often falls back to GMT±N.
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
