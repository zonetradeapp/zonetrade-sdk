"""SMC Fractals — Williams N-bar fractal detector. Pure compute.

Один источник истины для всех трёх режимов развёртывания плагина:
Mode A (host), Mode B (dev-bot), Mode C (snapshot subprocess). Все три
импортируют этот модуль.

Без внешних зависимостей: только `urllib` + stdlib. Это позволяет
держать `compute` тонким и быстро стартующим в subprocess'е (Mode C
cold start критичен).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


_BYBIT_TF_MAP = {
    '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
    '1h': '60', '2h': '120', '4h': '240', '6h': '360', '12h': '720',
    '1d': 'D', '1w': 'W', '1M': 'M',
}


def fetch_bybit_klines(symbol: str, tf: str, limit: int = 200) -> list[dict]:
    """Bybit v5 linear kline. ASC порядок (старые → новые).

    Каждая свеча: { time (unix sec), open, high, low, close }.
    Bybit отдаёт DESCENDING — реверсим. Open-time used as candle time.
    """
    bybit_tf = _BYBIT_TF_MAP.get(tf, tf)
    params = urllib.parse.urlencode({
        'category': 'linear', 'symbol': symbol,
        'interval': bybit_tf, 'limit': str(limit),
    })
    url = f'https://api.bybit.com/v5/market/kline?{params}'
    req = urllib.request.Request(url, headers={'User-Agent': 'zonetrade-plugin/1.0'})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    if data.get('retCode') != 0:
        raise RuntimeError(f"Bybit error: {data}")
    lst = list(reversed(data['result']['list']))
    return [{
        'time': int(row[0]) // 1000,
        'open': float(row[1]), 'high': float(row[2]),
        'low': float(row[3]), 'close': float(row[4]),
    } for row in lst]


def detect_williams_fractals(
    candles: list[dict],
    n: int = 2,
    respect_inside_candles: bool = True,
) -> list[dict]:
    """Williams N-bar fractal + labelling по последовательности.

    Args:
        candles: ASC list of {time, open, high, low, close}.
        n: fractal width (N=2 → классический 5-bar fractal).
        respect_inside_candles: пропускать inside-bars (свеча целиком
            внутри диапазона предыдущей) при поиске экстремумов.

    Returns:
        list of { idx, kind, price, time } где kind in HH/HL/LH/LL/SH/SL.
    """
    # Маркируем inside-bars если respect_inside_candles=True.
    is_inside = [False] * len(candles)
    if respect_inside_candles:
        for i in range(1, len(candles)):
            if (candles[i]['high'] <= candles[i - 1]['high']
                    and candles[i]['low'] >= candles[i - 1]['low']):
                is_inside[i] = True

    def neighbors_valid(i: int) -> list[int]:
        """N свечей слева + N справа, пропуская inside-bars."""
        left, right = [], []
        k = i - 1
        while k >= 0 and len(left) < n:
            if not is_inside[k]:
                left.append(k)
            k -= 1
        k = i + 1
        while k < len(candles) and len(right) < n:
            if not is_inside[k]:
                right.append(k)
            k += 1
        if len(left) < n or len(right) < n:
            return []
        return left + right

    out: list[dict] = []
    prev_high: dict | None = None
    prev_low: dict | None = None

    for i in range(len(candles)):
        if is_inside[i]:
            continue
        nbrs = neighbors_valid(i)
        if not nbrs:
            continue
        c = candles[i]

        # Fractal high?
        if all(c['high'] > candles[k]['high'] for k in nbrs):
            if prev_high is None:
                kind = 'SH'
            elif c['high'] > prev_high['price']:
                kind = 'HH'
            else:
                kind = 'LH'
            entry = {'idx': i, 'kind': kind, 'price': c['high'], 'time': c['time']}
            out.append(entry)
            prev_high = entry
            continue
        # Fractal low?
        if all(c['low'] < candles[k]['low'] for k in nbrs):
            if prev_low is None:
                kind = 'SL'
            elif c['low'] > prev_low['price']:
                kind = 'HL'
            else:
                kind = 'LL'
            entry = {'idx': i, 'kind': kind, 'price': c['low'], 'time': c['time']}
            out.append(entry)
            prev_low = entry
    return out
