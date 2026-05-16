"""Минимальный пример: подключение + подписка на bar-events.

Запуск:
    pip install zonetrade-sdk
    export ZT_API_KEY=zt_your_key
    python 01_subscribe_bars.py

Что делает: подписывается на 1m bar events для BTC и ETH, печатает close.
Tier: free (bar.* доступен всем).
"""

import asyncio
import os

from zonetrade_sdk import Client


async def main() -> None:
    client = Client(api_key=os.environ["ZT_API_KEY"])

    @client.on("bar")
    async def on_bar(bar):
        print(f"[bar] {bar.symbol} {bar.tf} close={bar.close} vol={bar.volume}")

    await client.run(subscribe=[
        "bar.1m.BTCUSDT",
        "bar.1m.ETHUSDT",
    ])


if __name__ == "__main__":
    asyncio.run(main())
