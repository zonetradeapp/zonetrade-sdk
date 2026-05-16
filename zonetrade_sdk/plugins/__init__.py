"""Official plugins для zonetrade-sdk.

Каждый под-пакет (`fractals`, `three_drive`, …) — самостоятельный плагин
с тем же контрактом что и сторонние: subclass `zonetrade_sdk.Plugin`,
опционально Mode C subprocess через `snapshot_entry.py`, манифест.

Сторонние плагины публикуются отдельными pip-пакетами (например
`zonetrade-plugin-myob`) и импортируют `from zonetrade_sdk import Plugin`
для базового класса — API одинаковый.
"""
