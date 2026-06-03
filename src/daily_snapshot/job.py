"""Hyperliquid daily snapshot orchestrator: fetch → rank → render → post."""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import Settings, load_settings
from ..discord_client import DiscordClient
from ..hyperliquid_client import HyperliquidClient
from .collector import collect_snapshot, funding_extreme, top_open_interest, top_volume
from .image_renderer import render_snapshot_png
from .market_summary import generate_summary_jp
from .x_client import XClient

JST = ZoneInfo("Asia/Tokyo")
log = logging.getLogger(__name__)


def run(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = settings.daily_snapshot

    now = datetime.now(tz=JST)
    log.info("hyperliquid snapshot for %s (dry_run=%s)", now.strftime("%Y-%m-%d %H:%M"), settings.dry_run)

    with HyperliquidClient() as client:
        perps = collect_snapshot(client, min_open_interest_usd=1_000_000)

    if not perps:
        log.warning("no perps after filtering — skipping")
        return

    top_oi = top_open_interest(perps, n=5)
    top_vol = top_volume(perps, n=5)
    funding = funding_extreme(perps, n=5)
    log.info(
        "ranked: %d OI / %d Vol / %d Funding (universe=%d)",
        len(top_oi), len(top_vol), len(funding), len(perps),
    )

    # Optional Japanese summary via jp_translator (Gemini -> OpenAI -> Grok).
    # We gate only on enable_jp_translation here; jp_translator itself reads
    # API keys from env and silently skips providers with no key, so as long
    # as any one of {GEMINI_API_KEY, OPENAI_API_KEY, XAI_API_KEY} is set the
    # chain will produce output. All-empty → returns "" and we just omit the band.
    summary = ""
    if cfg.enable_jp_translation:
        summary = generate_summary_jp(
            top_oi=top_oi,
            top_vol=top_vol,
            funding=funding,
            api_key=settings.gemini_api_key,
            model=cfg.jp_translation_model,
        )

    # Render image
    image_bytes: bytes | None = None
    if cfg.image_mode:
        try:
            image_bytes = render_snapshot_png(
                snapshot_date=now,
                top_oi=top_oi,
                top_vol=top_vol,
                funding=funding,
                universe_size=len(perps),
                market_summary_jp=summary,
            )
            log.info("rendered image: %d bytes", len(image_bytes))
        except Exception as e:
            log.warning("image render failed: %s — proceeding without", e)
            image_bytes = None

    # Caption (X tweet body / Discord fallback text).
    #
    # X enforces a 280 *weighted* character limit where every non-ASCII
    # code point (CJK, emoji, etc.) counts as 2. The previous ``len(caption)``
    # check counted code points only — a 130-codepoint Japanese summary
    # could comfortably pass ``len < 280`` while actually being 260+ weighted
    # plus the attached t.co media URL (+23 weighted), causing X to silently
    # truncate the tweet mid-sentence (e.g. "…約6" cut at codepoint ~50).
    #
    # We now budget on weighted chars and trim the JP summary itself if it
    # would push the caption past the budget, leaving the header + hashtags
    # intact and adding a "…" suffix so readers know it's truncated.
    date_short = f"{now.month}/{now.day:02d}"
    header = f"📊 Hyperliquid Daily Snapshot {date_short} JST"
    hashtags = "#Hyperliquid #Perp #DeFi"
    # X auto-adds the media URL (~23 weighted) to the count even though it's
    # not in our string. Reserve 25 to be safe.
    X_WEIGHTED_LIMIT = 280
    MEDIA_URL_RESERVE = 25 if image_bytes else 0

    def _weighted_len(s: str) -> int:
        return sum(2 if ord(c) > 0x7f else 1 for c in s)

    def _trim_summary(text: str, budget: int) -> str:
        """Trim text so that _weighted_len(text + '…') <= budget."""
        if _weighted_len(text) <= budget:
            return text
        out_chars: list[str] = []
        used = 0
        ellipsis = "…"  # 2 weighted
        room = budget - _weighted_len(ellipsis)
        for ch in text:
            w = 2 if ord(ch) > 0x7f else 1
            if used + w > room:
                break
            out_chars.append(ch)
            used += w
        # Trailing punctuation/whitespace looks better stripped before "…"
        return "".join(out_chars).rstrip("、。, .\n") + ellipsis

    if summary:
        # Caption = header + "\n\n" + summary + "\n\n" + hashtags
        fixed = "\n\n\n\n"  # 4 newlines glue, weighted 4
        scaffold = _weighted_len(header) + _weighted_len(fixed) + _weighted_len(hashtags)
        summary_budget = X_WEIGHTED_LIMIT - MEDIA_URL_RESERVE - scaffold
        trimmed = _trim_summary(summary, max(summary_budget, 0))
        caption = f"{header}\n\n{trimmed}\n\n{hashtags}"
    else:
        caption = f"{header}\n{hashtags}"

    log.info("caption weighted=%d (limit %d, media reserve %d)",
             _weighted_len(caption), X_WEIGHTED_LIMIT, MEDIA_URL_RESERVE)

    # Discord
    if cfg.enable_discord:
        webhook = settings.daily_snapshot_discord_webhook_url
        if not webhook and not settings.dry_run:
            log.warning("discord webhook not configured — skipping")
        else:
            with DiscordClient(webhook, dry_run=settings.dry_run) as dc:
                if image_bytes:
                    dc.send(image_bytes=image_bytes, image_filename="hyperliquid.png")
                else:
                    dc.send(content=caption)
            log.info("discord posted (image=%s)", image_bytes is not None)

    # X
    if cfg.enable_x:
        try:
            xc = XClient(
                api_key=settings.x_api_key,
                api_secret=settings.x_api_secret,
                access_token=settings.x_access_token,
                access_secret=settings.x_access_secret,
                dry_run=settings.dry_run,
            )
        except (ValueError, ImportError) as e:
            log.warning("x client unavailable: %s", e)
        else:
            xc.post(caption, image_bytes=image_bytes)
            log.info("x posted (image=%s)", image_bytes is not None)


if __name__ == "__main__":
    run()
