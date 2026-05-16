# Zonetrade Python SDK — AI Reference

This document is structured for **AI-assisted bot development**. When asked
to write a Zonetrade bot, parse this file as reference and produce
working code without hallucinating API surface.

## Authentication

- WS endpoint: `wss://zonetrade.app/external-signals`
- Query string: `?token=<api_key>`
- Get API key: <https://zonetrade.app/integration/api-keys>

Python:
```python
from zonetrade_sdk import Client
client = Client(api_key="zt_your_key")
```

## Channels

### bar.<TF>.<SYMBOL>

**Tier:** free
**Purpose:** Закрытая свеча на timeframe TF для символа SYMBOL.
**TFs:** `1m`, `5m`, `15m`, `1h`, `4h`, `1d`
**Symbols:** все watched (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, ...)

Event JSON:
```json
{
  "event": "bar",
  "channel": "bar.1m.BTCUSDT",
  "data": {
    "symbol": "BTCUSDT",
    "tf": "1m",
    "time": 1778524800,
    "open": 81000,
    "high": 81120,
    "low": 80950,
    "close": 81080,
    "volume": 12.34
  }
}
```

Python model: `zonetrade_sdk.Bar`

Usage:
```python
@client.on("bar")
async def on_bar(bar: Bar):
    if bar.tf == "1m" and bar.symbol == "BTCUSDT":
        print(bar.close)
```

### zone.fvg.<SYMBOL>

**Tier:** free
**Purpose:** Fair Value Gap zone на HTF (1h/4h/1d).
**fillPct:** 0.0 = unfilled, 0.85+ = burned.

Event:
```json
{
  "event": "zone",
  "channel": "zone.fvg.ETHUSDT",
  "data": {
    "symbol": "ETHUSDT",
    "htf": "1h",
    "side": "bullish",
    "top": 2304.18,
    "bottom": 2293.77,
    "firstCandleLow": 2273.69,
    "lastCandleHigh": 2306.41,
    "fillPct": 0.21,
    "formedAt": 1778500800
  }
}
```

Python model: `zonetrade_sdk.FvgZone`

### zone.ob.<SYMBOL>

**Tier:** free
**Purpose:** Order Block zone. body=top-bottom, wick=wickHigh-wickLow (ICT-style).

Python model: `zonetrade_sdk.ObZone`

### structure.choch.<SYMBOL> / structure.bos.<SYMBOL>

**Tier:** free
**Purpose:** Change of character / Break of structure events.

Event:
```json
{
  "event": "structure",
  "channel": "structure.choch.BTCUSDT",
  "data": {
    "symbol": "BTCUSDT",
    "htf": "1h",
    "kind": "choch",
    "direction": "up",
    "price": 81250,
    "time": 1778524800
  }
}
```

Python model: `zonetrade_sdk.StructureEvent`

### setup.three-drive-raw.<SYMBOL>

**Tier:** free
**Purpose:** Raw 3-drive pivot (без HTF trend фильтра).

Python model: `zonetrade_sdk.ThreeDriveRawSetup`

### signal.three-drive-v11.<SYMBOL>

**Tier:** STARTER ($25/mo)
**Purpose:** 3-drive aligned with HTF trend.

Python model: `zonetrade_sdk.ThreeDriveV11Signal`

### signal.trap-flip.<SYMBOL>

**Tier:** PRO ($50/mo)
**Purpose:** Sweep+return через свежий OB protector с 3-drive контекстом.

Event:
```json
{
  "event": "signal",
  "channel": "signal.trap-flip.ETHUSDT",
  "data": {
    "strategy": "trap-flip",
    "version": "v1",
    "symbol": "ETHUSDT",
    "direction": "long",
    "entry": 2302,
    "stop": 2273.69,
    "tp1": 2371.64,
    "rr": 2.46,
    "confirmTime": 1778515740,
    "raw": {
      "magnetZone": {...},
      "protectorOb": {...},
      "tpZone": {...},
      "threeDriveContext": [...]
    }
  }
}
```

Python model: `zonetrade_sdk.TrapFlipSignal`

## SDK API

### `Client(api_key, base_url=..., max_reconnect_delay=30.0)`

Создаёт клиент. `api_key` обязателен.

### `@client.on(event_type)`

