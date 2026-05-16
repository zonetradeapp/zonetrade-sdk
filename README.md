# Zonetrade Python SDK

Thin WebSocket wrapper for the Zonetrade Bot Platform — SMC trading
signals + market structure stream.

## Quick start

```bash
pip install git+https://github.com/zonetradeapp/zonetrade-sdk
```

Get an API key at <https://zonetrade.app/integration/api-keys> and set it in env:

```bash
export ZT_API_KEY=zt_your_key
```

Minimal bot:

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

## Reference for AI agents

[`claude.md`](./claude.md) — machine-readable reference: all channels,
event formats, type stubs, code samples. Drop the file into Claude /
Cursor context and ask the model to generate a bot for your strategy.

## Examples

- [`examples/01_subscribe_bars.py`](./examples/01_subscribe_bars.py) — minimal: connect + bar stream.
- [`examples/02_handle_trap_flip.py`](./examples/02_handle_trap_flip.py) — Pro tier: handle Trap-Flip signal + Binance integration stub.

Full set of ready-made bots: [`zonetradeapp/bot-templates`](https://github.com/zonetradeapp/bot-templates).

## License

MIT (see [LICENSE](./LICENSE))
