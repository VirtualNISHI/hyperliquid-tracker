"""Render the Hyperliquid daily snapshot as a 1200×800 PNG (dark theme).

Layout:
    ┌────────────────────────────────────────────────────────────┐
    │  📊  Hyperliquid Daily Snapshot                            │
    │      2026-05-07 (JST) · 230 perps                          │
    ├────────────────────────────────────────────────────────────┤
    │  🔥  Top Open Interest                                     │
    │      • BTC      $2.5B OI       +0.2%                       │
    │      ...                                                   │
    │  💸  Top 24h Volume                                        │
    │      • BTC      $2.7B Vol      +0.2%                       │
    │      ...                                                   │
    │  ⚡  Funding Extreme (APR)                                 │
    │      • PUMP    +245% APR       +12.3%                      │
    │      ...                                                   │
    ├────────────────────────────────────────────────────────────┤
    │  Auto-generated · Data via Hyperliquid public API          │
    └────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

from .collector import SnapshotRow

log = logging.getLogger(__name__)

W, H = 1200, 900
PAD = 50

# Dark palette
BG = (14, 16, 20)
DIVIDER = (48, 54, 61)
TEXT = (230, 237, 243)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
ACCENT = (139, 148, 230)

_JP_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/YuGothB.ttc", 0),
    ("C:/Windows/Fonts/YuGothM.ttc", 0),
    ("C:/Windows/Fonts/meiryob.ttc", 0),
    ("C:/Windows/Fonts/meiryo.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
]
_MONO_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/consolab.ttf", 0),
    ("C:/Windows/Fonts/consola.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 0),
]


def _load_font(candidates: list[tuple[str, int]], size: int) -> ImageFont.FreeTypeFont:
    for path, index in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size, index=index)
            except OSError:
                continue
    raise RuntimeError("No usable font found.")


def _fmt_usd_compact(v: float) -> str:
    """$1.23B / $456M / $7.8K formatting."""
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{sign}${a / 1_000_000_000:,.2f}B"
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:,.0f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:,.0f}K"
    return f"{sign}${a:,.0f}"


def _fmt_apr(rate: float) -> tuple[str, tuple[int, int, int]]:
    """Funding APR as ±X.X% with green/red color."""
    pct = rate * 100
    sign = "+" if pct >= 0 else ""
    color = GREEN if pct >= 0 else RED
    return f"{sign}{pct:,.1f}%", color


def _fmt_pct_change(d: float | None) -> tuple[str, tuple[int, int, int]]:
    if d is None:
        return "—", DIM
    pct = d * 100
    sign = "+" if pct >= 0 else ""
    color = GREEN if pct >= 0 else RED
    return f"{sign}{pct:.1f}%", color


def _section_metric_text(row: SnapshotRow) -> tuple[str, tuple[int, int, int]]:
    """Return (text, color) for the section-specific metric column.

    - Top OI: $X.XB OI (color = neutral text)
    - Top Volume: $X.XB Vol
    - Funding: ±X.X% APR (color depends on sign)
    """
    if row.category == "Funding":
        return _fmt_apr(row.volume_24h_usd / 100.0)  # we stored APR as fraction × 100? No — stored as APR fraction directly. Recompute:
    if row.category == "Top OI":
        return f"{_fmt_usd_compact(row.open_interest_usd)} OI", TEXT
    # Top Volume
    return f"{_fmt_usd_compact(row.day_volume_usd)} Vol", TEXT


def _section_metric(row: SnapshotRow) -> tuple[str, tuple[int, int, int]]:
    """Section-specific metric formatting."""
    if row.category == "Top OI":
        return f"{_fmt_usd_compact(row.open_interest_usd)} OI", TEXT
    if row.category == "Top Volume":
        return f"{_fmt_usd_compact(row.day_volume_usd)} Vol", TEXT
    if row.category == "Funding":
        # row.funding_apr is the APR as a fraction (e.g. 0.10 = 10% APR)
        return _fmt_apr(row.funding_apr)
    return "—", DIM


def render_snapshot_png(
    *,
    snapshot_date: datetime,
    top_oi: list[SnapshotRow],
    top_vol: list[SnapshotRow],
    funding: list[SnapshotRow],
    universe_size: int,
    market_summary_jp: str = "",
) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(_JP_FONT_CANDIDATES, 36)
    date_font = _load_font(_JP_FONT_CANDIDATES, 22)
    section_font = _load_font(_JP_FONT_CANDIDATES, 24)
    label_font = _load_font(_MONO_FONT_CANDIDATES, 22)
    metric_font = _load_font(_MONO_FONT_CANDIDATES, 22)
    pct_font = _load_font(_MONO_FONT_CANDIDATES, 22)
    summary_font = _load_font(_JP_FONT_CANDIDATES, 18)
    footer_font = _load_font(_JP_FONT_CANDIDATES, 16)

    with Pilmoji(img) as pilmoji:
        # Header
        date_str = snapshot_date.strftime("%Y-%m-%d")
        pilmoji.text((PAD, 36), "📊  Hyperliquid Daily Snapshot", font=title_font, fill=TEXT)
        draw.text(
            (PAD, 84), f"{date_str} (JST) · {universe_size} perps",
            font=date_font, fill=DIM,
        )
        draw.line([(PAD, 130), (W - PAD, 130)], fill=DIVIDER, width=2)

        # Sections
        sections: list[tuple[str, str, list[SnapshotRow]]] = [
            ("🔥", "Top Open Interest", top_oi),
            ("💸", "Top 24h Volume", top_vol),
            ("⚡", "Funding Extreme (APR)", funding),
        ]

        y = 160
        for emoji, title, rows in sections:
            pilmoji.text((PAD, y), f"{emoji}  {title}", font=section_font, fill=TEXT)
            y += 42

            for r in rows:
                metric_text, metric_color = _section_metric(r)
                change_text, change_color = _fmt_pct_change(r.one_day_change)

                # bullet
                draw.ellipse(
                    [(PAD + 12, y + 11), (PAD + 18, y + 17)], fill=DIM,
                )
                # ticker (left)
                draw.text((PAD + 32, y), r.market_id, font=label_font, fill=TEXT)
                # metric (middle, right-aligned at fixed x)
                metric_right = 800
                metric_w = int(metric_font.getlength(metric_text))
                draw.text((metric_right - metric_w, y), metric_text, font=metric_font, fill=metric_color)
                # 24h price change (right)
                change_right = 1000
                change_w = int(pct_font.getlength(change_text))
                draw.text((change_right - change_w, y), change_text, font=pct_font, fill=change_color)

                y += 32

            y += 18

        # Optional Japanese market summary (Gemini-generated)
        if market_summary_jp:
            draw.line([(PAD, y), (W - PAD, y)], fill=DIVIDER, width=1)
            y += 14
            # Wrap to 2 lines if needed
            max_chars = 60
            text = market_summary_jp.strip()
            if len(text) > max_chars * 2:
                text = text[: max_chars * 2 - 1] + "…"
            lines = [text[i : i + max_chars] for i in range(0, len(text), max_chars)][:2]
            for ln in lines:
                draw.text((PAD, y), ln, font=summary_font, fill=TEXT)
                y += 26
            y += 8

        # Footer
        footer_y = H - 40
        draw.line(
            [(PAD, footer_y - 14), (W - PAD, footer_y - 14)], fill=DIVIDER, width=1,
        )
        draw.text(
            (PAD, footer_y),
            "Auto-generated · Data via Hyperliquid public API · @Nishi8maru",
            font=footer_font, fill=DIM,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
