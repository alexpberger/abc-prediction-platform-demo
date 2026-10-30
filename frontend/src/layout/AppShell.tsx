import { AboutPage } from "../pages/AboutPage";
import { AgenticStrategyPage } from "../pages/AgenticStrategyPage";
import { HomePage } from "../pages/HomePage";
import { MarketDataPage } from "../pages/MarketDataPage";
import { PnlPage } from "../pages/PnlPage";
import styles from "./AppShell.module.css";

export type Section = "home" | "marketData" | "agentic" | "pnl" | "about";

const NAV: { id: Section; label: string }[] = [
  { id: "home", label: "Home" },
  { id: "marketData", label: "Market Data" },
  { id: "agentic", label: "Agentic Proposals" },
  { id: "pnl", label: "Profit & Loss" },
  { id: "about", label: "About" },
];

type AppShellProps = {
  section: Section;
  onNavigate: (section: Section) => void;
  onSignOut: () => void;
};

export function AppShell({ section, onNavigate, onSignOut }: AppShellProps) {
  return (
    <div className={styles.shell}>
      <nav className={styles.nav} aria-label="Sections">
        {NAV.map((item) => {
          const active = section === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={active ? styles.active : undefined}
              aria-current={active ? "page" : undefined}
              onClick={() => onNavigate(item.id)}
            >
              {item.label}
            </button>
          );
        })}
      </nav>
      <div className={styles.main}>
        <header className={styles.header}>
          <p className="section-label">ABC Prediction Platform</p>
          <button type="button" onClick={onSignOut}>
            Sign out
          </button>
        </header>
        {section === "home" ? <HomePage /> : null}
        {section === "marketData" ? <MarketDataPage /> : null}
        {section === "agentic" ? <AgenticStrategyPage /> : null}
        {section === "pnl" ? <PnlPage /> : null}
        {section === "about" ? <AboutPage /> : null}
      </div>
    </div>
  );
}
