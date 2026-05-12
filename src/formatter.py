"""Discord embed formatters per the design mockup.

Layout philosophy:
- Title is clickable (``url=`` market url) so the embed has a primary anchor.
- An explicit "View Market" link row follows the metric fields as a fallback
  for users who don't realize the title is clickable (matches the mockup).
- Side-by-side metrics use Discord's inline embed fields.
- Direction (YES / NO) is rendered with ANSI bold green / red inside an
  ``ansi`` code block. This adds a code-block background but is the only way
  to actually colour text inside a webhook embed; legibility of the
  bull/bear signal is more important than the visual minimalism the mockup
  implies.
- Wallet addresses use the mockup's 6-leading + 3-trailing shortening
  (``0xabc...def``) inside backticks for monospace alignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .nansen_client import ATTRIBUTION_FOOTER_PLAIN

SMART_MONEY_COLOR = 0x9B59B6  # SPEC §5.1 — purple, individual trades
CONVERGENCE_COLOR = 0xE74C3C  # SPEC §5.2 — red, multi-wallet convergence

# ANSI escapes inside Discord ``ansi``-fenced code blocks. ``1;`` = bold,
# ``32`` = green, ``31`` = red.
ANSI_GREEN_BOLD = "\x1b[1;32m"
ANSI_RED_BOLD = "\x1b[1;31m"
ANSI_RESET = "\x1b[0m"

# Zero-width space — Discord requires a non-empty field name; using a ZWS
# gives us a heading-less link row.
ZWS = "​"


def shorten_wallet(addr: str) -> str:
    """Mockup-style 6-leading + 3-trailing shortening (``0xabc...def``)."""
    if not addr or len(addr) < 10:
        return addr or ""
    return f"{addr[:6]}...{addr[-3:]}"


def market_url(market_id: str, slug: str | None = None) -> str:
    if slug:
        return f"https://polymarket.com/event/{slug}"
    return f"https://polymarket.com/market/{market_id}"


def nansen_wallet_url(addr: str) -> str:
    return f"https://app.nansen.ai/profiler/{addr}"


def _direction_block(side: str) -> str:
    """ANSI-coloured YES (green) / NO (red) inside a one-line code block."""
    s = (side or "").upper()
    if s == "YES":
        return f"```ansi\n{ANSI_GREEN_BOLD}YES{ANSI_RESET}\n```"
    if s == "NO":
        return f"```ansi\n{ANSI_RED_BOLD}NO{ANSI_RESET}\n```"
    return f"`{s or '?'}`"


def _direction_inline(side: str, amount_usd: float, price_str: str) -> str:
    """Variant for the trade embed where Direction sits with size + price.

    A full ANSI block in this cell would dwarf the rest, so we colour just the
    side keyword and follow with plain text. Discord renders multiple lines
    inside a single field cleanly.
    """
    s = (side or "").upper()
    if s == "YES":
        coloured = f"```ansi\n{ANSI_GREEN_BOLD}YES{ANSI_RESET}\n```"
    elif s == "NO":
        coloured = f"```ansi\n{ANSI_RED_BOLD}NO{ANSI_RESET}\n```"
    else:
        coloured = f"`{s or '?'}`"
    return f"{coloured}${amount_usd:,.0f} @ {price_str}"


@dataclass
class WalletStats:
    address: str
    rank: int | None = None
    cumulative_pnl_usd: float = 0.0
    win_rate: float = 0.0
    market_appearances: int = 0


@dataclass
class TradeNotification:
    market_id: str
    market_question: str
    market_slug: str | None
    side: str
    amount_usd: float
    entry_price: float | None
    wallet: WalletStats
    # Optional Nansen-sourced enrichment (FREE / ATTRIBUTION tier only).
    # When present, an "On-chain context" field is added to the embed and the
    # Nansen attribution footer is set, per Nansen redistribution policy.
    nansen_context: dict[str, Any] | None = None


def _signed_usd(val: float | int | None) -> str:
    if val is None:
        return "—"
    v = float(val)
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def _format_nansen_context_value(ctx: dict[str, Any]) -> str | None:
    """Render Nansen on-chain context as a multiline embed field.

    Only uses FREE/ATTRIBUTION tier data (address pnl-summary, balances,
    prediction-market address-summary). NEVER includes entity labels or
    smart-money classifications per Nansen ToS.
    """
    lines: list[str] = []
    pnl = ctx.get("onchain_pnl_usd")
    wr = ctx.get("onchain_win_rate")
    tc = ctx.get("onchain_trade_count")
    lookback = ctx.get("lookback_days") or 0
    if pnl is not None and tc:
        wr_str = f", win {float(wr):.0%}" if wr is not None else ""
        lines.append(
            f"On-chain ({int(lookback)}d): **{_signed_usd(pnl)}**{wr_str} across {int(tc)} sales"
        )
    pf = ctx.get("portfolio_value_usd")
    if pf:
        lines.append(f"Portfolio (top tokens): **${float(pf):,.0f}**")
    pm_pnl = ctx.get("pm_total_pnl_usd")
    pm_mkts = ctx.get("pm_markets_traded") or 0
    pm_wr = ctx.get("pm_win_rate")
    if pm_pnl is not None and pm_mkts:
        wr_str = f", win {float(pm_wr):.0%}" if pm_wr is not None else ""
        lines.append(
            f"Polymarket lifetime: **{_signed_usd(pm_pnl)}**{wr_str} across {int(pm_mkts)} markets"
        )
    age = ctx.get("pm_wallet_age_days")
    if age:
        lines.append(f"Wallet age: {int(age)} days")
    return "\n".join(lines) if lines else None


def format_trade_embed(t: TradeNotification) -> dict[str, Any]:
    price_str = f"${t.entry_price:.3f}" if t.entry_price is not None else "—"
    rank_str = f"Rank #{t.wallet.rank}" if t.wallet.rank else "—"
    url = market_url(t.market_id, t.market_slug)

    fields = [
        {
            "name": "Direction",
            "value": _direction_block(t.side),
            "inline": True,
        },
        {
            "name": "Size",
            "value": f"**${t.amount_usd:,.0f}** @ {price_str}",
            "inline": True,
        },
        {
            "name": "Wallet",
            "value": f"`{shorten_wallet(t.wallet.address)}` ({rank_str})",
            "inline": True,
        },
        {
            "name": "Cumulative PnL",
            "value": f"${t.wallet.cumulative_pnl_usd:,.0f}",
            "inline": True,
        },
        {
            "name": "Win Rate",
            "value": f"{t.wallet.win_rate:.0%}",
            "inline": True,
        },
        {
            "name": "Active Markets",
            "value": str(t.wallet.market_appearances),
            "inline": True,
        },
    ]

    nansen_field: str | None = None
    if t.nansen_context:
        nansen_field = _format_nansen_context_value(t.nansen_context)
        if nansen_field:
            fields.append(
                {"name": "On-chain context", "value": nansen_field, "inline": False}
            )

    fields.append(
        {
            "name": ZWS,
            "value": (
                f"[View Market]({url}) · "
                f"[View Wallet]({nansen_wallet_url(t.wallet.address)})"
            ),
            "inline": False,
        }
    )

    embed: dict[str, Any] = {
        "title": "🎯 Smart Money Trade",
        "url": url,
        "description": f"**{t.market_question}**" if t.market_question else None,
        "color": SMART_MONEY_COLOR,
        "fields": fields,
    }
    # Add Nansen attribution footer when on-chain context is shown,
    # per Nansen redistribution policy for ATTRIBUTION-tier data.
    if nansen_field:
        embed["footer"] = {"text": ATTRIBUTION_FOOTER_PLAIN}
    return embed


@dataclass
class ConvergenceWalletEntry:
    address: str
    amount_usd: float


@dataclass
class ConvergenceNotification:
    market_id: str
    market_question: str
    market_slug: str | None
    side: str
    total_amount_usd: float
    wallets: list[ConvergenceWalletEntry]
    current_probability: float | None = None


def _format_wallet_lines(wallets: list[ConvergenceWalletEntry], max_rows: int = 10) -> str:
    """Bulleted list with left-padded addresses and amounts.

    Inside a Discord field value, a regular markdown list renders cleanly;
    backticks on the address force monospace so the column alignment holds.
    """
    rows = wallets[:max_rows]
    addr_w = max((len(shorten_wallet(w.address)) for w in rows), default=14)
    lines: list[str] = []
    for w in rows:
        addr = shorten_wallet(w.address).ljust(addr_w)
        lines.append(f"• `{addr}`  ${w.amount_usd:,.0f}")
    if len(wallets) > max_rows:
        lines.append(f"• …and {len(wallets) - max_rows} more")
    return "\n".join(lines)


def format_convergence_embed(n: ConvergenceNotification) -> dict[str, Any]:
    prob_value = (
        f"**{n.current_probability * 100:.0f}%**"
        if n.current_probability is not None
        else "—"
    )
    url = market_url(n.market_id, n.market_slug)

    fields = [
        {
            "name": "Direction",
            "value": _direction_block(n.side),
            "inline": True,
        },
        {
            "name": "Total inflow (24h)",
            "value": f"**${n.total_amount_usd:,.0f}**",
            "inline": True,
        },
        {
            "name": f"{len(n.wallets)} smart wallets in last 24h",
            "value": _format_wallet_lines(n.wallets),
            "inline": False,
        },
        {
            "name": "Current probability",
            "value": prob_value,
            "inline": False,
        },
        {
            "name": ZWS,
            "value": f"[View Market]({url})",
            "inline": False,
        },
    ]
    return {
        "title": "🚨 Smart Money Convergence",
        "url": url,
        "description": f"**Market:** {n.market_question}" if n.market_question else None,
        "color": CONVERGENCE_COLOR,
        "fields": fields,
    }
