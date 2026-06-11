"""Run the dashboard FastAPI application."""

from __future__ import annotations

import uvicorn

from .api import create_app
from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=settings.dashboard_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
