"""One catalog pull and one paper proposal.

The staging job runs this at 06:00 and 18:00 US Eastern. It does not start
the web server or the website's refresh loop. The catalog file it writes is
what the website loads on startup.
"""

import asyncio
import sys

import httpx

from app.agent import propose
from app.market_data import refresh_catalog


def main() -> None:
    """Pull the catalog, then store one proposal. A failure writes nothing."""
    try:
        with httpx.Client() as client:
            refresh_catalog(client)
        run = asyncio.run(propose())
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        print(message, file=sys.stderr)
        raise SystemExit(1) from exc
    if run.skip == "edge":
        print("No paper proposal was stored. Confidence did not beat the market price.")
    elif run.skip == "size":
        print("No paper proposal was stored. The Kelly stake is below one contract.")


if __name__ == "__main__":
    main()
