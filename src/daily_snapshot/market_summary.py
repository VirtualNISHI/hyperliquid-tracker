"""Generate a 1-line Japanese market summary via Gemini.

Given the three ranked sections (Top OI / Top Volume / Funding Extreme),
ask Gemini to summarize the Hyperliquid perp market state in 1-2 short
Japanese sentences (max ~120 chars). Returns "" on any failure or if
``api_key`` is empty — the renderer simply omits the summary band.
"""
from __future__ import annotations

import logging

from .collector import SnapshotRow

log = logging.getLogger(__name__)

PROMPT_TEMPLATE = """\
あなたは仮想通貨デリバティブ市場の解説者です。
以下は Hyperliquid 永続スワップ市場の今日のスナップショットです。
日本語で1〜2文(最大120字)、市場の特徴を簡潔に解説してください。
- ティッカー(BTC, ETH 等)はそのまま
- 数字を盛り込む
- 「〜です」「〜となっている」等の自然な日本語
- 装飾(絵文字・見出し)なし、本文のみ

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
    api_key: str,
    model: str = "gemini-2.5-flash-lite",
) -> str:
    if not api_key:
        log.info("gemini api key not set, skipping market summary")
        return ""

    try:
        from google import genai
    except ImportError:
        log.warning("google-genai not installed, skipping summary")
        return ""

    prompt = PROMPT_TEMPLATE.format(
        top_oi=_row_for_prompt(top_oi, "OI"),
        top_vol=_row_for_prompt(top_vol, "Vol"),
        funding=_row_for_prompt(funding, "APR"),
    )

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        text = (resp.text or "").strip()
        text = " ".join(text.split())
        log.info("gemini summary: %d chars", len(text))
        return text
    except Exception as e:
        log.warning("gemini summary failed: %s", e)
        return ""
