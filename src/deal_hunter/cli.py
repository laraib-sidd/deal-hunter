"""Deal Hunter CLI — second-hand hardware deal finder for India."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from deal_hunter.analysis.normalizer import HardwareNormalizer
from deal_hunter.analysis.schemas import DealAnalysis
from deal_hunter.analysis.scorer import analyze_deal, analyze_deal_async

app = typer.Typer(
    name="deal-hunter",
    help="Second-hand hardware deal finder for India.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)

# Verdict -> color mapping
_VERDICT_COLORS = {
    "BUY": "bold green",
    "NEGOTIATE": "bold yellow",
    "PASS": "bold red",
    "SCAM_RISK": "bold red on white",
}

# Severity -> color
_SEVERITY_COLORS = {
    "low": "dim",
    "medium": "yellow",
    "high": "bold red",
    "critical": "bold white on red",
}


def _listing_to_analysis(listing) -> DealAnalysis | None:
    """Reconstruct a display analysis from persisted listing fields."""
    from deal_hunter.analysis.schemas import RedFlag
    from deal_hunter.db.models import Listing

    if not isinstance(listing, Listing) or listing.deal_score is None or listing.price is None:
        return None
    red_flags: list[RedFlag] = []
    if listing.red_flags_json:
        try:
            red_flags = [RedFlag(**flag) for flag in json.loads(listing.red_flags_json)]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return DealAnalysis(
        canonical_name=listing.canonical_name or listing.title,
        category=listing.category,
        brand="",
        asking_price=int(listing.price),
        fair_market_low=0,
        fair_market_high=0,
        fair_market_mid=0,
        msrp=0,
        deal_score=int(listing.deal_score),
        verdict=listing.deal_verdict or "PASS",
        reasoning=listing.deal_reason or "",
        red_flags=red_flags,
        confidence=0.5,
    )


def _get_scored_listings(engine, min_score: int, limit: int) -> list:
    from sqlmodel import Session, col, select

    from deal_hunter.db.models import Listing

    with Session(engine) as session:
        stmt = (
            select(Listing)
            .where(Listing.deal_score.is_not(None), Listing.deal_score >= min_score)  # type: ignore[union-attr]
            .order_by(col(Listing.deal_score).desc())
            .limit(limit)
        )
        return list(session.exec(stmt).all())


def _listing_id(listing) -> int | None:
    from sqlalchemy import inspect as sa_inspect

    identity = sa_inspect(listing).identity
    if not identity:
        return None
    return int(identity[0])


def _listings_to_score(engine, ingest_result) -> list:
    from sqlmodel import Session, select

    from deal_hunter.db.models import Listing

    listing_ids: list[int] = []
    seen_ids: set[int] = set()
    for listing in list(ingest_result.fresh) + [row for row, _, _ in ingest_result.price_drops]:
        listing_id = _listing_id(listing)
        if listing_id is not None and listing_id not in seen_ids:
            listing_ids.append(listing_id)
            seen_ids.add(listing_id)

    if not listing_ids:
        return []

    with Session(engine) as session:
        rows = session.exec(select(Listing).where(Listing.id.in_(listing_ids))).all()  # type: ignore[attr-defined]
        return list(rows)


def _rebuild_price_drops(engine, ingest_result) -> list:
    from sqlmodel import Session

    from deal_hunter.db.models import Listing

    rebuilt: list[tuple[Listing, float, float]] = []
    with Session(engine) as session:
        for listing, old_price, new_price in ingest_result.price_drops:
            listing_id = _listing_id(listing)
            if listing_id is None:
                continue
            row = session.get(Listing, listing_id)
            if row is not None:
                rebuilt.append((row, old_price, new_price))
    return rebuilt


async def _process_ingest_result(
    engine,
    config,
    ingest_result,
    *,
    min_score: int,
    ai: bool,
    notify: bool,
) -> None:
    from deal_hunter.alerts.match import match_watches
    from deal_hunter.alerts.pipeline import decide_alerts, dispatch, score_delta
    from deal_hunter.db.ingest import mark_stale

    mark_stale(engine, datetime.now(UTC))
    to_score = _listings_to_score(engine, ingest_result)
    api_key = config.groq_api_key if ai else ""
    analyses = await score_delta(engine, to_score, ai_api_key=api_key) if to_score else {}
    if to_score:
        match_watches(engine, to_score, analyses)
    if notify and to_score:
        price_drops = _rebuild_price_drops(engine, ingest_result)
        alerts = decide_alerts(
            to_score,
            analyses,
            min_score=min_score,
            price_drops=price_drops,
        )
        await dispatch(engine, config, alerts)


async def _run_cycle(
    engine,
    config,
    scrapers,
    *,
    keywords: list[str] | None = None,
    max_pages: int = 3,
    min_score: int = 6,
    ai: bool = False,
    notify: bool = False,
):
    from deal_hunter.db.ingest import IngestionService
    from deal_hunter.scrapers.runner import run_scrapers

    listings = await run_scrapers(
        scrapers,
        keywords=keywords,
        max_pages=max_pages,
        engine=engine,
    )
    ingest_result = IngestionService(engine).ingest_batch(listings)
    await _process_ingest_result(
        engine,
        config,
        ingest_result,
        min_score=min_score,
        ai=ai,
        notify=notify,
    )
    return ingest_result



def _render_analysis(analysis: DealAnalysis) -> None:
    """Render a deal analysis as a Rich panel."""
    # Header with product info
    header = Text()
    header.append(f"{analysis.canonical_name}", style="bold cyan")
    header.append(f"  ({analysis.generation})", style="dim")

    # Pricing table
    price_table = Table(show_header=False, box=None, padding=(0, 2))
    price_table.add_column("Label", style="dim")
    price_table.add_column("Value", justify="right")

    price_table.add_row("Asking", f"₹{analysis.asking_price:,}")
    price_table.add_row("Fair Range", f"₹{analysis.fair_market_low:,} – ₹{analysis.fair_market_high:,}")
    price_table.add_row("Fair Mid", f"₹{analysis.fair_market_mid:,}")
    price_table.add_row("MSRP (new)", f"₹{analysis.msrp:,}")
    price_table.add_row("Age", f"~{analysis.age_months} months")
    price_table.add_row("Depreciation", f"{analysis.depreciation_pct:.0%}")

    pct_style = "green" if analysis.price_vs_fair_pct < 0 else "red"
    pct_label = f"{abs(analysis.price_vs_fair_pct):.0f}% {'below' if analysis.price_vs_fair_pct < 0 else 'above'} fair"
    price_table.add_row("vs Market", Text(pct_label, style=pct_style))

    console.print()
    console.print(header)
    console.print(price_table)

    # Score and verdict
    score_bar = "█" * analysis.deal_score + "░" * (10 - analysis.deal_score)
    score_color = "green" if analysis.deal_score >= 7 else "yellow" if analysis.deal_score >= 5 else "red"
    console.print()
    console.print(f"  Score:    [{score_color}]{score_bar}[/] {analysis.deal_score}/10")

    verdict_style = _VERDICT_COLORS.get(analysis.verdict, "bold")
    console.print(f"  Verdict:  [{verdict_style}]{analysis.verdict}[/]")

    if analysis.suggested_offer:
        console.print(f"  Suggest:  Offer ₹{analysis.suggested_offer:,}")

    console.print(f"  Confidence: {analysis.confidence:.0%}")

    # Reasoning
    console.print()
    console.print(Panel(analysis.reasoning, title="Analysis", border_style="blue", width=80))

    # Red flags
    if analysis.red_flags:
        console.print()
        flag_table = Table(title="Red Flags", show_lines=True)
        flag_table.add_column("Severity", width=10)
        flag_table.add_column("Type", width=24)
        flag_table.add_column("Detail")

        for flag in analysis.red_flags:
            sev_style = _SEVERITY_COLORS.get(flag.severity, "")
            flag_table.add_row(
                Text(flag.severity.upper(), style=sev_style),
                flag.flag_type,
                flag.detail,
            )
        console.print(flag_table)
    else:
        console.print("\n  [green]No red flags detected[/]")

    console.print()


@app.command()
def analyze(
    listing: Annotated[str, typer.Argument(help="Listing text, e.g. 'RTX 3060 Ti, 2yr old, ₹16,500'")],
    price: Annotated[int | None, typer.Option("--price", "-p", help="Asking price in INR")] = None,
    location: Annotated[str, typer.Option("--location", "-l", help="Seller location")] = "",
    description: Annotated[str, typer.Option("--desc", "-d", help="Additional description")] = "",
    ai: Annotated[bool, typer.Option("--ai", help="Use Groq AI for unknown products")] = True,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Analyze a hardware listing and score the deal."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    import asyncio

    from deal_hunter.config import AppConfig

    config = AppConfig()
    api_key = config.groq_api_key if ai else ""

    normalizer = HardwareNormalizer()
    result = asyncio.run(analyze_deal_async(
        text=listing,
        asking_price=price,
        location=location,
        description=description,
        normalizer=normalizer,
        ai_api_key=api_key,
    ))

    if result is None:
        console.print("[red]Could not analyze listing.[/] Could not identify hardware or price.")
        console.print("Tip: Try including the model name (e.g. 'RTX 3060') and price (e.g. '₹15000').")
        raise typer.Exit(1)

    _render_analysis(result)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Hardware name to look up")],
) -> None:
    """Look up fair market value for a hardware item."""
    normalizer = HardwareNormalizer()
    hw = normalizer.normalize(query)

    if hw is None:
        console.print(f"[red]Unknown hardware:[/] '{query}'")
        console.print("Tip: Try a specific model name like 'RTX 3060' or 'Ryzen 5 5600X'.")
        raise typer.Exit(1)

    from deal_hunter.analysis.pricing import calculate_age_months, estimate_fair_value

    age = calculate_age_months(hw.release_date)
    fair = estimate_fair_value(hw.msrp_inr, age, hw.category)

    table = Table(title=hw.canonical_name, show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Category", hw.category)
    table.add_row("Brand", hw.brand)
    table.add_row("Generation", hw.generation)
    table.add_row("Released", hw.release_date)
    table.add_row("Age", f"~{age} months")
    table.add_row("MSRP (new)", f"₹{hw.msrp_inr:,}")
    table.add_row("Fair Used (low)", f"₹{fair.low:,}")
    table.add_row("Fair Used (mid)", f"₹{fair.midpoint:,}")
    table.add_row("Fair Used (high)", f"₹{fair.high:,}")
    table.add_row("Depreciation", f"{fair.depreciation_pct:.0%}")

    console.print()
    console.print(table)
    console.print()


@app.command()
def scrape(
    source: Annotated[str | None, typer.Option("--source", "-s", help="Scrape a single source")] = None,
    keywords: Annotated[str | None, typer.Option("--keywords", "-k", help="Comma-separated search terms")] = None,
    max_pages: Annotated[int, typer.Option("--pages", help="Max pages per source")] = 3,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Scrape listings from TechEnclave and Reddit."""
    import asyncio

    from deal_hunter.config import AppConfig
    from deal_hunter.db.engine import get_engine
    from deal_hunter.db.ingest import IngestionService
    from deal_hunter.scrapers.runner import build_scrapers, run_scrapers

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    config = AppConfig()
    if source:
        config.sources = [source]

    kw_list = [k.strip() for k in keywords.split(",")] if keywords else None

    scrapers = build_scrapers(config)
    if not scrapers:
        console.print("[yellow]No scrapers configured.[/] Check your source settings.")
        raise typer.Exit(1)

    console.print(f"[bold]Scraping from:[/] {', '.join(s.source_name for s in scrapers)}")
    if kw_list:
        console.print(f"[bold]Keywords:[/] {', '.join(kw_list)}")

    engine = get_engine(config.db_path)

    with console.status("[bold green]Scraping..."):
        listings = asyncio.run(
            run_scrapers(scrapers, keywords=kw_list, max_pages=max_pages, engine=engine)
        )

    if not listings:
        console.print("[yellow]No listings found.[/]")
        return

    result = IngestionService(engine).ingest_batch(listings)

    console.print(
        f"\n[bold green]Done![/] {len(result.new)} new, {len(result.seen)} unchanged, "
        f"{len(result.reactivated)} reactivated."
    )
    console.print(f"Total in this batch: {len(listings)} from {len(scrapers)} source(s).")


