"""Three-Drive plugin — 3-drive setup detector поверх fractals (plugin-composition).

Зависит от `fractals` плагина через HTTP-вызов `/api/plugins/fractals/snapshot` —
один compute на сервере, shared Redis cache для всех потребителей.

Использование (Mode A/B):
    from zonetrade_sdk import Client
    from zonetrade_sdk.plugins.three_drive import ThreeDrivePlugin

    client = Client(api_key=TOKEN)
    client.use(ThreeDrivePlugin(symbols=['BTCUSDT'], tf='15m'))
    await client.run()

Mode C: `python3 -m zonetrade_sdk.plugins.three_drive.snapshot_entry`
"""

from .plugin_class import ThreeDrivePlugin

__all__ = ["ThreeDrivePlugin"]
