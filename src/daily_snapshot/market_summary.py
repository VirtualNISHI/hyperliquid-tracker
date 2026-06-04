"""Generate a 1-line Japanese market summary via the jp_translator LLM chain.

Given the three ranked sections (Top OI / Top Volume / Funding Extreme),
ask the LLM chain to summarize the Hyperliquid perp market state in 1-2 short
Japanese sentences (max ~120 chars).

Fallback chain (shared jp_translator package): Gemini → OpenAI → Grok.
DeepL is excluded since it cannot follow a generation prompt.

Returns "" on any failure or if all API keys are empty — the renderer
simply omits the summary band.
"""
from __future__ import annotations

import logging

from src.jp_translator import generate

from .collector import SnapshotRow

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
あなたは仮想通貨デリバティブ市場の解説者です。
入力は Hyperliquid 永続スワップ市場の今日のスナップショットです。
日本語で1〜2文(最大100字)、市場の特徴を簡潔に解説してください。
- 必ず句点(。)で完結した完全な文を返す。途中で切れた文は禁止。
- ティッカー(BTC, ETH 等)はそのまま
- 数字を盛り込む
- 「〜です」「〜となっている」等の自然な日本語
- 装飾(絵文字・見出し)なし、本文のみ
"""

USER_TEMPLATE = """\
【建玉(OI)上位】
{top_oi}

【出来高24h上位】
{top_vol}

【ファンディング極端値(年率)】
{funding}
"""


def _row_for_prompt(rows: list[SnapshotRow], metric_label: str) -> str:
    out = []
    for r in rows[:5]:
        if metric_label == "OI":
            metric = f"${r.open_interest_usd / 1e9:.2f}B" if r.open_interest_usd >= 1e9 else f"${r.open_interest_usd / 1e6:.0f}M"
        elif metric_label == "Vol":
            metric = f"${r.day_volume_usd / 1e9:.2f}B" if r.day_volume_usd >= 1e9 else f"${r.day_volume_usd / 1e6:.0f}M"
        elif metric_label == "APR":
            metric = f"{r.funding_apr * 100:+.1f}%"
        else:
            metric = "?"
        change = f"{r.one_day_change * 100:+.1f}%" if r.one_day_change is not None else "—"
        out.append(f"  - {r.market_id}: {metric}, 24h {change}")
    return "\n".join(out)


def generate_summary_jp(
    *,
    top_oi: list[SnapshotRow],
    top_vol: list[SnapshotRow],
    funding: list[SnapshotRow],
    api_key: str = "",  # legacy: Gemini key. Kept for back-compat with job.py.
    model: str | None = None,  # legacy: ignored (jp_translator picks per provider).
    gemini_api_key: str | None = None,
    openai_api_key: str | None = None,
    xai_api_key: str | None = None,
) -> str:
    """Return a 1-line JP summary, or "" on all-provider failure.

    Fallback chain (shared jp_translator package): Gemini → OpenAI → Grok.

    The legacy ``api_key=`` kwarg is treated as the Gemini key so existing
    callers (``job.py``) keep working without modification.

    The actual Gemini model used is whatever ``JP_TRANSLATOR_GEMINI_MODEL``
    is set to (defaults to ``gemini-2.5-flash-lite``). Avoid Gemini 2.5
    "thinking" models (``gemini-2.5-flash``, ``gemini-2.5-pro``) here —
    they reliably eat most of max_output_tokens on hidden reasoning and
    leave the visible text cut mid-sentence (e.g. "…約7"). Non-thinking
    models (2.0-flash, 2.5-flash-lite) produce complete sentences.
    """
    # Backward compat: old call sites pass api_key= as the Gemini key.
    if api_key and not gemini_api_key:
        gemini_api_key = api_key

    user = USER_TEMPLATE.format(
        top_oi=_row_for_prompt(top_oi, "OI"),
        top_vol=_row_for_prompt(top_vol, "Vol"),
        funding=_row_for_prompt(funding, "APR"),
    )

    text = generate(
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=400,
        temperature=0.3,
        gemini_api_key=gemini_api_key,
        openai_api_key=openai_api_key,
        xai_api_key=xai_api_key,
    )

    if not text:
        log.info("market_summary: jp_translator chain returned None")
        return ""

    # Collapse whitespace to a single line.
    text = " ".join(text.split())
    log.info("market_summary: %d chars", len(text))
    return text
