"""FractalsPlugin — SDK Plugin class для Mode A (host) и Mode B (dev-bot).

Использует ту же `compute.detect_williams_fractals` что и Mode C
snapshot_entry. Один источник истины для алгоритма — менять Williams
в `compute.py`, оба runtime'а автоматически обновляются.
"""

from __future__ import annotations

import logging

from .compute import detect_williams_fractals, fetch_bybit_klines
from ...plugin import Plugin

logger = logging.getLogger("zonetrade_sdk.plugins.fractals")

# Цветовые defaults для рендера. Можно переопределить через params при
# инстанциировании, но для большинства юзеров — этих хватит.
_DEFAULT_COLORS = {
    'HH': 'rgba(34,197,94,0.95)',
    'HL': 'rgba(34,197,94,0.85)',
    'LH': 'rgba(239,68,68,0.95)',
    'LL': 'rgba(239,68,68,0.85)',
    'SH': 'rgba(148,163,184,0.9)',
    'SL': 'rgba(148,163,184,0.9)',
}


class FractalsPlugin(Plugin):
    """Считает фракталы для каждой пары/TF, рендерит как markers.

    Args:
        symbols: ['*'] / ['auto'] / ['all'] → resolved через
            `client.list_game_watched_pairs()`. Иначе — explicit список.
        tf: timeframe ('1m'/'5m'/...).
        n: fractal width (1..3).
        respect_inside_candles: пропускать inside-bars.
        limit: глубина истории (max 1000 у Bybit).
        ttl_sec: TTL render-marker'ов (1ч default).
    """

    name = "fractals"

    def __init__(
        self,
        symbols: list[str],
        tf: str = "1m",
        n: int = 2,
        respect_inside_candles: bool = True,
        limit: int = 200,
        ttl_sec: int = 3600,
    ) -> None:
        super().__init__()
        self.symbols = [s.upper() for s in symbols]
        self.tf = tf
        self.n = n
        self.respect_inside_candles = respect_inside_candles
        self.limit = limit
        self.ttl_sec = ttl_sec

    async def on_init(self) -> None:
        assert self._client is not None
        # 'auto' / '*' / 'all' → все game-watched пары.
        resolved = self.symbols
        if any(s.lower() in ('auto', '*', 'all') for s in resolved):
            try:
                resolved = await self._client.list_game_watched_pairs()
                logger.info("[fractals] auto-resolved to %d pairs", len(resolved))
            except Exception as e:
                logger.warning("[fractals] auto-resolve failed: %s", e)
                resolved = self._client.resolved_signal_symbols()

        for sym in resolved:
            try:
                candles = fetch_bybit_klines(sym, self.tf, limit=self.limit)
            except Exception as e:
                logger.warning("[fractals] kline fetch %s failed: %s", sym, e)
                continue
            fractals = detect_williams_fractals(
                candles, n=self.n,
                respect_inside_candles=self.respect_inside_candles,
            )
            logger.info(
                "[fractals] %s/%s: %d candles → %d fractals (N=%d)",
                sym, self.tf, len(candles), len(fractals), self.n,
            )
            for fr in fractals:
                color = _DEFAULT_COLORS.get(fr['kind'], _DEFAULT_COLORS['SH'])
                await self.render_marker(
                    symbol=sym, tf=self.tf,
                    price=fr['price'], time=fr['time'],
                    color=color, label=fr['kind'],
                    ttl=self.ttl_sec,
                )

    async def on_event(self, channel: str, event) -> None:
        # MVP: только snapshot на init. Live updates через polling — TBD.
        pass
