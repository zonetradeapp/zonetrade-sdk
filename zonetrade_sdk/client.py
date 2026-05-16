"""WebSocket client для Zonetrade Bot Platform.

Тонкая обёртка над `websockets` с:
- auto-reconnect (exponential backoff)
- handler-декораторами per event-type
- subscription management
- Pydantic-парсингом events

Минимум кода (target < 200 строк) — SDK как стандартная либа,
бизнес-логика бота пишется юзером.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
from pydantic import ValidationError

from zonetrade_sdk.events import (
    Account,
    Bar,
    FractalEvent,
    FvgZone,
    Order,
    OrderCancelResult,
    OrderEvent,
    ObZone,
    ObZoneEvent,
    StructureEvent,
    ThreeDriveRawSetup,
    ThreeDriveV11Signal,
    TrapFlipSignal,
)
from zonetrade_sdk.exceptions import AuthError, ConnectionError, OrderError, TierRequiredError
from zonetrade_sdk.plugin import Plugin
from zonetrade_sdk.render import RenderObject, RenderObjectCreated
from zonetrade_sdk.structure import StructureSnapshot

logger = logging.getLogger("zonetrade_sdk")

# Channel prefix → Pydantic model. Используется для авто-парсинга events.
# Match — first prefix wins; порядок важен если префиксы наследуют (`signal.`
# / `signal.trap-flip.`). Per-user каналы пока только `user.<id>.order` —
# когда появится `user.<id>.balance` или другие, заменим на regex-dispatch.
_CHANNEL_TO_MODEL: dict[str, type] = {
    "bar.": Bar,
    "zone.fvg.": FvgZone,
    # `zone.ob.` имеет два варианта схемы: новый channel-event ObZoneEvent
    # (task 03, sweep+engulf payload с TF в routing-key) и legacy ObZone
    # (per-HTF zone state). Сейчас публикуется только новый — bind на него.
    "zone.ob.": ObZoneEvent,
    # `structure.fractal.` идёт ПЕРЕД `structure.` — first-prefix-wins.
    "structure.fractal.": FractalEvent,
    "structure.": StructureEvent,
    "setup.three-drive-raw.": ThreeDriveRawSetup,
    "signal.three-drive-v11.": ThreeDriveV11Signal,
    "signal.trap-flip.": TrapFlipSignal,
    "user.": OrderEvent,
}

HandlerFn = Callable[[Any], Awaitable[None]]


def _model_for_channel(channel: str) -> type | None:
    for prefix, model in _CHANNEL_TO_MODEL.items():
        if channel.startswith(prefix):
            return model
    return None


class Client:
    """Zonetrade WebSocket client.

    Использование:
        client = Client(api_key="zt_...")

        @client.on("bar")
        async def on_bar(bar):
            print(bar.close)

        await client.run(subscribe=["bar.1m.BTCUSDT"])
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "wss://zonetrade.app/external-signals",
        api_base_url: str | None = None,
        max_reconnect_delay: float = 30.0,
    ):
        if not api_key:
            raise AuthError("api_key required")
        self.api_key = api_key
        self.base_url = base_url
        # REST base — выводим из WS URL (`wss://host/...` → `https://host`),
        # либо берём явный override. Endpoint'ы `/api/v1/...` дописываются
        # в _request().
        self.api_base_url = (api_base_url or _ws_to_http_origin(base_url)).rstrip("/")
        self.max_reconnect_delay = max_reconnect_delay
        # event_type → handlers. event_type = "bar", "signal", "zone", etc.
        # (короткое имя из event-payload, не полный channel).
        self._handlers: dict[str, list[HandlerFn]] = {}
        # текущие подписки — сохраняем для re-subscribe после reconnect.
        self._subscribed: set[str] = set()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False
        # Lazy httpx client — создаём при первом REST-вызове, чтобы юзеры,
        # которые используют только WS, не платили за инициализацию.
        self._http: httpx.AsyncClient | None = None
        # userId — приходит в `hello` event'е от сервера, нужен чтобы
        # subscribe_orders() мог сформировать `user.<id>.order` канал без
        # того, чтобы юзер знал свой numeric id.
        self.user_id: int | None = None
        # signalSymbols — whitelist пар из настроек юзера (см. User::$signalSymbols
        # в backend'е). Приходит в hello. None = дефолт (BTC/ETH/SOL/BNB/XRP),
        # пустой список = опт-аут, любой массив = explicit пары.
        # Bot-template'ы используют для ZT_SYMBOLS=auto.
        self.signal_symbols: list[str] | None = None
        # Текущий баланс юзера (User.coins). Обновляется при `get_account()`.
        # Используется bot-template'ами для percent-based расчёта amount.
        self.coins: int = 0
        # Зарегистрированные плагины. Каждый получает on_init() после hello
        # и on_event() при подходящем канале.
        self._plugins: list[Plugin] = []
        self._plugins_initialized = False

    def use(self, plugin: Plugin) -> "Client":
        """Зарегистрировать плагин. Можно цепочкой: client.use(a).use(b).
        Init вызывается после hello-event (в _handle_message)."""
        plugin._attach(self)
        self._plugins.append(plugin)
        return self

    def on(self, event_type: str) -> Callable[[HandlerFn], HandlerFn]:
        """Декоратор: регистрирует handler для event_type.

        event_type может быть:
          - короткое имя: "bar", "signal", "zone", "structure", "setup"
          - конкретный channel: "bar.1m.BTCUSDT" — handler только для него
        """

        def decorator(fn: HandlerFn) -> HandlerFn:
            self._handlers.setdefault(event_type, []).append(fn)
            return fn

        return decorator

    async def run(self, subscribe: list[str] | None = None) -> None:
        """Подключается к WS и запускает event loop. Auto-reconnect внутри."""
        self._running = True
        if subscribe:
            self._subscribed.update(subscribe)
        backoff = 0.5
        while self._running:
            try:
                await self._connect_and_listen()
                backoff = 0.5  # успешный коннект сбрасывает backoff
            except websockets.exceptions.InvalidStatusCode as e:
                if e.status_code == 401:
                    raise AuthError(f"Invalid API key (HTTP {e.status_code})") from e
                logger.warning("ws error %s, reconnecting in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_reconnect_delay)
            except Exception as e:
                logger.warning("ws error %s, reconnecting in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_reconnect_delay)

    async def stop(self) -> None:
        """Корректное завершение event loop. Вызывает on_unload каждого
        плагина — там по дефолту удаляются их render-objects."""
        self._running = False
        for plugin in self._plugins:
            try:
                await plugin.on_unload()
            except Exception as e:
                logger.warning("[%s] on_unload failed: %s", plugin.name, e)
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def subscribe(self, channels: list[str]) -> None:
        """Динамическое subscribe на каналы (после run started)."""
        self._subscribed.update(channels)
        if self._ws and not self._ws.closed:
            await self._ws.send(json.dumps({"action": "subscribe", "channels": channels}))

    async def unsubscribe(self, channels: list[str]) -> None:
        """Динамическое unsubscribe."""
        for ch in channels:
            self._subscribed.discard(ch)
        if self._ws and not self._ws.closed:
            await self._ws.send(json.dumps({"action": "unsubscribe", "channels": channels}))

    def resolved_signal_symbols(self) -> list[str]:
        """Whitelist пар юзера с resolve'нутым default'ом.

        SDK получает signal_symbols из hello-event'а:
          - None → backend default (BTC/ETH/SOL/BNB/XRP, синхронизировано с
            GameplayTgConsumerCommand::DEFAULT_SIGNAL_SYMBOLS)
          - []   → юзер сознательно отключил все пары
          - [...] → explicit список

        Bot-template'ы зовут этот метод когда `ZT_SYMBOLS=auto`. Вызывать
        ПОСЛЕ hello (см. self.user_id != None). На клиенте пока нет hello —
        вернётся default (так разумнее чем кидать exception).
        """
        if self.signal_symbols is not None:
            return list(self.signal_symbols)
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

    async def subscribe_orders(self) -> None:
        """Подписаться на канал `user.<self.user_id>.order` — push-события о
        смене статуса своих ордеров (fill/close/cancel/invalidate). Сервер
        запретит подписку на чужой userId (`forbidden_channel`).

        Вызывать ПОСЛЕ `run()` начал event-loop и получил hello-event
        (см. self.user_id). Безопасно вызвать без хеллo — SDK подождёт.
        """
        # Если hello ещё не пришёл — ждём, иначе формируем неправильный
        # channel. Race-safe: hello приходит обычно через 50-100мс.
        for _ in range(50):  # ~5s max wait
            if self.user_id is not None:
                break
            await asyncio.sleep(0.1)
        if self.user_id is None:
            raise ConnectionError("subscribe_orders: hello event not received yet")
        await self.subscribe([f"user.{self.user_id}.order"])

    async def _connect_and_listen(self) -> None:
        url = f"{self.base_url}?token={self.api_key}"
        async with websockets.connect(url) as ws:
            self._ws = ws
            logger.info("connected to %s", self.base_url)
            # Initial subscribe deferred — отправим после первого hello
            # event'а. Иначе race: сервер async-инициализирует message-handler
            # и subscribe может прийти ДО того как ws.on('message') готов.
            self._initial_subscribe_sent = False
            async for raw in ws:
                await self._handle_message(raw)

    # ---------- REST API v1 (orders) ----------
    #
    # Тонкая обёртка над `/api/v1/orders/*` (см. backend OrderV1Controller).
    # Auth — тот же `api_key` через `Authorization: Bearer ...` header.
    # Все методы async; ошибки backend'а → OrderError (с http-status + code).

    async def get_account(self) -> Account:
        """Снапшот аккаунта: coins, tier, signalSymbols. Используется в
        bot-template'ах перед place_order для динамического расчёта amount
        от balance. После вызова обновляет `self.coins` и `self.signal_symbols`."""
        data = await self._request("GET", "/api/v1/account")
        acc = Account.model_validate(data)
        # Side-effect: синхронизируем in-memory state (можем кэшировать без
        # повторного round-trip'а).
        self.coins = acc.coins
        if acc.signalSymbols is not None:
            self.signal_symbols = list(acc.signalSymbols)
        return acc

    async def place_order(
        self,
        symbol: str,
        side: str,
        entry: float,
        stop: float,
        tp1: float,
        tp2: float | None = None,
        tp3: float | None = None,
        amount: float | None = None,
        strategy: str | None = None,
        signal_id: int | None = None,
    ) -> Order:
        """Создать paper-ордер. Возвращает Order или бросает OrderError.

        Args:
            side: 'long' | 'short'
            amount: margin в USD (default 100 на backend'е)
            strategy: 'single_tp' | 'multi_tp_be' (default 'multi_tp_be')
        """
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "stop": stop,
            "tp1": tp1,
        }
        if tp2 is not None: body["tp2"] = tp2
        if tp3 is not None: body["tp3"] = tp3
        if amount is not None: body["amount"] = amount
        if strategy is not None: body["strategy"] = strategy
        if signal_id is not None: body["signalId"] = signal_id
        data = await self._request("POST", "/api/v1/orders", json=body, expect=(201, 200))
        return Order.model_validate(data)

    async def list_orders(
        self,
        symbol: str | None = None,
        open_only: bool = False,
        limit: int = 50,
    ) -> list[Order]:
        """Список ордеров текущего юзера (по api_key). max limit=100."""
        params: dict[str, Any] = {"limit": limit}
        if symbol: params["symbol"] = symbol
        if open_only: params["openOnly"] = 1
        data = await self._request("GET", "/api/v1/orders", params=params)
        return [Order.model_validate(it) for it in data.get("items", [])]

    async def get_order(self, order_id: int) -> Order:
        """Один ордер по id. OrderError(404) если не существует или чужой."""
        data = await self._request("GET", f"/api/v1/orders/{order_id}")
        return Order.model_validate(data)

    async def cancel_order(self, order_id: int) -> OrderCancelResult:
        """Отменить wait-ордер или закрыть active по текущей цене."""
        data = await self._request("POST", f"/api/v1/orders/{order_id}/cancel")
        return OrderCancelResult.model_validate(data)

    async def get_structure_snapshot(
        self,
        symbol: str,
        tf: str = "1m",
        window_bars: int = 100,
        fractal_n: int = 2,
        respect_inside_candles: bool = True,
        end_ms: int | None = None,
    ) -> StructureSnapshot:
        """Snapshot структуры (fractals/BoS/CHoCH/FVG/OB) для одного символа.

        Зови ПЕРЕД WS-subscribe на `structure.*` — иначе видны будут
        только новые события, без текущего контекста. Подход REST snapshot
        + WS delta — индустриальный стандарт (Binance, Bybit для стаканов).

        Args:
            symbol: апперкейс, например BTCUSDT.
            tf: 1m/3m/5m/15m/30m/1h/2h/4h/6h/12h/1d/1w/1M.
            window_bars: сколько свечей назад (10..500).
            fractal_n: размер фрактала (1..3, default 2 = классический 5-bar).
            respect_inside_candles: пропускать inside bars при детекте.
            end_ms: конец окна в Unix ms (default = сейчас). Полезно для
                воспроизводимого среза в прошлом.
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "tf": tf,
            "windowBars": window_bars,
            "fractalN": fractal_n,
            "respectInsideCandles": "1" if respect_inside_candles else "0",
        }
        if end_ms is not None:
            params["endMs"] = end_ms
        data = await self._request("GET", "/api/structure/snapshot", params=params)
        # Endpoint оборачивает payload в {success, items: {...}} — стандартный
        # Symfony API-wrapper. Распаковываем для модели.
        body = data.get("items", data) if isinstance(data, dict) else data
        return StructureSnapshot.model_validate(body)

    # ---------- Render objects (task 05) ----------
    #
    # Бот рисует на чарте у юзера: создаёт объект → REST POST → backend
    # сохраняет в Redis с TTL и publish'ит в `user.<id>.render` WS-канал
    # → chartview рисует через primitive-механизм.

    async def list_game_watched_pairs(self) -> list[str]:
        """Список всех символов с isGameWatched=true.

        Используется плагинами в качестве «вселенной» — все пары которые
        наш cron-детектор обрабатывает (там же и structure-stream доступен).
        Endpoint публичный (`/api/public/*`), но JwtAuthenticator валится на
        non-JWT Bearer. Делаем fetch БЕЗ Authorization header — отдельный
        httpx-клиент."""
        async with httpx.AsyncClient(
            base_url=self.api_base_url, timeout=15.0,
        ) as cli:
            resp = await cli.get("/api/public/trading-pairs")
            resp.raise_for_status()
            data = resp.json()
        inner = data.get("items", data) if isinstance(data, dict) else {}
        pairs = inner.get("pairs", []) if isinstance(inner, dict) else []
        return [p["symbol"] for p in pairs if p.get("isGameWatched") and p.get("symbol")]

    async def render_zone(
        self,
        symbol: str,
        tf: str,
        top: float,
        bottom: float,
        fill: str | None = None,
        border: str | None = None,
        label: str | None = None,
        ttl: int = 3600,
    ) -> RenderObjectCreated:
        """Прямоугольная зона [top..bottom]. fill — цвет заливки (rgba),
        border — обводка, label — текст-метка. ttl до 7 дней."""
        return await self._create_render({
            "type": "zone",
            "symbol": symbol,
            "tf": tf,
            "geometry": {"top": top, "bottom": bottom},
            "style": {k: v for k, v in {
                "fill": fill, "border": border, "label": label,
            }.items() if v is not None},
            "ttl": ttl,
        })

    async def render_line(
        self,
        symbol: str,
        tf: str,
        price: float,
        color: str | None = None,
        dash: list[int] | None = None,
        label: str | None = None,
        ttl: int = 3600,
    ) -> RenderObjectCreated:
        """Горизонтальная линия по цене."""
        return await self._create_render({
            "type": "line",
            "symbol": symbol,
            "tf": tf,
            "geometry": {"price": price},
            "style": {k: v for k, v in {
                "color": color, "dash": dash, "label": label,
            }.items() if v is not None},
            "ttl": ttl,
        })

    async def render_label(
        self,
        symbol: str,
        tf: str,
        price: float,
        time: int,
        text: str,
        color: str | None = None,
        ttl: int = 3600,
    ) -> RenderObjectCreated:
        """Текстовая метка в точке (time, price). `time` — Unix секунды."""
        return await self._create_render({
            "type": "label",
            "symbol": symbol,
            "tf": tf,
            "geometry": {"price": price, "time": time, "text": text},
            "style": {"color": color} if color else {},
            "ttl": ttl,
        })

    async def render_marker(
        self,
        symbol: str,
        tf: str,
        price: float,
        time: int,
        color: str | None = None,
        radius: float | None = None,
        label: str | None = None,
        ttl: int = 3600,
    ) -> RenderObjectCreated:
        """Точка (circle) в координатах (time, price). Опционально с подписью
        рядом (`label`) и кастомным радиусом (`radius`, default 3px).

        Полезно для visualization fractals/POI/triggers — отметить ТОЧКУ
        в данных а не зону или линию."""
        style: dict[str, Any] = {}
        if color is not None: style["color"] = color
        if label is not None: style["label"] = label
        if radius is not None: style["radius"] = radius
        return await self._create_render({
            "type": "marker",
            "symbol": symbol,
            "tf": tf,
            "geometry": {"price": price, "time": time},
            "style": style,
            "ttl": ttl,
        })

    async def render_position(
        self,
        symbol: str,
        tf: str,
        side: str,
        entry: float,
        stop: float,
        take: float,
        time: int,
        end_time: int,
        take2: float | None = None,
        take3: float | None = None,
        tag: str | None = None,
        ttl: int = 3600,
    ) -> RenderObjectCreated:
        """Bounded визуал торговой позиции (entry/SL/TP zones + LONG/SHORT label).

        Рендерится в chartview через PositionPrimitive — risk-zone (red)
        от entry до stop, profit-zone (green) от entry до take, line на
        entry, label LONG/SHORT (или с префиксом `tag`).

        Args:
            side: 'long' | 'short'.
            time / end_time: Unix секунды — границы позиции на оси времени.
            take2, take3: опциональные доп. TP уровни.
            tag: префикс к LONG/SHORT-лейблу (например `#42` для номера setup'а).

        Возвращает RenderObjectCreated с `id` — можно потом удалить
        через `delete_render_object()`.
        """
        style: dict[str, Any] = {"side": side}
        if tag is not None: style["tag"] = tag
        geometry: dict[str, Any] = {
            "entry": entry, "stop": stop, "take": take,
            "time": time, "endTime": end_time,
        }
        if take2 is not None: geometry["take2"] = take2
        if take3 is not None: geometry["take3"] = take3
        return await self._create_render({
            "type": "position",
            "symbol": symbol,
            "tf": tf,
            "geometry": geometry,
            "style": style,
            "ttl": ttl,
        })

    async def delete_render_object(self, object_id: str) -> bool:
        """Удалить объект по id. True если был, False если уже истёк/нет."""
        data = await self._request(
            "DELETE", f"/api/v1/render-objects/{object_id}",
        )
        return bool(data.get("deleted", False)) if isinstance(data, dict) else False

    async def list_render_objects(
        self,
        symbol: str | None = None,
        tf: str | None = None,
    ) -> list[RenderObject]:
        """Список текущих render-объектов юзера (опц. фильтр по symbol/tf)."""
        params: dict[str, Any] = {}
        if symbol: params["symbol"] = symbol
        if tf: params["tf"] = tf
        data = await self._request("GET", "/api/v1/render-objects", params=params)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [RenderObject.model_validate(it) for it in items]

    async def _create_render(self, body: dict[str, Any]) -> RenderObjectCreated:
        data = await self._request(
            "POST", "/api/v1/render-objects", json=body, expect=(201,),
        )
        return RenderObjectCreated.model_validate(data)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        expect: tuple[int, ...] = (200,),
    ) -> Any:
        """HTTP-обёртка: Bearer-auth, JSON-парсинг, error → OrderError."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.api_base_url,
                timeout=15.0,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        try:
            resp = await self._http.request(method, path, json=json, params=params)
        except httpx.HTTPError as e:
            raise OrderError("network", 0, {"detail": str(e)}) from e

        # Backend сейчас отдаёт JSON на всех ответах (включая ошибки). Если
        # тело не парсится — это network-уровень (proxy/nginx), не наш API.
        try:
            payload = resp.json()
        except ValueError as e:
            raise OrderError("bad_json", resp.status_code, {"body": resp.text[:200]}) from e

        if resp.status_code not in expect:
            code = (payload.get("error") if isinstance(payload, dict) else None) or "http_error"
            if resp.status_code == 401:
                raise AuthError(f"Invalid API key (HTTP 401, {code})")
            raise OrderError(code, resp.status_code, payload if isinstance(payload, dict) else None)
        return payload

    async def aclose(self) -> None:
        """Закрыть HTTP-коннект (если был открыт). WS отдельно — через stop()."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---------- WS message dispatching ----------

    async def _handle_message(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("bad json: %r", raw[:200])
            return

        # WS-server использует `event` поле для channel-данных и `type` —
        # для legacy wrapper-сообщений (hello/ping). Нормализуем в одно
        # `event` чтобы handler'ам было одинаково.
        event = msg.get("event") or msg.get("type")
        channel = msg.get("channel")
        data = msg.get("data")

        # Ping: heartbeat от сервера, ничего не делаем (websockets сам
        # держит коннект через WS-уровневые ping/pong).
        if event == "ping":
            return

        # Special events: hello / subscribed / subscribe_rejected / error.
        if event == "hello":
            uid = msg.get("userId")
            if isinstance(uid, int):
                self.user_id = uid
            settings = msg.get("settings") or {}
            raw_symbols = settings.get("signalSymbols")
            if isinstance(raw_symbols, list):
                self.signal_symbols = [str(s) for s in raw_symbols]
            elif raw_symbols is None:
                self.signal_symbols = None
            # Snapshot coins из hello — init без REST. После place/close
            # coins на backend меняются, для свежей цифры вызвать get_account().
            raw_coins = settings.get("coins")
            if isinstance(raw_coins, (int, float)):
                self.coins = int(raw_coins)
            logger.info(
                "hello user=%s settings=%s",
                uid, settings,
            )
            # Initial subscribe — после hello, чтобы избежать race с
            # async init server'а.
            if self._subscribed and not getattr(self, "_initial_subscribe_sent", False):
                await self._ws.send(json.dumps({
                    "action": "subscribe",
                    "channels": sorted(self._subscribed),
                }))
                self._initial_subscribe_sent = True
            # Plugin init — после первого hello. При reconnect не повторяем
            # (плагин уже инициализирован, его _subscribed channels включены
            # в self._subscribed и они re-subscribe'нутся выше).
            if not self._plugins_initialized:
                self._plugins_initialized = True
                for plugin in self._plugins:
                    try:
                        await plugin.on_init()
                    except Exception as e:
                        logger.exception("[%s] on_init failed: %s", plugin.name, e)
            await self._dispatch("hello", msg)
            return
        if event == "subscribed":
            logger.info("subscribed channels=%s rejected=%s",
                        msg.get("channels"), msg.get("rejected"))
            for rej in msg.get("rejected") or []:
                if rej.get("reason") == "tier_required":
                    # Подсветим в логе — но не throw exception, чтобы остальные
                    # подписки продолжали работать. Юзер видит warning.
                    logger.warning(
                        "channel %s requires tier %s",
                        rej.get("channel"), rej.get("required_tier"),
                    )
            return
        if event == "unsubscribed":
            return
        if event == "error":
            logger.error("server error: %s", msg.get("reason"))
            return

        # Data events: bar / zone / structure / setup / signal.
        # Парсим в Pydantic-модель если есть подходящая.
        model = _model_for_channel(channel or "")
        parsed: Any = data
        if model:
            try:
                parsed = model.model_validate(data)
            except ValidationError as e:
                logger.warning("parse fail for %s: %s", channel, e)
                # дальше передаём raw dict — лучше так чем drop
                parsed = data

        # Dispatch: event-type handler ("bar", "signal", ...) + channel-specific.
        await self._dispatch(event or "unknown", parsed)
        if channel:
            await self._dispatch(channel, parsed)
        # Plugins — каждый получает on_event только если канал в его
        # _subscribed списке (плагин сам управляет своими подписками).
        if channel:
            for plugin in self._plugins:
                if not plugin._matches_channel(channel):
                    continue
                try:
                    await plugin.on_event(channel, parsed)
                except Exception as e:
                    logger.exception("[%s] on_event failed: %s", plugin.name, e)

    async def _dispatch(self, key: str, data: Any) -> None:
        for handler in self._handlers.get(key, []):
            try:
                await handler(data)
            except Exception as e:
                logger.exception("handler error for %s: %s", key, e)


def _ws_to_http_origin(ws_url: str) -> str:
    """`wss://host/external-signals` → `https://host`. Используется чтобы из
    одного WS base_url вывести REST-origin без лишних параметров SDK."""
    p = urlparse(ws_url)
    scheme = "https" if p.scheme == "wss" else "http" if p.scheme == "ws" else p.scheme
    # path/query/fragment отбрасываем — REST берёт `/api/v1/...` от origin.
    return urlunparse((scheme, p.netloc, "", "", "", ""))


# Удобный re-export чтобы из примера выглядело лаконично.
__all__ = ["Client", "AuthError", "ConnectionError", "OrderError", "TierRequiredError"]
