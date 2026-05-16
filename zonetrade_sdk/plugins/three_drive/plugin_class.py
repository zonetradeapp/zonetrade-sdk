"""ThreeDrivePlugin — SDK Plugin для Mode A (host) и Mode B (dev-bot).

Plugin-composition (вариант A): этот плагин ЗАВИСИТ от `fractals` plugin
через HTTP-вызов backend'а `/api/plugins/fractals/snapshot`. Не считает
fractals сам — переиспользует shared Redis cache (TTL 60s).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .compute import detect_three_drive
from ...plugin import Plugin

logger = logging.getLogger("zonetrade_sdk.plugins.three_drive")

# Цвет marker'ов drive1/2/3 — совпадает с ThreeDrivePrimitive (Mode C
# полный визуал) для визуальной consistency. Уровни entry/SL/TP рисуются
# через `render_position` → PositionPrimitive со своими дефолт-цветами.
_DRIVE_COLOR = 'rgba(167,139,250,0.95)'


class ThreeDrivePlugin(Plugin):
    """Детектит 3-drive setup'ы поверх fractals plugin, рендерит маркеры + позицию.

    Args:
        symbols: ['*'] / ['auto'] / ['all'] → resolved через
            `client.list_game_watched_pairs()`. Иначе — explicit список.
        tf: timeframe.
        fractal_n: fractal width — пробрасывается в fractals dep.
        respect_inside_candles: пробрасывается в fractals dep.
        min_drive_gap_pct: % gap между drive'ами (0 = строгое неравенство).
        lookback: окно (в fractals) для поиска паттерна.
        ttl_sec: TTL render-объектов.
    """

    name = "three_drive"

    def __init__(
        self,
        symbols: list[str],
        tf: str = "1m",
        fractal_n: int = 2,
        respect_inside_candles: bool = True,
        min_drive_gap_pct: float = 0.0,
        lookback: int = 10,
        ttl_sec: int = 3600,
    ) -> None:
        super().__init__()
        self.symbols = [s.upper() for s in symbols]
        self.tf = tf
        self.fractal_n = fractal_n
        self.respect_inside_candles = respect_inside_candles
        self.min_drive_gap_pct = min_drive_gap_pct
        self.lookback = lookback
        self.ttl_sec = ttl_sec

    async def _fetch_fractals(
        self, http: httpx.AsyncClient, symbol: str,
    ) -> list[dict[str, Any]]:
        """HTTP GET `/api/plugins/fractals/snapshot` — shared Redis cache."""
        resp = await http.get(
            '/api/plugins/fractals/snapshot',
            params={
                'symbol': symbol, 'tf': self.tf,
                'fractalN': self.fractal_n,
                'respectInsideCandles': 1 if self.respect_inside_candles else 0,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        # Symfony оборачивает controller-output в { success, items: <controller> }.
        # Внутри — { cached, cacheKey, data: { items: [...] } }.
        inner = body.get('items') if isinstance(body.get('items'), dict) else body
        data = inner.get('data') or {}
        return data.get('items') or []

    async def on_init(self) -> None:
        assert self._client is not None

        resolved = self.symbols
        if any(s.lower() in ('auto', '*', 'all') for s in resolved):
            try:
                resolved = await self._client.list_game_watched_pairs()
                logger.info("[3drive] auto-resolved to %d pairs", len(resolved))
            except Exception as e:
                logger.warning("[3drive] auto-resolve failed: %s", e)
                resolved = self._client.resolved_signal_symbols()

        async with httpx.AsyncClient(
            base_url=self._client.api_base_url, timeout=15.0,
        ) as http:
            for sym in resolved:
                try:
                    fractals = await self._fetch_fractals(http, sym)
                except Exception as e:
                    logger.warning("[3drive] fractals dep %s failed: %s", sym, e)
                    continue
                drives = detect_three_drive(
                    fractals,
                    min_drive_gap_pct=self.min_drive_gap_pct,
                    lookback=self.lookback,
                )
                logger.info(
                    "[3drive] %s/%s: %d fractals → %d 3-drive setups",
                    sym, self.tf, len(fractals), len(drives),
                )
                for d in drives:
                    await self._render_setup(sym, d)

    async def _render_setup(self, sym: str, d: dict) -> None:
        """Рендер 3-drive setup'а: 3 marker'а на drive'ах + bounded position."""
        drives = d['drives']
        for i, (price, t) in enumerate(drives, start=1):
            await self.render_marker(
                symbol=sym, tf=self.tf,
                price=price, time=t,
                color=_DRIVE_COLOR, label=str(i),
                radius=4, ttl=self.ttl_sec,
            )

        last_price, drive3_time = drives[-1]
        _tf_sec_map = {
            '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
            '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600, '12h': 43200,
            '1d': 86400, '1w': 604800,
        }
        tf_sec = _tf_sec_map.get(self.tf, 60)
        end_time = drive3_time + 10 * tf_sec
        side = 'long' if d['kind'] == '3D-L' else 'short'
        tag = f"{d['kind']} {d['patternType'][:7].upper()}"
        await self.render_position(
            symbol=sym, tf=self.tf, side=side,
            entry=d['entry'], stop=d['sl'], take=d['tpRecovery'],
            time=drive3_time, end_time=end_time,
            tag=tag, ttl=self.ttl_sec,
        )

    async def on_event(self, channel: str, event) -> None:
        pass
