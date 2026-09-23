"""UI presentation helpers — deal-signal colors, price deltas, score bars.

Centralizes the design decisions so the dealer's visual language (buy = green,
scam = red, below-market = down-arrow) is consistent across every template.

Helpers that emit HTML return `Markup` so Jinja2 does not re-escape them.
"""
from __future__ import annotations

from markupsafe import Markup

# Shared verdict data. badge = plaintext w/ emoji (telegram), chip class = dashboard.
VERDICT_BADGES: dict[str, str] = {
    "BUY": "🟢 BUY NOW",
    "NEGOTIATE": "🟡 NEGOTIATE",
    "PASS": "🔴 PASS",
    "SCAM_RISK": "⛔ SCAM RISK",
}

# Per-category marketplace visuals: (short label, emoji, gradient stops)
CATEGORY_VISUALS: dict[str, tuple[str, str, str]] = {
    "gpu": ("GPU", "🖥", "linear-gradient(135deg,#3a1d5e,#7c3aed)"),
    "cpu": ("CPU", "⚙️", "linear-gradient(135deg,#1d3a5e,#2f7ced)"),
    "ram": ("RAM", "🧠", "linear-gradient(135deg,#3a5e1d,#4ced2f)"),
    "ssd": ("SSD", "💾", "linear-gradient(135deg,#5e1d3a,#ed2f8f)"),
    "monitor": ("Monitor", "🖥", "linear-gradient(135deg,#1d5e5e,#2feed)"),
    "laptop": ("Laptop", "💻", "linear-gradient(135deg,#5e3a1d,#ed8f2f)"),
    "motherboard": ("Motherboard", "🔲", "linear-gradient(135deg,#3a3a5e,#6f7ced)"),
    "psu": ("PSU", "🔌", "linear-gradient(135deg,#4a4a4a,#9a9a9a)"),
}

# Categories shown in the sidebar nav, in order; "all" + "other" handled specially
SIDEBAR_CATEGORIES: list[str] = [
    "gpu", "cpu", "ram", "ssd", "monitor",
    "laptop", "motherboard", "psu", "other",
]

# Verdicts usable as a sidebar quick-filter
SIDEBAR_VERDICTS: list[str] = ["BUY", "NEGOTIATE", "PASS", "SCAM_RISK"]


def category_visual(category: str | None) -> tuple[str, str, str]:
    """Return (label, emoji, gradient) for a category; generic fallback for None/'other'."""
    if not category or category == "other":
        return ("Deal", "🏷", "linear-gradient(135deg,#33333a,#5a5a63)")
    return CATEGORY_VISUALS.get(category, ("Deal", "🏷", "linear-gradient(135deg,#33333a,#5a5a63)"))


def verdict_ui(verdict: str | None) -> tuple[str, str]:
    """Map a verdict to a CSS class + short label."""
    if verdict is None:
        return ("—", "chip-neutral")
    table = {
        "BUY": ("BUY", "chip-buy"),
        "NEGOTIATE": ("NEGOTIATE", "chip-negotiate"),
        "PASS": ("PASS", "chip-pass"),
        "SCAM_RISK": ("SCAM RISK", "chip-scam"),
    }
    label, cls = table.get(verdict, (verdict, "chip-neutral"))
    return label, cls


def price_delta(pct: float | None) -> tuple[str, str]:
    """Return (label, css_class) for a price-vs-fair percentage.

    pct<0 means below fair (good for buyer). Returns like
    ("18% below", "delta-good") / ("12% above", "delta-bad") / ("at market", "delta-flat").
    """
    if pct is None:
        return ("—", "delta-flat")
    if pct <= -5:
        return (f"{abs(pct):.0f}% below", "delta-good")
    if pct >= 5:
        return (f"{pct:.0f}% above", "delta-bad")
    return ("at market", "delta-flat")


def score_blocks(score: int | None, total: int = 10) -> str:
    """Plain block-glyph score bar (e.g. '██████░░░░'). Shared by all renderers."""
    if score is None:
        return ""
    filled = "█" * max(0, min(int(score), total))
    empty = "░" * max(0, total - int(score))
    return f"{filled}{empty}"


def score_bar(score: int | None, total: int = 10) -> Markup:
    """10-segment monospace score bar with green/amber/red shading."""
    blocks = score_blocks(score, total)
    if not blocks:
        return Markup("")
    cls = "sig-buy" if score >= 7 else "sig-negotiate" if score >= 5 else "sig-pass"
    return Markup(f'<span class="{cls} mono">{blocks}</span>')


def fmt_inr(price: float | None) -> str:
    return f"₹{price:,.0f}" if price is not None else "—"


def fmt_dt(dt, fmt="%d %b %H:%M"):
    return dt.strftime(fmt) if dt else "—"

def relative_time(dt) -> str:
    """Human-readable age for listing timestamps."""
    if not dt:
        return "—"
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    secs = int((now - dt).total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    return dt.strftime("%d %b")


def live_run_status(last: dict | None) -> dict:
    """Map last_run_summary to LIVE / STALE / OFF pill state."""
    from datetime import UTC, datetime, timedelta

    if last is None:
        return {"label": "OFF", "cls": "live-off", "pulse": False}
    started = last["started_at"]
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    age = datetime.now(UTC) - started
    if age < timedelta(hours=3):
        return {"label": "LIVE", "cls": "live-ok", "pulse": True}
    return {"label": "STALE", "cls": "live-stale", "pulse": False}


def sparkline_svg(history, median: float | None, width: int = 320, height: int = 80) -> Markup:
    """Inline SVG polyline for price history with optional median guide."""
    if not history:
        return Markup("")
    points = list(reversed(history))
    prices = [p.price for p in points]
    if len(prices) < 2:
        return Markup("")
    lo = min(prices)
    hi = max(prices)
    if median is not None:
        lo = min(lo, median)
        hi = max(hi, median)
    span = hi - lo or 1.0
    pad = 6
    coords: list[str] = []
    for i, price in enumerate(prices):
        x = pad + (i / (len(prices) - 1)) * (width - 2 * pad)
        y = height - pad - ((price - lo) / span) * (height - 2 * pad)
        coords.append(f"{x:.1f},{y:.1f}")
    median_line = ""
    if median is not None:
        my = height - pad - ((median - lo) / span) * (height - 2 * pad)
        median_line = (
            f'<line x1="{pad}" y1="{my:.1f}" x2="{width - pad}" y2="{my:.1f}" '
            f'stroke="var(--text-4)" stroke-width="1" stroke-dasharray="4 3"/>'
        )
    return Markup(
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'{median_line}'
        f'<polyline fill="none" stroke="var(--accent-hi)" stroke-width="1.5" '
        f'points="{" ".join(coords)}"/></svg>'
    )
