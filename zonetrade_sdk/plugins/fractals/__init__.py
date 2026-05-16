"""Fractals plugin — Williams N-bar fractal detector + HH/HL/LH/LL/SH/SL labels.

Использование (Mode A/B — host или dev-bot):
    from zonetrade_sdk import Client
    from zonetrade_sdk.plugins.fractals import FractalsPlugin

    client = Client(api_key=TOKEN)
    client.use(FractalsPlugin(symbols=['BTCUSDT'], tf='1m'))
    await client.run()

Mode C (shared snapshot endpoint) — backend дёргает subprocess'ом:
    python3 -m zonetrade_sdk.plugins.fractals.snapshot_entry
"""

from .plugin_class import FractalsPlugin

__all__ = ["FractalsPlugin"]
