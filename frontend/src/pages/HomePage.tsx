import { useEffect } from "react";

import styles from "./section.module.css";

export function HomePage() {
  useEffect(() => {
    document.title = "Home — ABC Prediction Platform";
  }, []);

  return (
    <section className={styles.intro}>
      <h1 className={styles.title}>Home</h1>
      <hr className={styles.accentRule} />
      <div className={styles.copy}>
        <p>This platform proposes paper trades on Kalshi markets.</p>
        <p>Market data is the shared catalog of economics and financials events.</p>
        <p>
          Agentic Proposals is the autonomous agent that proposes one paper
          trade at a time.
        </p>
        <p>
          Profit & Loss is the realized cash result of those paper proposals.
        </p>
        <p>About explains the application purpose and architecture.</p>
      </div>
    </section>
  );
}
