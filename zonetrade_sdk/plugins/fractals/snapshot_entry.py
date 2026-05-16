"""Mode C entry — stdin/stdout subprocess для shared snapshot endpoint.

Backend (PluginSnapshotController) спавнит как module:
    python3 -m zonetrade_sdk.plugins.fractals.snapshot_entry

Использует ту же `compute.detect_williams_fractals` что и `plugin_class.py`
— один Python-алгоритм на оба runtime'а.

Контракт:
  stdin:  JSON { symbol, tf, fractalN?, respectInsideCandles? }
  stdout: JSON { items: [ { type:'marker', kind, price, time }, ... ] }
"""

from __future__ import annotations

import json
import sys

from .compute import detect_williams_fractals, fetch_bybit_klines


def main() -> None:
    try:
        params = json.loads(sys.stdin.read())
    except Exception as e:
        sys.stdout.write(json.dumps({'error': f'invalid_input: {e}'}))
        sys.exit(1)

    symbol = (params.get('symbol') or '').upper()
    tf = params.get('tf') or '1m'
    fractal_n = int(params.get('fractalN', 2))
    respect_inside = bool(int(params.get('respectInsideCandles', 1)))

    if not symbol:
        sys.stdout.write(json.dumps({'error': 'missing_symbol'}))
        sys.exit(0)

    try:
        candles = fetch_bybit_klines(symbol, tf, limit=200)
    except Exception as e:
        sys.stdout.write(json.dumps({'error': f'kline_fetch_failed: {e}'}))
        sys.exit(0)

    fractals = detect_williams_fractals(
        candles, n=fractal_n, respect_inside_candles=respect_inside,
    )

    items = [{
        'type': 'marker',
        'kind': fr['kind'],
        'price': fr['price'],
        'time': fr['time'],
    } for fr in fractals]
    sys.stdout.write(json.dumps({'items': items}))


if __name__ == '__main__':
    main()
