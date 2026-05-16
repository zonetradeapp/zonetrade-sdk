"""Модели для REST `/api/structure/snapshot` — текущее состояние структуры
(fractals + BoS/CHoCH + FVG + OB зоны) за заданное окно свечей.

Используется ботами при подключении чтобы получить картину «сейчас» до
того как WS начнёт стримить delta-events.

Пример:
    client = Client(api_key="zt_...")
    snap = await client.get_structure_snapshot("BTCUSDT", "1m", window_bars=100)
    for fr in snap.fractals:
        print(fr.label, fr.price, fr.timeMs)
    await client.subscribe(["structure.fractal.1m.BTCUSDT"])
"""

from typing import Literal

from pydantic import BaseModel, Field


class SnapshotWindow(BaseModel):
    """Окно за которое посчитан snapshot."""

    fromMs: int | None = None
    toMs: int | None = None
    bars: int
    fractalN: int
    respectInsideCandles: bool


class SnapshotFractal(BaseModel):
    """Свинг (HH/HL/LH/LL/SH/SL). `type` — raw тип (SH/SL), `label` —
    классифицированный (HH/HL/LH/LL или SH/SL если ещё нет
    предыдущего свинга для сравнения)."""

    idx: int
    type: Literal["SH", "SL"]
    label: Literal["HH", "HL", "LH", "LL", "SH", "SL"]
    price: float
    timeMs: int


class SnapshotBosEvent(BaseModel):
    """BoS (Break of Structure) или CHoCH (Change of Character).
    `brokenLevel` — цена сломанного свинга, `timeMs` — когда свеча
    закрылась за уровнем."""

    idx: int
    kind: Literal["bos", "choch"]
    direction: Literal["up", "down"]
    brokenLevel: float | None = None
    brokenIdx: int | None = None
    timeMs: int = Field(description="Unix ms когда подтвердился break (confirm-свеча)")


class SnapshotTouch(BaseModel):
    """Один entry-exit зоны (для расчёта mitigation)."""

    entryIdx: int
    exitIdx: int | None = None
    entryTimeMs: int
    exitTimeMs: int | None = None


class SnapshotFvgZone(BaseModel):
    """Fair Value Gap зона. `mitigated=True` если уже было касание."""

    topIdx: int
    bottomIdx: int
    impulseIdx: int | None = None
    top: float
    bottom: float
    direction: Literal["bullish", "bearish"]
    mitigated: bool
    touches: list[SnapshotTouch] = Field(default_factory=list)
    timeMs: int


class SnapshotObZone(BaseModel):
    """Order Block зона. `idx` — индекс sweep-свечи, `engulfIdx` —
    свечи закрывшейся за sweep'ом."""

    idx: int
    engulfIdx: int
    top: float
    bottom: float
    direction: Literal["bullish", "bearish"]
    subtype: str | None = None
    mitigated: bool
    touches: list[SnapshotTouch] = Field(default_factory=list)
    timeMs: int


class StructureSnapshot(BaseModel):
    """Полный snapshot структуры для одного символа/TF на момент `window.toMs`.

    Возвращается `Client.get_structure_snapshot(...)`. Поля mirror
    payload backend'а (StructureController::snapshot)."""

    symbol: str
    tf: str
    window: SnapshotWindow
    fractals: list[SnapshotFractal] = Field(default_factory=list)
    bosEvents: list[SnapshotBosEvent] = Field(default_factory=list)
    fvgZones: list[SnapshotFvgZone] = Field(default_factory=list)
    obZones: list[SnapshotObZone] = Field(default_factory=list)
    lastBosDirection: Literal["up", "down"] | None = None
