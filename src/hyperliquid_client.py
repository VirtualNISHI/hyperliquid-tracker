"""Hyperliquid public REST API client.

Endpoint: ``POST https://api.hyperliquid.xyz/info``
Authentication: none. Rate limit: generous for read-only meta calls.

The single ``metaAndAssetCtxs`` body returns everything we need for the
daily snapshot:
- ``meta.universe[i]``: {name, szDecimals, maxLeverage}
- ``assetCtxs[i]``: {markPx, prevDayPx, dayNtlVlm, openInterest, funding, ...}

The ``i`` index is 1-to-1 between universe and assetCtxs. We zip them into
``HyperliquidPerp`` records that downstream code consumes.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import httpx

log = logging.getLogger(__name__)

INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass
class HyperliquidPerp:
    coin: str                  # ticker, e.g. "BTC"
    mark_price_usd: float      # current mark price
    prev_day_price_usd: float  # 24h ago price
    day_volume_usd: float      # 24h notional volume in USD
    open_interest_coin: float  # OI in coin units
    open_interest_usd: float   # OI × mark_price
    funding_rate_hourly: float # current 1h funding rate (e.g. 0.0000125 = 0.00125%/h)
    max_leverage: int

    @property
    def price_change_24h_pct(self) -> float | None:
        """24h price change as a fraction (0.05 = +5%)."""
        if self.prev_day_price_usd == 0:
            return None
        return (self.mark_price_usd - self.prev_day_price_usd) / self.prev_day_price_usd

    @property
    def funding_rate_apr(self) -> float:
        """Annualized funding rate (×24×365). Positive = longs pay shorts."""
        return self.funding_rate_hourly * 24 * 365


class HyperliquidClient:
    def __init__(self, *, user_agent: str = "hyperliquid-tracker/0.1", timeout: float = 15.0):
        self._headers = {"User-Agent": user_agent, "Content-Type": "application/json"}
        self._timeout = timeout
        self._client: httpx.Client | None = None

    def __enter__(self) -> "HyperliquidClient":
        self._client = httpx.Client(headers=self._headers, timeout=self._timeout)
        return self

    def __exit__(self, *exc) -> None:
        if self._client:
            self._client.close()

    def fetch_all_perps(self) -> list[HyperliquidPerp]:
        """One call returns every active perpetual on Hyperliquid."""
        assert self._client is not None, "use as context manager"
        resp = self._client.post(INFO_URL, json={"type": "metaAndAssetCtxs"})
        resp.raise_for_status()
        data = resp.json()
        meta, ctxs = data
        universe = meta["universe"]

        out: list[HyperliquidPerp] = []
        for u, c in zip(universe, ctxs):
            try:
                mark = float(c["markPx"])
                prev = float(c["prevDayPx"])
                vol = float(c["dayNtlVlm"])
                oi_coin = float(c["openInterest"])
                funding = float(c["funding"])
            except (KeyError, ValueError, TypeError) as e:
                log.warning("skipping %s: malformed ctx (%s)", u.get("name"), e)
                continue

            out.append(
                HyperliquidPerp(
                    coin=u["name"],
                    mark_price_usd=mark,
                    prev_day_price_usd=prev,
                    day_volume_usd=vol,
                    open_interest_coin=oi_coin,
                    open_interest_usd=oi_coin * mark,
                    funding_rate_hourly=funding,
                    max_leverage=int(u.get("maxLeverage", 0)),
                )
            )
        log.info("hyperliquid: fetched %d perpetuals", len(out))
        return out


@contextmanager
def open_client(user_agent: str = "hyperliquid-tracker/0.1") -> Iterator[HyperliquidClient]:
    with HyperliquidClient(user_agent=user_agent) as c:
        yield c
