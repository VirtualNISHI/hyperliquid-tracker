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

    # Caption (X tweet body / Discord fallback text)
    date_short = f"{now.month}/{now.day:02d}"
    if summary:
        caption = (
            f"📊 Hyperliquid Daily Snapshot {date_short} JST\n"
            f"\n{summary}\n"
            f"\n#Hyperliquid #Perp #DeFi"
        )
    else:
        caption = (
            f"📊 Hyperliquid Daily Snapshot {date_short} JST\n"
            "#Hyperliquid #Perp #DeFi"
        )
    if len(caption) > 280:
        caption = caption[:277] + "..."

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
