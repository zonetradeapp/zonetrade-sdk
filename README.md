# Zonetrade Python SDK

Тонкая WebSocket-обёртка для подключения к Zonetrade Bot Platform —
SMC trading signals + market structure stream.

## Quick start

```bash
pip install git+https://github.com/zonetradeapp/zonetrade-sdk
```

Получи API key на <https://zonetrade.app/integration/api-keys>, поставь в env:

```bash
export ZT_API_KEY=zt_your_key
```

Минимальный бот:

```python
import asyncio
import os
from zonetrade_sdk import Client

async def main():
    client = Client(api_key=os.environ["ZT_API_KEY"])

    @client.on("bar")
    async def on_bar(bar):
        print(f"{bar.symbol} {bar.tf} close={bar.close}")

    await client.run(subscribe=["bar.1m.BTCUSDT"])

asyncio.run(main())
```

## Tier-доступ

| Tier | Цена | Каналы |
|------|------|--------|
| **Free** | $0 | `bar.*`, `zone.*`, `structure.*`, raw 3-drive setups |
| **Starter** | $25/мес | + 3-drive с HTF фильтром, структурный поток (FVG, OB, CHoCH, BoS, fractals) |
| **Pro** | $50/мес | + Trap-Flip премиум-сигналы, + $25 за каждую выигрышную сделку |

Купить подписку: <https://zonetrade.app/integration/pricing>

## Документация для AI-агентов

[`claude.md`](./claude.md) — machine-readable reference: все каналы,
event-форматы, type stubs, примеры кода. Просто скинь файл в Claude /
Cursor и попроси сгенерировать бота под твою стратегию.

## Examples

- [`examples/01_subscribe_bars.py`](./examples/01_subscribe_bars.py) — минимум: подключение + bar-стрим.
- [`examples/02_handle_trap_flip.py`](./examples/02_handle_trap_flip.py) — Pro tier: обработка Trap-Flip signal + заглушка для Binance.

Полный набор готовых ботов: [`zonetradeapp/bot-templates`](https://github.com/zonetradeapp/bot-templates).

## License

MIT (см. [LICENSE](./LICENSE))
