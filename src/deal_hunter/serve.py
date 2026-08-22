"""Bot / serve entry point — runs the Telegram bot (and optionally the dashboard).

No import side effects at module load; everything happens in main().
"""
from __future__ import annotations

import asyncio
import logging
import sys

import typer

app = typer.Typer(name="deal-hunter-serve", help="Run the Deal Hunter Telegram bot / dashboard.")


@app.command()
def bot(verbose: bool = False) -> None:
    """Run the interactive Telegram bot (polling)."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    from deal_hunter.bot import run_bot
    from deal_hunter.config import AppConfig

    cfg = AppConfig()
    if not cfg.telegram.bot_token:
        print("Telegram bot_token not set in .env — cannot run bot.", file=sys.stderr)
        raise sys.exit(1)

    asyncio.run(run_bot(cfg.telegram.bot_token))


@app.command()
def dash(host: str = "127.0.0.1", port: int = 8001) -> None:
    """Run the dashboard (uvicorn)."""
    import uvicorn

    uvicorn.run("deal_hunter.dashboard.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
