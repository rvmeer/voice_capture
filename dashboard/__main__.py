"""Run the dashboard FastAPI application."""

from __future__ import annotations

import logging

import uvicorn

from .api import create_app
from .config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("dashboard").setLevel(logging.INFO)
    settings = get_settings()
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=settings.dashboard_port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
