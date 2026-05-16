"""Бот: получает trap-flip signals и логирует.

Tier: PRO (signal.trap-flip.* требует Pro подписку).

Можно расширить: вместо print — placing real order на Binance через
python-binance. Это и есть graduation path — тот же бот, разные backends.
"""

import asyncio
import os

from zonetrade_sdk import Client


async def main() -> None:
    client = Client(api_key=os.environ["ZT_API_KEY"])

    @client.on("signal")
    async def on_signal(sig):
        # sig — это TrapFlipSignal Pydantic model (если canал signal.trap-flip.*)
        # или ThreeDriveV11Signal (если signal.three-drive-v11.*).
        if sig.rr < 2.0:
            print(f"[SKIP] {sig.symbol} {sig.direction} RR={sig.rr:.2f} too low")
            return
        print(
            f"[SIGNAL] {sig.strategy} {sig.symbol} {sig.direction}"
            f" entry={sig.entry} stop={sig.stop} tp={sig.tp1} RR={sig.rr:.2f}"
        )
        # TODO: place real order
        # from binance.client import Client as BN
        # bn = BN(os.environ["BINANCE_KEY"], os.environ["BINANCE_SECRET"])
        # bn.futures_create_order(...)

    await client.run(subscribe=[
        "signal.trap-flip.BTCUSDT",
        "signal.trap-flip.ETHUSDT",
        "signal.trap-flip.SOLUSDT",
    ])


if __name__ == "__main__":
    asyncio.run(main())
