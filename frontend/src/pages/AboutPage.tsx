import { useEffect } from "react";

import styles from "./section.module.css";

export function AboutPage() {
  useEffect(() => {
    document.title = "About — ABC Prediction Platform";
  }, []);

  return (
    <section className={styles.intro}>
      <h1 className={styles.title}>About</h1>
      <hr className={styles.accentRule} />
      <div className={styles.copy}>
        <p>
          The purpose of this application is to demonstrate a sound way to
          build a modern data application. The focus is on the application
          architecture, engineering practices, and deployment workflow rather
          than on developing the perfect trading model.
        </p>
        <p>
          One Docker image holds this application, running in Azure as a
          Container App. The page is built with React and TypeScript, and
          the API with Python and FastAPI.
        </p>
        <p>
          Market data comes from Kalshi's public API: economics and financials
          events, with no API key. The agent proposes one paper trade at a
          time. It calls Azure OpenAI through the Microsoft Agent Framework
          (MAF).
        </p>
        <p>
          Terraform describes the Azure resources. GitHub Actions tests the
          code and builds the image. A separate run from main deploys that
          image to staging.
        </p>
        <p>
          The application is arranged for three environments. Local runs in the
          dev container. Staging is the Azure site used to try a change.
          Production is a later copy of the same stack.
        </p>
        <p>
          Together, these choices demonstrate a practical approach to building
          a modern data application: a typed interface, an API, infrastructure
          as code, automated testing, and staging before production.
        </p>
        <p>
          The source code can be found at{" "}
          <a href="https://github.com/alexpberger/abc-prediction-platform-demo">
            https://github.com/alexpberger/abc-prediction-platform-demo
          </a>.
        </p>
      </div>
    </section>
  );
}