@app.command()
def listings(
    query: Annotated[str | None, typer.Argument(help="Search term (optional)")] = None,
    source: Annotated[str | None, typer.Option("--source", "-s", help="Filter by source")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
    with_analysis: Annotated[bool, typer.Option("--analyze", "-a", help="Run deal analysis on each")] = False,
) -> None:
    """Browse stored listings."""
    from deal_hunter.config import AppConfig
    from deal_hunter.db.engine import get_engine, get_recent_listings, search_listings

    config = AppConfig()
    engine = get_engine(config.db_path)

    if query:
        results = search_listings(engine, query, limit=limit)
    else:
        results = get_recent_listings(engine, limit=limit, source=source)

    if not results:
        console.print("[yellow]No listings found.[/] Run 'deal-hunter scrape' first.")
        return

    table = Table(title=f"Listings ({len(results)})", show_lines=True)
    table.add_column("#", width=3, justify="right")
    table.add_column("Source", width=12)
    table.add_column("Title", width=40)
    table.add_column("Price", width=12, justify="right")
    table.add_column("Location", width=15)
    table.add_column("Posted", width=12)

    normalizer = HardwareNormalizer() if with_analysis else None

    for i, listing in enumerate(results, 1):
        price_str = f"₹{listing.price:,.0f}" if listing.price else "—"
        posted_str = listing.posted_at.strftime("%Y-%m-%d") if listing.posted_at else "—"
        location_str = (listing.location or "—")[:15]

        table.add_row(
            str(i),
            listing.source,
            listing.title[:40],
            price_str,
            location_str,
            posted_str,
        )

    console.print()
    console.print(table)

    if with_analysis and normalizer:
        console.print("\n[bold]Deal Analysis:[/]")
        for listing in results:
            if not listing.price:
                continue
            result = analyze_deal(
                text=listing.title,
                asking_price=int(listing.price),
                location=listing.location or "",
                description=listing.description or "",
                normalizer=normalizer,
            )
            if result:
                _render_analysis(result)

    console.print()


@app.command()
def deals(
    min_score: Annotated[int, typer.Option("--min-score", "-m", help="Minimum deal score (1-10)")] = 6,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
    ai: Annotated[bool, typer.Option("--ai", help="Use Groq AI when rescoring")] = False,
    rescore: Annotated[bool, typer.Option("--rescore", help="Rescore the recent priced window")] = False,
    notify: Annotated[bool, typer.Option("--notify", help="Send Telegram alerts for good deals")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Show persisted deals, optionally rescore the recent priced window."""
    import asyncio

    from deal_hunter.alerts.pipeline import decide_alerts, dispatch, score_delta
    from deal_hunter.config import AppConfig
    from deal_hunter.db.engine import get_engine, get_recent_listings

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    config = AppConfig()
    engine = get_engine(config.db_path)

    if rescore:
        priced = get_recent_listings(engine, limit=limit, with_price=True)
        if not priced:
            console.print("[yellow]No priced listings found.[/] Run 'deal-hunter scrape' first.")
            return
        console.print(f"[bold]Rescoring {len(priced)} priced listings...[/]")
        api_key = config.groq_api_key if ai else ""

        async def _rescore() -> dict:
            return await score_delta(engine, priced, ai_api_key=api_key)

        with console.status("[bold green]Rescoring deals..."):
            analyses = asyncio.run(_rescore())

        if notify and analyses:
            alerts = decide_alerts(priced, analyses, min_score=min_score)
            asyncio.run(dispatch(engine, config, alerts))

    scored_listings = _get_scored_listings(engine, min_score, limit)
    if not scored_listings:
        console.print(f"[yellow]No deals scored {min_score}+ found.[/] Try lowering --min-score.")
        return

    console.print(f"\n[bold]Top Deals ({len(scored_listings)} found, min score {min_score}):[/]\n")
    for listing in scored_listings:
        analysis = _listing_to_analysis(listing)
        if analysis is None:
            continue
        _render_analysis(analysis)
        console.print(f"  [dim]Source: {listing.source} | {listing.url}[/]\n")


@app.command()
def run(
    source: Annotated[str | None, typer.Option("--source", "-s", help="Scrape a single source")] = None,
    keywords: Annotated[str | None, typer.Option("--keywords", "-k", help="Comma-separated search terms")] = None,
    max_pages: Annotated[int, typer.Option("--pages", help="Max pages per source")] = 3,
    min_score: Annotated[int, typer.Option("--min-score", "-m", help="Minimum deal score for alerts")] = 6,
    ai: Annotated[bool, typer.Option("--ai", help="Use Groq AI for scoring unknown products")] = False,
    notify: Annotated[bool, typer.Option("--notify", help="Send Telegram alerts for good deals")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run scrape, ingest, score, and optional alerts in one cycle."""
    import asyncio

    from deal_hunter.config import AppConfig
    from deal_hunter.db.engine import get_engine
    from deal_hunter.scrapers.runner import build_scrapers

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    config = AppConfig()
    if source:
        config.sources = [source]

    scrapers = build_scrapers(config)
    if not scrapers:
        console.print("[yellow]No scrapers configured.[/] Check your source settings.")
        raise typer.Exit(1)

    kw_list = [k.strip() for k in keywords.split(",")] if keywords else None
    engine = get_engine(config.db_path)

    console.print(f"[bold]Running cycle from:[/] {', '.join(s.source_name for s in scrapers)}")
    if kw_list:
        console.print(f"[bold]Keywords:[/] {', '.join(kw_list)}")

    with console.status("[bold green]Running cycle..."):
        result = asyncio.run(
            _run_cycle(
                engine,
                config,
                scrapers,
                keywords=kw_list,
                max_pages=max_pages,
                min_score=min_score,
                ai=ai,
                notify=notify,
            )
        )

    console.print(
        f"\n[bold green]Cycle complete.[/] {len(result.new)} new, {len(result.seen)} unchanged, "
        f"{len(result.price_drops)} price drops."
    )


async def _watch_loop(
    interval: int,
    min_score: int,
    ai: bool,
    notify: bool,
    config,
    scrapers,
    engine,
) -> None:
    """Continuous scrape-ingest-score-alert cycles."""
    import asyncio
    import time

    while True:
        console.print(f"[dim]{time.strftime('%H:%M:%S')}[/] Running cycle...", end=" ")
        result = await _run_cycle(
            engine,
            config,
            scrapers,
            max_pages=2,
            min_score=min_score,
            ai=ai,
            notify=notify,
        )
        console.print(
            f"{len(result.new)} new, {len(result.seen)} unchanged, {len(result.price_drops)} drops."
        )
        console.print(f"  Next cycle in {interval}s...\n")
        await asyncio.sleep(interval)


@app.command()
def watch(
    interval: Annotated[int, typer.Option("--interval", "-i", help="Seconds between scrape cycles")] = 300,
    min_score: Annotated[int, typer.Option("--min-score", "-m")] = 7,
    ai: Annotated[bool, typer.Option("--ai", help="Use AI scoring")] = False,
    notify: Annotated[bool, typer.Option("--notify", help="Send Telegram alerts")] = False,
) -> None:
    """Continuous mode: scrape, score, and alert on interval (graceful shutdown)."""
    import asyncio
    import signal

    from deal_hunter.config import AppConfig
    from deal_hunter.db.engine import get_engine
    from deal_hunter.scrapers.runner import build_scrapers

    config = AppConfig()
    scrapers = build_scrapers(config)
    engine = get_engine(config.db_path)

    console.print(f"[bold]Watch mode[/] — scraping every {interval}s, min score {min_score}")
    console.print(f"Sources: {', '.join(s.source_name for s in scrapers)}")
    console.print("Press Ctrl+C to stop.\n")

    async def _run() -> None:
        stop = asyncio.Event()

        def _on_signal(signum, _frame) -> None:
            console.print(f"\n[bold]Shutting down gracefully ({signal.Signals(signum).name})...[/]")
            stop.set()

        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, _on_signal, signal.SIGINT, None)
        loop.add_signal_handler(signal.SIGTERM, _on_signal, signal.SIGTERM, None)

        async with asyncio.TaskGroup() as tg:
            task = tg.create_task(_watch_loop(interval, min_score, ai, notify, config, scrapers, engine))
            await stop.wait()
            task.cancel()

        engine.dispose()  # close the shared pool cleanly
        console.print("[bold]Watch stopped cleanly.[/]")

    asyncio.run(_run())


@app.command()
def history(
    query: Annotated[str, typer.Argument(help="Product name to look up (e.g. 'RTX 3060')")],
) -> None:
    """Show price history for a product."""
    from deal_hunter.config import AppConfig
    from deal_hunter.db.engine import get_engine, get_price_history, get_price_summary

    config = AppConfig()
    engine = get_engine(config.db_path)

    # Normalize the query to canonical name
    normalizer = HardwareNormalizer()
    hw = normalizer.normalize(query)
    name = hw.canonical_name if hw else query

    summary = get_price_summary(engine, name)
    if not summary:
        console.print(f"[yellow]No price history for '{name}'.[/]")
        console.print("Tip: Run 'deal-hunter deals --ai' to record prices as listings are scored.")
        return

    console.print(f"\n[bold cyan]{name}[/] — {summary['count']} observations")
    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column("Label", style="dim")
    stats_table.add_column("Value", justify="right")
    stats_table.add_row("Lowest", f"₹{summary['min_price']:,}")
    stats_table.add_row("Average", f"₹{summary['avg_price']:,}")
    stats_table.add_row("Highest", f"₹{summary['max_price']:,}")
    console.print(stats_table)

    entries = get_price_history(engine, name, limit=20)
    if entries:
        console.print()
        hist_table = Table(title="Recent Prices", show_lines=True)
        hist_table.add_column("Date", width=12)
        hist_table.add_column("Price", width=12, justify="right")
        hist_table.add_column("Source", width=12)
        hist_table.add_column("Location", width=15)

        for e in entries:
            hist_table.add_row(
                e.observed_at.strftime("%Y-%m-%d"),
                f"₹{e.price:,.0f}",
                e.source,
                e.location or "—",
            )
        console.print(hist_table)
    console.print()


@app.command(name="setup-telegram")
def setup_telegram() -> None:
    """Test Telegram bot connection and show setup instructions."""
    import asyncio

    from deal_hunter.config import AppConfig
    from deal_hunter.notifications.telegram import send_summary

    config = AppConfig()

    if not config.telegram.bot_token or not config.telegram.chat_id:
        console.print("[bold]Telegram Setup Guide[/]\n")
        console.print("1. Open Telegram, search for [bold]@BotFather[/]")
        console.print("2. Send [bold]/newbot[/], follow prompts to create a bot")
        console.print("3. Copy the bot token (looks like [dim]123456:ABC-DEF...[/])")
        console.print("4. Start a chat with your bot, send any message")
        console.print("5. Get your chat ID: visit [dim]https://api.telegram.org/bot<TOKEN>/getUpdates[/]")
        console.print("6. Update your [bold].env[/] file:\n")
        console.print("   DEAL_HUNTER_TELEGRAM__ENABLED=true")
        console.print("   DEAL_HUNTER_TELEGRAM__BOT_TOKEN=your_token_here")
        console.print("   DEAL_HUNTER_TELEGRAM__CHAT_ID=your_chat_id_here")
        return

    console.print("[bold]Testing Telegram connection...[/]")
    success = asyncio.run(send_summary(
        bot_token=config.telegram.bot_token,
        chat_id=config.telegram.chat_id,
        total_scraped=0,
        deals_found=0,
        top_deals=[],
    ))

    if success:
        console.print("[green]Telegram bot is working![/] You'll get deal alerts with --notify.")
    else:
        console.print("[red]Failed to send test message.[/] Check your bot token and chat ID.")


@app.command()
def version() -> None:
    """Show version."""
    console.print("deal-hunter v0.1.0")


if __name__ == "__main__":
    app()
