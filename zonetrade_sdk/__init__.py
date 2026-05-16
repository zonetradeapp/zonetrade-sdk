"""
Zonetrade Python SDK — WebSocket client for SMC trading signals.

Quick start:
    from zonetrade_sdk import Client

    client = Client(api_key="zt_...")

    @client.on("bar")
    async def on_bar(bar):
        print(f"{bar.symbol} {bar.tf} close={bar.close}")

    @client.on("signal")
    async def on_signal(sig):
        print(f"SIGNAL {sig.strategy}: {sig.symbol} {sig.direction}")

    await client.run(subscribe=["bar.1m.BTCUSDT", "signal.trap-flip.BTCUSDT"])

See `claude.md` for full channel reference and event schemas.
"""

from zonetrade_sdk.client import Client
from zonetrade_sdk.events import (
    Account,
    Bar,
    FractalEvent,
    FvgZone,
    ObZone,
    ObZoneEvent,
    Order,
    OrderCancelResult,
    OrderEvent,
    StructureEvent,
    ThreeDriveRawSetup,
    TrapFlipSignal,
    ThreeDriveV11Signal,
)
from zonetrade_sdk.exceptions import (
    AuthError,
    ConnectionError,
    OrderError,
    TierRequiredError,
)
from zonetrade_sdk.plugin import Plugin
from zonetrade_sdk.plugins.fractals import FractalsPlugin
from zonetrade_sdk.plugins.bybit_spot_fractals import BybitSpotFractalsPlugin
from zonetrade_sdk.render import (
    RenderObject,
    RenderObjectCreated,
)
from zonetrade_sdk.structure import (
    SnapshotBosEvent,
    SnapshotFractal,
    SnapshotFvgZone,
    SnapshotObZone,
    SnapshotTouch,
    SnapshotWindow,
    StructureSnapshot,
)

__version__ = "0.1.0"
__all__ = [
    "Client",
    "Account",
    "Bar",
    "FractalEvent",
    "FvgZone",
    "ObZone",
    "ObZoneEvent",
    "Order",
    "OrderCancelResult",
    "OrderEvent",
    "StructureEvent",
    "ThreeDriveRawSetup",
    "TrapFlipSignal",
    "ThreeDriveV11Signal",
    "StructureSnapshot",
    "SnapshotWindow",
    "SnapshotFractal",
    "SnapshotBosEvent",
    "SnapshotFvgZone",
    "SnapshotObZone",
    "SnapshotTouch",
    "RenderObject",
    "RenderObjectCreated",
    "Plugin",
    "FractalsPlugin",
    "BybitSpotFractalsPlugin",
    "AuthError",
    "ConnectionError",
    "OrderError",
    "TierRequiredError",
]
