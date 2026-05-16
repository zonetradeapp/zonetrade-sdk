"""Mode C entry — stdin/stdout subprocess для 3-drive плагина.

Backend (PluginSnapshotController) спавнит как module:
    python3 -m zonetrade_sdk.plugins.three_drive.snapshot_entry

Plugin-composition (вариант A): этот скрипт НЕ считает fractals сам.
HTTP-запрос к `/api/plugins/fractals/snapshot?...` того же backend'а —
shared Redis cache (60s TTL).

Контракт:
  stdin:  JSON {
    symbol, tf,
    fractalN?, respectInsideCandles?,
    minDriveGapPct?, lookback?,
    apiBase?
  }
  stdout: JSON { items: [ { type:'three-drive', drives, entry, sl, ... } ] }
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

from .compute import detect_three_drive


def _fetch_fractals(
    api_base: str, symbol: str, tf: str,
    fractal_n: int, respect_inside: bool,
) -> list[dict]:
    """HTTP GET /api/plugins/fractals/snapshot — same backend, shared cache."""
    qs = urllib.parse.urlencode({
        'symbol': symbol, 'tf': tf,
        'fractalN': fractal_n,
        'respectInsideCandles': 1 if respect_inside else 0,
    })
    url = f"{api_base.rstrip('/')}/api/plugins/fractals/snapshot?{qs}"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'zonetrade-plugin-three-drive/1.0',
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        body = json.loads(resp.read())
    # Symfony оборачивает controller-output в { success, items: <controller> }.
    inner = body.get('items') if isinstance(body.get('items'), dict) else body
    data = inner.get('data') or {}
    return data.get('items') or []


def main() -> None:
    try:
        params = json.loads(sys.stdin.read())
    except Exception as e:
        sys.stdout.write(json.dumps({'error': f'invalid_input: {e}'}))
        sys.exit(1)

    symbol = (params.get('symbol') or '').upper()
    tf = params.get('tf') or '1m'
    if not symbol:
        sys.stdout.write(json.dumps({'error': 'missing_symbol'}))
        sys.exit(0)

    fractal_n = int(params.get('fractalN', 2))
    respect_inside = bool(int(params.get('respectInsideCandles', 1)))
    min_gap_pct = float(params.get('minDriveGapPct', 0)) / 100.0
    lookback = int(params.get('lookback', 10))

    api_base = (
        params.get('apiBase')
        or os.environ.get('ZONETRADE_API_INTERNAL')
        or os.environ.get('ZONETRADE_API_BASE')
        or 'http://trading_nginx'
    )

    try:
        fractals = _fetch_fractals(api_base, symbol, tf, fractal_n, respect_inside)
    except Exception as e:
        sys.stdout.write(json.dumps({'error': f'fractals_dep_failed: {e}'}))
        sys.exit(0)

    drives = detect_three_drive(
        fractals, min_drive_gap_pct=min_gap_pct, lookback=lookback,
    )

    _TF_SEC = {
        '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
        '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600, '12h': 43200,
        '1d': 86400, '1w': 604800, '1M': 2592000,
    }
    tf_sec = _TF_SEC.get(tf, 60)

    items = []
    for d in drives:
        drive3_time = d['drives'][-1][1]
        items.append({
            'type': 'three-drive',
            'kind': d['kind'],
            'direction': d['direction'],
            'patternType': d['patternType'],
            'drives': [{'price': p, 'time': t} for (p, t) in d['drives']],
            'entry': d['entry'],
            'sl': d['sl'],
            'tpRecovery': d['tpRecovery'],
            'chochTime': drive3_time + d['chochOffset'] * tf_sec,
            'retraceTime': drive3_time + d['retraceOffset'] * tf_sec,
            'entryTime': drive3_time + d['entryOffset'] * tf_sec,
        })
    sys.stdout.write(json.dumps({'items': items}))


if __name__ == '__main__':
    main()
