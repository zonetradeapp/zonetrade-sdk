"""Render-objects (task 05): API для рисования на чарте у пользователя.

Бот считает свою фигуру (например own-rule OB, custom level, alert-label)
и пушит её через REST. Chartview подписан на `user.<id>.render` WS-канал —
рисует через primitive-механизм.

Объекты эфемерны (TTL до 7 дней, default 1h), хранятся в Redis. При
expiresAt истёкшем — chartview снимет primitive локально.

Пример:
    client = Client(api_key="zt_...")
    # Нарисовать кастомную OB-зону
    obj = await client.render_zone(
        symbol="BTCUSDT", tf="1m",
        top=80500, bottom=80400,
        fill="rgba(34,197,94,0.2)", border="rgba(34,197,94,0.8)",
        label="My OB", ttl=3600,
    )
    # ...позже...
    await client.delete_render_object(obj.id)
"""

from typing import Literal

from pydantic import BaseModel, Field


class RenderGeometryZone(BaseModel):
    top: float
    bottom: float


class RenderGeometryLine(BaseModel):
    price: float


class RenderGeometryLabel(BaseModel):
    price: float
    time: int = Field(description="Unix seconds")
    text: str


class RenderStyle(BaseModel):
    """Опциональные style-параметры для primitive. Какие поля учитываются
    зависит от type (zone использует fill/border, line — color/dash и т.д.).
    chartview ignore'ит неподходящие."""

    fill: str | None = None
    border: str | None = None
    color: str | None = None
    dash: list[int] | None = None
    label: str | None = None


class RenderObject(BaseModel):
    """Render-объект как его возвращает GET /api/v1/render-objects.

    `geometry` — dict (тип-зависимый), не парсим в discriminated union
    чтобы клиент видел все поля как есть."""

    id: str
    userId: int
    type: Literal["zone", "line", "label"]
    symbol: str
    tf: str
    geometry: dict
    style: dict
    createdAt: int
    expiresAt: int


class RenderObjectCreated(BaseModel):
    """Ответ POST /api/v1/render-objects."""

    id: str
    expiresAt: int