Декоратор для регистрации handler'ов. `event_type` может быть:
- Generic: `"bar"`, `"signal"`, `"zone"`, `"structure"`, `"setup"`
- Specific channel: `"signal.trap-flip.BTCUSDT"` — только для него

Handler — async function принимает 1 аргумент (Pydantic model или dict).

### `await client.run(subscribe=[...])`

Подключается + initial subscribe + event loop. Auto-reconnect внутри
(exponential backoff 0.5s → 30s max). Блокирующая.

### `await client.subscribe(channels: list[str])`

Dynamic subscribe после старта.

### `await client.unsubscribe(channels: list[str])`

Dynamic unsubscribe.

### `await client.stop()`

Завершение event loop.

## Common Patterns

### Pattern: Filter signals по RR

```python
@client.on("signal")
async def on_signal(sig):
    if sig.rr < 2.0:
        return  # skip low-RR
    # ... place order
```

### Pattern: Бот следит за несколькими символами

```python
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
subs = [f"signal.trap-flip.{s}" for s in SYMBOLS]
await client.run(subscribe=subs)
```

### Pattern: Сохранение last-N events

```python
from collections import deque

bar_history: dict[str, deque[Bar]] = {}

@client.on("bar")
async def on_bar(bar):
    key = f"{bar.symbol}.{bar.tf}"
    if key not in bar_history:
        bar_history[key] = deque(maxlen=20)
    bar_history[key].append(bar)
```

### Pattern: Combine signal + own indicator filter

```python
volume_spikes: dict[str, list[int]] = {}  # symbol → recent timestamps

@client.on("bar")
async def on_bar(bar):
    if bar.tf != "1m": return
    # ... volume spike detection
    if is_spike(bar):
        volume_spikes.setdefault(bar.symbol, []).append(bar.time)

@client.on("signal")
async def on_signal(sig):
    recent_spikes = volume_spikes.get(sig.symbol, [])
    has_recent = any(t >= sig.confirmTime - 60 for t in recent_spikes)
    if not has_recent:
        return  # no volume confirmation
    # ... place order
```

### Pattern: Graduation to Binance

```python
from binance.client import Client as BN

zt = Client(api_key=os.environ["ZT_API_KEY"])
bn = BN(os.environ["BINANCE_KEY"], os.environ["BINANCE_SECRET"])

@zt.on("signal")
async def on_signal(sig):
    side = "BUY" if sig.direction == "long" else "SELL"
    qty = round(10.0 / abs(sig.entry - sig.stop), 4)  # $10 risk
    bn.futures_create_order(
        symbol=sig.symbol,
        side=side,
        type="STOP_MARKET",
        quantity=qty,
        stopPrice=sig.entry,
        timeInForce="GTC",
    )
```

## Tier Limits

| Tier | Channels | Symbols | Channels total |
|------|----------|---------|----------------|
| Free | bar/zone/structure/setup.three-drive-raw | 5 max | 50 max |
| Starter | + signal.three-drive-v11 | 15 max | 150 max |
| Pro | + signal.trap-flip + все signal.* | 30 (все) | 300 max |
| Premium | + per-detector params override | unlimited | unlimited |

При попытке subscribe на канал выше своего tier — пропускается
с warning в логе. Остальные подписки продолжают работать.

## Pitfalls

### Events во время disconnect — потеряны

SDK auto-reconnect, но event'ы между disconnect и reconnect dropped.
Для critical state (positions) — храните в Redis/DB, восстанавливайте
при reconnect через REST history endpoints.

### Tier downgrade

Если subscription expired → server-side recheck → connection drops.
SDK reconnect'ится, но subscribe на premium-каналы fail'нет с warning.
Bot должен gracefully handle this (например, downgrade strategy).

### Symbol-name case sensitivity

Symbols всегда UPPER CASE в channels: `bar.1m.BTCUSDT`, не `btcusdt`.

## Prompting AI for bot development

**Good prompts:**

> "Создай бота который подписывается на bar.1m.BTCUSDT и считает SMA20.
> Когда close пересекает SMA20 вверх — print 'BUY signal'."

> "Расширь existing bot.py чтобы фильтровать trap-flip signals только
> когда recent volume > 3× SMA20 на 1m."

**Bad prompts:**

- "Напиши торгового бота" — слишком абстрактно
- "Сделай бота как Renko" — мы не предоставляем Renko-bars,
  только OHLC timeframes
