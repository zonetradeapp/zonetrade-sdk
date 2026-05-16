"""Pydantic models для WS events от Zonetrade.

Каждый канал имеет свой event-тип. SDK при получении сообщения
определяет тип по `event` полю и парсит в соответствующую модель.

Использование:
    @client.on("bar")
    async def on_bar(bar: Bar):  # type hint работает с Pydantic
        if bar.tf == "1m" and bar.symbol == "BTCUSDT":
            print(bar.close)
"""

from typing import Literal

from pydantic import BaseModel, Field


class Bar(BaseModel):
    """Закрытая свеча на timeframe. Источник: bar.<TF>.<SYMBOL> channel."""

    symbol: str
    # Канонический список TF — см. assets/chartview/app/pages/index.vue:TIMEFRAMES.
    # Publisher (bybit-kline-publisher) сейчас шлёт только subset, но модель не
    # ограничиваем чтобы не падать на новые TF когда publisher расширится.
    tf: Literal["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
    time: int = Field(description="Unix timestamp начала бара, секунды")
    open: float
    high: float
    low: float
    close: float
    volume: float


class FvgZone(BaseModel):
    """Fair Value Gap зона на HTF. Источник: zone.fvg.<SYMBOL> channel.

    fillPct < 0.33 = "свежая" (мало заполнена).
    fillPct >= 0.85 = "сожжённая" (почти полностью пробита).
    """

    symbol: str
    htf: str = Field(description="Timeframe на котором найдена зона (1h/4h/1d)")
    side: Literal["bullish", "bearish"]
    top: float
    bottom: float
    firstCandleLow: float
    lastCandleHigh: float
    fillPct: float = Field(description="Deepest penetration / span, 0.0-1.0")
    formedAt: int = Field(description="Unix sec когда зона сформировалась")


class ObZone(BaseModel):
    """Order Block зона. Источник: zone.ob.<SYMBOL> channel.

    body = top-bottom (нижняя свеча engulfment'а).
    wick = wickHigh-wickLow (full candle range, ICT-style).
    """

    symbol: str
    htf: str
    side: Literal["bullish", "bearish"]
    top: float
    bottom: float
    wickHigh: float
    wickLow: float
    fillPct: float
    formedAt: int


class StructureEvent(BaseModel):
    """CHoCH или BoS event. Источник: `structure.<kind>.<TF>.<SYMBOL>` channel.

    Эмиссия из cron-детектора (см. detect-game-setups.mjs). Kind дублируется
    в data.kind для удобства handler-логики."""

    kind: Literal["bos", "choch"]
    symbol: str
    timeframe: str
    direction: Literal["up", "down"]
    brokenLevel: float | None = None
    brokenIdx: int | None = None
    confirmIdx: int
    confirmTimeMs: int = Field(description="Unix ms когда подтвердился break")


class FractalEvent(BaseModel):
    """Новый свинг (HH/HL/LH/LL/SH/SL). Источник: `structure.fractal.<TF>.<SYMBOL>`.

    Подтверждается через fractalN свечей после самого свинга
    (default N=2 → задержка 2 свечи)."""

    kind: Literal["fractal"] = "fractal"
    symbol: str
    timeframe: str
    type: Literal["HH", "HL", "LH", "LL", "SH", "SL"]
    price: float
    idx: int
    timeMs: int


class ObZoneEvent(BaseModel):
    """Новая OB-зона (sweep+engulf). Источник: `zone.ob.<TF>.<SYMBOL>` channel."""

    kind: Literal["ob"] = "ob"
    symbol: str
    timeframe: str
    direction: Literal["bullish", "bearish"]
    subtype: str | None = None
    top: float
    bottom: float
    sweepIdx: int
    sweepTimeMs: int
    engulfIdx: int
    engulfTimeMs: int
    mitigated: bool


class ThreeDriveRawSetup(BaseModel):
    """Raw 3-drive pivot (без HTF trend фильтра).

    Источник: setup.three-drive-raw.<SYMBOL> channel.
    Bear in mind: это RAW pivot — может быть counter-trend. Бот сам
    решает применять ли HTF-фильтр.

    Поля entry/stop/tp1-3/rr дублируют те же что у ThreeDriveV11Signal —
    raw payload отдаёт их параллельно с confirmPrice/targets чтобы
    bot-template'ы могли использовать setup как free-tier источник
    paper-ордеров без отдельной парсинг-логики.
    """

    strategy: Literal["three-drive"] = "three-drive"
    version: Literal["raw"] = "raw"
    symbol: str
    # Канонический список TF берётся из chartview (TIMEFRAMES в pages/index.vue).
    # Опционален до того как publisher научится передавать поле в payload.
    tf: Literal["1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"] | None = None
    direction: Literal["long", "short"]
    confirmIdx: int
    confirmPrice: float
    confirmTime: int
    drives: list[dict] = Field(default_factory=list)
    targets: list[float] = Field(default_factory=list)
    # Опциональные — старые публикации до 2026-05-12 могли не содержать.
    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    tp3: float | None = None
    rr: float | None = None


class ThreeDriveV11Signal(BaseModel):
    """3-drive setup aligned с HTF trend (V11). Tier: STARTER.

    Источник: signal.three-drive-v11.<SYMBOL> channel.
    """

    strategy: Literal["three-drive"] = "three-drive"
    version: str = "v11"
    symbol: str
    direction: Literal["long", "short"]
    entry: float
    stop: float
    tp1: float
    tp2: float | None = None
    tp3: float | None = None
    rr: float
    confirmTime: int
    raw: dict | None = Field(default=None, description="Полный контекст setup'а")


class Order(BaseModel):
    """Paper-ордер на нашей виртуальной бирже. Возвращается v1 REST API
    (`/api/v1/orders/*`). Tier: создание ордеров доступно всем юзерам
    с валидным API key (paper-trading, не реальная биржа).

    Статусы:
      - `wait` — лимит/стоп-маркет создан, ждём price-trigger
      - `active` — активирован, есть открытый Trade'ы
      - `closed` — все Trade'ы закрыты (TP/SL/manual)
      - `cancelled` — отменён до активации
    """

    id: int
    symbol: str
    side: Literal["long", "short"]
    type: Literal["limit", "stop_market"]
    status: Literal["wait", "active", "closed", "cancelled"]
    strategy: Literal["single_tp", "multi_tp_be"]
    entry: float
    stop: float | None = None
    tp: float | None = None
    quantity: float
    signalId: int | None = None
    createdAt: str
    filledAt: str | None = None
    cancelledAt: str | None = None


class OrderEvent(BaseModel):
    """Push-уведомление о смене статуса ордера. Источник: `user.<id>.order`
    WS-канал. SDK подписывается на канал после `place_order(...)` чтобы
    знать когда ордер filled/closed без polling'а REST API.

    `action`: что произошло.
    `reason`: для action='closed' — что закрыло (tp/sl/manual). Для
              остальных action — None.

    Handler:
        @client.on("order")
        async def on_order(ev: OrderEvent):
            if ev.action == "closed":
                print(f"order #{ev.orderId} {ev.reason} pnl={ev.pnl}")
    """

    action: Literal["filled", "closed", "cancelled", "invalidated"]
    reason: Literal["tp", "sl", "manual"] | None = None
    ts: int = Field(description="Unix ms когда событие произошло на backend'е")
    orderId: int | None = None
    symbol: str | None = None
    side: Literal["long", "short"] | None = None
    entryPrice: float | None = None
    exitPrice: float | None = None
    stopLoss: float | None = None
    takeProfit: float | None = None
    quantity: float | None = None
    pnl: float | None = None


class OrderCancelResult(BaseModel):
    """Результат `POST /api/v1/orders/{id}/cancel`. Содержит обновлённый
    ордер + exit-инфо (если был active → closed)."""

    order: Order
    result: str = Field(description="'cancelled' | 'closed' | etc")
    exit: float | None = None
    pnl: float | None = None


class Account(BaseModel):
    """Снапшот аккаунта (см. `GET /api/v1/account`). Используется для
    динамического расчёта `amount` от balance перед `place_order(...)`.
    """

    userId: int
    email: str
    coins: int
    tier: Literal["free", "starter", "pro", "premium"]
    tierExpiresAt: str | None = None
    signalSymbols: list[str] | None = None


class TrapFlipSignal(BaseModel):
    """Trap-flip signal: sweep+return через свежий OB protector. Tier: PRO.

    Источник: signal.trap-flip.<SYMBOL> channel.
    Алгоритм: цена забирает 3-drive ловушку (sweep ниже OB.wickLow для LONG),
    возвращается → entry на возврате, SL за магнитом, TP в свежей зоне.
    """

    strategy: Literal["trap-flip"] = "trap-flip"
    version: str = "v1"
    symbol: str
    direction: Literal["long", "short"]
    entry: float
    stop: float
    tp1: float
    rr: float
    confirmTime: int
    raw: dict | None = Field(
        default=None,
        description="Контекст: magnetZone, protectorOb, tpZone, threeDriveContext",
    )
