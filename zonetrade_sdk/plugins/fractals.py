"""FractalsPlugin — визуализация SMC-свингов (HH/HL/LH/LL/SH/SL) на чарте.

Получает фракталы из REST snapshot'а на старте + live из WS-канала
`structure.fractal.<tf>.<SYM>`. Для каждого фрактала рисует подписанный
label в точке (timeMs, price) через `render_label`.

При unload удаляет все свои labels (default Plugin.on_unload cleanup).

Это первый официальный плагин — образец паттерна. Авторы community-плагинов
будут копировать этот файл и менять логику.
"""

from __future__ import annotations

import logging

from zonetrade_sdk.events import FractalEvent
from zonetrade_sdk.plugin import Plugin

logger = logging.getLogger("zonetrade_sdk.plugins.fractals")

# Цвета лейблов по типу свинга — bullish структура green'ом, bearish red'ом,
# нейтральные swings (без сравнения с предыдущим) — серый.
_FRACTAL_COLORS = {
    'HH': 'rgba(34,197,94,0.95)',    # higher high — bullish
    'HL': 'rgba(34,197,94,0.85)',    # higher low — bullish
    'LH': 'rgba(239,68,68,0.95)',    # lower high — bearish
    'LL': 'rgba(239,68,68,0.85)',    # lower low — bearish
    'SH': 'rgba(148,163,184,0.9)',   # swing high — нейтральный (нет предыдущего для сравнения)
    'SL': 'rgba(148,163,184,0.9)',   # swing low
}


class FractalsPlugin(Plugin):
    """Визуализирует фракталы (свинги) на чарте.

    Args:
        symbols: список символов для обработки.
        tf: timeframe (default '1m').
        window_bars: глубина snapshot'а (default 200 — ~3.3 часа на 1m).
        ttl_sec: TTL render-объектов (default 1 час). Larger = дольше живут
            фракталы которые уже scroll'нулись из видимого окна (но Redis
            держит лимит).
    """

    name = "fractals"

    def __init__(
        self,
        symbols: list[str],
        tf: str = "1m",
        window_bars: int = 200,
        ttl_sec: int = 3600,
    ) -> None:
        super().__init__()
        self.symbols = [s.upper() for s in symbols]
        self.tf = tf
        self.window_bars = window_bars
        self.ttl_sec = ttl_sec

    async def on_init(self) -> None:
        assert self._client is not None
        # `'auto'` / `'*'` / `'all'` → ВСЕ game-watched символы из реестра
        # (не фильтруем по signalSymbols юзера — плагин должен работать
        # на любой паре которую юзер откроет в chartview, даже если её
        # нет в его watch-list'е). chartview сам отфильтрует объекты по
        # текущей паре в syncRenderPrimitives.
        resolved = self.symbols
        if any(s.lower() in ('auto', '*', 'all') for s in resolved):
            try:
                resolved = await self._client.list_game_watched_pairs()
                logger.info("[fractals] auto-resolved to %d pairs", len(resolved))
            except Exception as e:
                logger.warning("[fractals] auto-resolve failed: %s — fallback to signal_symbols", e)
                resolved = self._client.resolved_signal_symbols()
        channels: list[str] = []
        for sym in resolved:
            # Bootstrap: история фракталов из snapshot'а — рисуем сразу,
            # без ожидания live-событий.
            try:
                snap = await self._client.get_structure_snapshot(
                    symbol=sym,
                    tf=self.tf,
                    window_bars=self.window_bars,
                )
            except Exception as e:
                logger.warning("snapshot %s/%s failed: %s", sym, self.tf, e)
                continue
            for fr in snap.fractals:
                await self._draw_fractal(
                    sym=sym,
                    label=fr.label,
                    price=fr.price,
                    time_ms=fr.timeMs,
                )
            channels.append(f"structure.fractal.{self.tf}.{sym}")
            logger.info(
                "[fractals] seeded %s/%s: %d fractals",
                sym, self.tf, len(snap.fractals),
            )
        # Подписка live — далее новые фракталы будут приходить в on_event.
        if channels:
            await self.subscribe(channels)

    async def on_event(self, channel: str, event) -> None:
        if not isinstance(event, FractalEvent):
            return
        await self._draw_fractal(
            sym=event.symbol,
            label=event.type,
            price=event.price,
            time_ms=event.timeMs,
        )

    async def _draw_fractal(
        self,
        sym: str,
        label: str,
        price: float,
        time_ms: int,
    ) -> None:
        color = _FRACTAL_COLORS.get(label, _FRACTAL_COLORS['SH'])
        # Marker = точка в (time, price) + опц. label-текст рядом.
        # Видно расхождение между нашим источником и источниками бота
        # (futures vs spot и т.п.) — точка стоит на ЦЕНЕ из snapshot'а,
        # а chartview-свеча может быть чуть выше/ниже.
        await self.render_marker(
            symbol=sym,
            tf=self.tf,
            price=price,
            time=time_ms // 1000,
            color=color,
            label=label,
            ttl=self.ttl_sec,
        )
