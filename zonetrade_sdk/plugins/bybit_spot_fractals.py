"""BybitSpotFractalsPlugin — independent fractal detector над raw Bybit spot.

Демонстрирует Path B (см. docs): плагин **не использует** наш REST snapshot
и WS structure-stream, а сам ходит к Bybit spot kline-API, считает
Williams fractals в Python, и рисует через render-objects.

Преимущество: плагин может реализовать **свою** definicию fractals
(другой N, другие правила, multi-tf merge, custom labels). Drift с нашим
UI возможен — это by design.

Алгоритм Williams N-bar fractal:
  - bar i это **fractal high** если high[i] > high[i-N..i-1] И high[i] > high[i+1..i+N]
  - bar i это **fractal low**  если low[i]  < low[i-N..i-1]  И low[i]  < low[i+1..i+N]
  - Подтверждается только когда есть N свечей **справа** (= delay N свечей).

Labelling (по последовательности):
  - сравниваем с предыдущим high/low того же типа:
    HH (higher high) / LH (lower high) / HL (higher low) / LL (lower low).
  - первый high/low без предыдущего → SH / SL (swing high/low).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from zonetrade_sdk.plugin import Plugin

logger = logging.getLogger("zonetrade_sdk.plugins.bybit_spot_fractals")

_BYBIT_TF_MAP = {
    '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
    '1h': '60', '2h': '120', '4h': '240', '6h': '360', '12h': '720',
    '1d': 'D', '1w': 'W', '1M': 'M',
}

_FRACTAL_COLORS = {
    'HH': 'rgba(34,197,94,0.95)',
    'HL': 'rgba(34,197,94,0.85)',
    'LH': 'rgba(239,68,68,0.95)',
    'LL': 'rgba(239,68,68,0.85)',
    'SH': 'rgba(148,163,184,0.9)',
    'SL': 'rgba(148,163,184,0.9)',
}


async def fetch_bybit_spot_klines(symbol: str, tf: str, limit: int = 200) -> list[dict]:
    """Bybit spot v5 kline. Возвращает список свечей в ASC-порядке
    (старые → новые) в формате `{time, open, high, low, close, volume}`."""
    bybit_tf = _BYBIT_TF_MAP.get(tf, tf)
    url = (
        f"https://api.bybit.com/v5/market/kline"
        f"?category=spot&symbol={symbol}&interval={bybit_tf}&limit={limit}"
    )
    async with httpx.AsyncClient(timeout=10.0) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        data = r.json()
    if data.get('retCode') != 0:
        raise RuntimeError(f"Bybit kline error: {data}")
    lst = data.get('result', {}).get('list', [])
    # Bybit shows DESCENDING — реверсим в ASC.
    lst = list(reversed(lst))
    return [{
        'time': int(row[0]) // 1000,   # unix sec
        'open': float(row[1]),
        'high': float(row[2]),
        'low': float(row[3]),
        'close': float(row[4]),
        'volume': float(row[5]),
    } for row in lst]


def detect_williams_fractals(
    candles: list[dict],
    n: int = 2,
) -> list[dict]:
    """Williams N-bar fractals + labelling по последовательности.

    Возвращает список `{idx, type, label, price, time}` где
      - type: 'SH' | 'SL' (raw тип pivot'а — high/low)
      - label: 'HH' | 'HL' | 'LH' | 'LL' | 'SH' | 'SL'
    """
    out: list[dict] = []
    prev_high: dict | None = None
    prev_low: dict | None = None
    for i in range(n, len(candles) - n):
        c = candles[i]
        # Fractal high?
        is_high = all(
            c['high'] > candles[i - k]['high'] and c['high'] > candles[i + k]['high']
            for k in range(1, n + 1)
        )
        if is_high:
            if prev_high is None:
                label = 'SH'
            elif c['high'] > prev_high['price']:
                label = 'HH'
            else:
                label = 'LH'
            entry = {'idx': i, 'type': 'SH', 'label': label,
                     'price': c['high'], 'time': c['time']}
            out.append(entry)
            prev_high = entry
            continue  # одна свеча — один pivot (high ИЛИ low, не оба)
        # Fractal low?
        is_low = all(
            c['low'] < candles[i - k]['low'] and c['low'] < candles[i + k]['low']
            for k in range(1, n + 1)
        )
        if is_low:
            if prev_low is None:
                label = 'SL'
            elif c['low'] > prev_low['price']:
                label = 'HL'
            else:
                label = 'LL'
            entry = {'idx': i, 'type': 'SL', 'label': label,
                     'price': c['low'], 'time': c['time']}
            out.append(entry)
            prev_low = entry
    return out


class BybitSpotFractalsPlugin(Plugin):
    """Считает fractals на Bybit spot — независимо от нашего детектора.

    Args:
        symbols: список Bybit spot символов (BTCUSDT, ETHUSDT, ...).
        tf: timeframe.
        n: fractal width (N=2 → 5-bar williams, N=1 → 3-bar чаще).
        limit: глубина истории (max 1000 у Bybit).
        ttl_sec: TTL render-labels.
    """

    name = "bybit-spot-fractals"

    def __init__(
        self,
        symbols: list[str],
        tf: str = "1m",
        n: int = 2,
        limit: int = 200,
        ttl_sec: int = 3600,
    ) -> None:
        super().__init__()
        self.symbols = [s.upper() for s in symbols]
        self.tf = tf
        self.n = n
        self.limit = limit
        self.ttl_sec = ttl_sec

    async def on_init(self) -> None:
        assert self._client is not None
        resolved = self.symbols
        if any(s.lower() in ('auto', '*', 'all') for s in resolved):
            try:
                resolved = await self._client.list_game_watched_pairs()
            except Exception:
                resolved = self._client.resolved_signal_symbols()
        for sym in resolved:
            try:
                candles = await fetch_bybit_spot_klines(sym, self.tf, self.limit)
            except Exception as e:
                logger.warning("[bybit-spot] fetch %s/%s failed: %s", sym, self.tf, e)
                continue
            fractals = detect_williams_fractals(candles, n=self.n)
            logger.info(
                "[bybit-spot] %s/%s: %d свечей → %d fractals (N=%d)",
                sym, self.tf, len(candles), len(fractals), self.n,
            )
            for fr in fractals:
                color = _FRACTAL_COLORS.get(fr['label'], _FRACTAL_COLORS['SH'])
                # Префикс '*' чтоб отличить визуально от Path A на чарте
                # (если оба бота крутятся).
                label = f"*{fr['label']}"
                await self.render_marker(
                    symbol=sym,
                    tf=self.tf,
                    price=fr['price'],
                    time=fr['time'],
                    color=color,
                    label=label,
                    ttl=self.ttl_sec,
                )

    async def on_event(self, channel: str, event: Any) -> None:
        # Path B не подписан на наш WS — он dependent от Bybit. На запуске
        # отрисовали всё, далее юзер пере-запускает бот для refresh'а
        # (или добавляет периодический task — расширение для следующей итерации).
        pass
