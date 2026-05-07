"""Hyperliquid snapshot data collection.

One ``metaAndAssetCtxs`` call yields every perpetual with mark price, prev-day
price, 24h volume, open interest, and current funding rate. We rank them three
different ways for the three card sections.

The downstream renderer/formatter consumes ``SnapshotRow`` objects (kept for
reuse with the polymarket-BOT template). We re-purpose its fields:

| SnapshotRow field | Hyperliquid meaning |
|---|---|
| ``market_id`` | coin ticker, e.g. "BTC" |
| ``slug`` | lower-case ticker, e.g. "btc" |
| ``question`` | display text used by the renderer |
| ``yes_price`` | mark price in USD |
| ``one_day_change`` | 24h price change as a fraction (0.05 = +5%) |
| ``volume_24h_usd`` | the section-specific metric (OI USD / volume USD / funding APR) |
| ``category`` | section label ("Top OI" / "Top Volume" / "Funding") |
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..hyperliquid_client import HyperliquidClient, HyperliquidPerp

log = logging.getLogger(__name__)


@dataclass
class SnapshotRow:
    market_id: str           # coin ticker
    slug: str | None         # lower ticker
    question: str            # display label (e.g. "BTC")
    yes_price: float | None  # mark price USD
    one_day_change: float | None  # 24h price change (fraction)
    volume_24h_usd: float    # section-specific metric (see module docstring)
    tag_slugs: list[str]
    category: str | None
    event_slug: str | None = None
    event_title: str | None = None
    # Hyperliquid-specific extras for the renderer
    open_interest_usd: float = 0.0
    day_volume_usd: float = 0.0
    funding_apr: float = 0.0


def _to_row(perp: HyperliquidPerp, *, category: str, metric_value: float) -> SnapshotRow:
    return SnapshotRow(
        market_id=perp.coin,
        slug=perp.coin.lower(),
        question=perp.coin,  # ticker only
        yes_price=perp.mark_price_usd,
        one_day_change=perp.price_change_24h_pct,
        volume_24h_usd=metric_value,  # section-specific
        tag_slugs=[],
        category=category,
        open_interest_usd=perp.open_interest_usd,
        day_volume_usd=perp.day_volume_usd,
        funding_apr=perp.funding_rate_apr,
    )


def collect_snapshot(
    client: HyperliquidClient,
    *,
    min_open_interest_usd: float = 1_000_000,
    **_unused,
) -> list[HyperliquidPerp]:
    """Pull all perpetuals, drop the illiquid tail (OI < $1M)."""
    perps = client.fetch_all_perps()
    eligible = [p for p in perps if p.open_interest_usd >= min_open_interest_usd]
    log.info(
        "snapshot universe: %d perps after OI filter (from %d total)",
        len(eligible),
        len(perps),
    )
    return eligible


def top_open_interest(perps: list[HyperliquidPerp], *, n: int = 5) -> list[SnapshotRow]:
    """Top N by current open interest (USD)."""
    sorted_ = sorted(perps, key=lambda p: p.open_interest_usd, reverse=True)[:n]
    return [_to_row(p, category="Top OI", metric_value=p.open_interest_usd) for p in sorted_]


def top_volume(perps: list[HyperliquidPerp], *, n: int = 5) -> list[SnapshotRow]:
    """Top N by 24h notional volume (USD)."""
    sorted_ = sorted(perps, key=lambda p: p.day_volume_usd, reverse=True)[:n]
    return [_to_row(p, category="Top Volume", metric_value=p.day_volume_usd) for p in sorted_]


def funding_extreme(perps: list[HyperliquidPerp], *, n: int = 5) -> list[SnapshotRow]:
    """Top N by absolute current funding rate (positive or negative).

    Sign of ``funding_apr`` is preserved in ``volume_24h_usd`` (the section
    metric) so the renderer can color-code per row.
    """
    eligible = [p for p in perps if p.funding_rate_hourly != 0]
    sorted_ = sorted(eligible, key=lambda p: abs(p.funding_rate_hourly), reverse=True)[:n]
    return [
        _to_row(p, category="Funding", metric_value=p.funding_rate_apr) for p in sorted_
    ]
