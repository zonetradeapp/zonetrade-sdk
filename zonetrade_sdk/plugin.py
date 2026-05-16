"""Plugin framework — pluggable SDK extensions.

Плагин = класс с lifecycle-хуками. Регистрируется через `client.use(plugin)`.
Получает client как self._client, имеет helpers render_zone/line/label,
которые отслеживают созданные render-объекты и автоматически удаляют их
при `on_unload`.

Пример:
    class FractalsPlugin(Plugin):
        async def on_init(self):
            snap = await self._client.get_structure_snapshot("BTCUSDT", "1m")
            for fr in snap.fractals:
                await self.render_label(
                    symbol="BTCUSDT", tf="1m",
                    price=fr.price, time=fr.timeMs // 1000,
                    text=fr.label,
                )
            await self._client.subscribe(["structure.fractal.1m.BTCUSDT"])

        async def on_event(self, channel, ev):
            if isinstance(ev, FractalEvent):
                await self.render_label(...)

    client = Client(api_key="...")
    client.use(FractalsPlugin())
    await client.run()

При `client.stop()` SDK вызовет `on_unload()` каждого плагина, и все
объекты созданные через `self.render_*` будут удалены автоматически.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zonetrade_sdk.client import Client

logger = logging.getLogger("zonetrade_sdk.plugin")


class Plugin:
    """Base class для SDK-плагинов.

    Переопределяй `on_init` / `on_event` / `on_unload` в наследнике.
    Не зови `super().__init__()` если не передаёшь параметры — base уже
    инициализирует свои поля в `_attach()`.
    """

    name: str = "unnamed"
    api_version: int = 1

    def __init__(self) -> None:
        self._client: "Client | None" = None
        self._render_ids: list[str] = []
        self._subscribed: list[str] = []

    # ---- Internal: called by Client.use() / run() / stop() ----

    def _attach(self, client: "Client") -> None:
        self._client = client

    def _matches_channel(self, channel: str) -> bool:
        """Плагин получит on_event только для каналов из _subscribed."""
        return channel in self._subscribed

    # ---- Public helpers — proxy через client + tracking ----

    async def subscribe(self, channels: list[str]) -> None:
        """Subscribe + запомнить чтобы фильтровать on_event."""
        assert self._client is not None, "plugin not attached"
        await self._client.subscribe(channels)
        self._subscribed.extend(channels)

    async def render_zone(self, **kw: Any) -> Any:
        assert self._client is not None
        obj = await self._client.render_zone(**kw)
        self._render_ids.append(obj.id)
        return obj

    async def render_line(self, **kw: Any) -> Any:
        assert self._client is not None
        obj = await self._client.render_line(**kw)
        self._render_ids.append(obj.id)
        return obj

    async def render_label(self, **kw: Any) -> Any:
        assert self._client is not None
        obj = await self._client.render_label(**kw)
        self._render_ids.append(obj.id)
        return obj

    async def render_marker(self, **kw: Any) -> Any:
        assert self._client is not None
        obj = await self._client.render_marker(**kw)
        self._render_ids.append(obj.id)
        return obj

    async def render_position(self, **kw: Any) -> Any:
        assert self._client is not None
        obj = await self._client.render_position(**kw)
        self._render_ids.append(obj.id)
        return obj

    async def cleanup_render(self) -> None:
        """Удалить все render-объекты, которые плагин создал.

        Вызывается автоматически из default `on_unload`. Если плагин
        переопределяет on_unload — должен сам вызвать `await self.cleanup_render()`
        или оставить objects жить (с TTL).
        """
        assert self._client is not None
        for rid in self._render_ids:
            try:
                await self._client.delete_render_object(rid)
            except Exception as e:
                logger.warning("[%s] cleanup delete %s failed: %s", self.name, rid, e)
        self._render_ids.clear()

    # ---- Hooks — override in subclass ----

    async def on_init(self) -> None:
        """Вызывается ОДИН раз после успешного hello от сервера.
        Тут плагин должен subscribe + bootstrap snapshot'ы."""
        pass

    async def on_event(self, channel: str, event: Any) -> None:
        """WS-событие на subscribed канале. event — Pydantic-модель или
        raw dict если SDK не знает schema."""
        pass

    async def on_unload(self) -> None:
        """Cleanup. Default — удаляет все render-объекты плагина.
        Override если нужна доп. логика (логи, отчёт)."""
        await self.cleanup_render()
