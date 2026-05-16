"""Exception types для Zonetrade SDK."""


class ZonetradeError(Exception):
    """Базовый класс всех ошибок SDK."""


class AuthError(ZonetradeError):
    """Невалидный API key. Перепроверь zonetrade.app/bot/api-keys."""


class ConnectionError(ZonetradeError):
    """Не удалось подключиться к WebSocket после retry'ев."""


class OrderError(ZonetradeError):
    """Ошибка REST-вызова `/api/v1/orders/*`. Содержит HTTP-status и
    error-код от backend'а (например 'insufficient_funds', 'forbidden',
    'geom_long_stop_not_below_entry').
    """

    def __init__(self, code: str, status: int, payload: dict | None = None):
        self.code = code
        self.status = status
        self.payload = payload or {}
        super().__init__(f"OrderError({status}): {code}")


class TierRequiredError(ZonetradeError):
    """Попытка subscribe на channel который требует более высокий tier.

    Attributes:
        channel: Имя канала на который не удалось подписаться
        required_tier: Минимальный нужный tier (starter/pro/premium)
    """

    def __init__(self, channel: str, required_tier: str | None = None):
        self.channel = channel
        self.required_tier = required_tier
        msg = f"Channel '{channel}' requires tier '{required_tier or '?'}' or higher"
        super().__init__(msg)
