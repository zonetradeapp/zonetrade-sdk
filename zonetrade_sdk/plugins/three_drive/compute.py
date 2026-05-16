"""Three-Drive — детектор 3-drive setup'а поверх готовых fractals.

Pure function: получает уже-посчитанные fractals (например, из plugin
`fractals` — Mode C cache в Redis), возвращает 3-drive паттерны.

Не зависит от kline-фетчера и не вычисляет fractals сам — это и есть
основная фишка plugin-composition (вариант A): три-drive == «потребитель»
fractals, переиспользует их вместо повторной обработки свечей.

Контракт fractal-элемента (минимум полей):
    { 'kind': 'HH'|'HL'|'LH'|'LL'|'SH'|'SL',
      'price': float,
      'time':  int (unix sec) }
Лишние поля игнорируются — мы только читаем kind/price/time.
"""

from __future__ import annotations


def detect_three_drive(
    fractals: list[dict],
    min_drive_gap_pct: float = 0.0,
    lookback: int = 10,
) -> list[dict]:
    """Найти 3-drive паттерны в последовательности fractals.

    Правило: три последовательных fractal'а одного типа (LL для long,
    HH для short) с монотонной прогрессией. Каждый следующий drive
    должен быть «лучше» предыдущего хотя бы на min_drive_gap_pct.

    Сканируем по всему массиву (не только последние) — на снапшоте
    видно историю всех 3-drive setup'ов в окне.

    Args:
        fractals: список { kind, price, time, ... }, отсортирован по time.
        min_drive_gap_pct: минимальный % gap между drive'ами (0 = строгое
            неравенство). 0.001 = каждый next drive ≥ 0.1% дальше.
        lookback: сколько подряд идущих fractals просматривать в окне
            для каждой попытки матча.

    Returns:
        list of {
            kind: '3D-L'|'3D-S',
            direction: 'up'|'down',    # 'up' = bullish reversal (3 LL→long),
                                       # 'down' = bearish reversal (3 HH→short)
            patternType: 'consolidation'|'exhaustion',  # gap2 < gap1 → consolid
            drives: [(price, time), (price, time), (price, time)],
            entry: float,        # ~30% retrace из drive3
            sl: float,           # за drive3 на 50% от последнего gap
            tpRecovery: float,   # возврат к drive1 (полный retrace)
            chochOffset, retraceOffset, entryOffset: int  # в bars от drive3
        }.
    """
    out: list[dict] = []
    n = len(fractals)
    if n < 3:
        return out

    seen_third_idx: set[int] = set()
    for i in range(2, n):
        if i in seen_third_idx:
            continue
        kind = fractals[i].get('kind')
        if kind not in ('LL', 'HH'):
            continue
        window_start = max(0, i - lookback + 1)
        same_kind_idx = [
            j for j in range(window_start, i + 1)
            if fractals[j].get('kind') == kind
        ]
        if len(same_kind_idx) < 3:
            continue
        d_idx = same_kind_idx[-3:]
        prices = [fractals[j]['price'] for j in d_idx]
        times = [fractals[j]['time'] for j in d_idx]
        p1, p2, p3 = prices

        if kind == 'LL':
            if p1 <= 0 or p2 <= 0:
                continue
            gap1 = (p1 - p2) / p1
            gap2 = (p2 - p3) / p2
            if not (gap1 > min_drive_gap_pct and gap2 > min_drive_gap_pct):
                continue
            setup_kind = '3D-L'
            direction = 'up'  # bullish reversal
        else:  # HH
            if p1 <= 0 or p2 <= 0:
                continue
            gap1 = (p2 - p1) / p1
            gap2 = (p3 - p2) / p2
            if not (gap1 > min_drive_gap_pct and gap2 > min_drive_gap_pct):
                continue
            setup_kind = '3D-S'
            direction = 'down'  # bearish reversal

        # Геометрия паттерна для визуала. Эвристики — каркас, для торговли
        # их надо валидировать FVG/OB/fibo, но для отображения хватит:
        #
        # - patternType: consolidation = drive'ы в сужающейся прогрессии
        #   (gap2 < gap1); exhaustion = расширяющейся (gap2 ≥ gap1).
        # - entry: ~30% retrace в сторону предыдущего drive'а от drive3.
        # - sl: за drive3 на 50% размера последнего шага (drive2→drive3).
        # - tpRecovery: полный возврат к drive1 (1.0 retrace).
        pattern_type = 'consolidation' if gap2 < gap1 else 'exhaustion'
        last_step = abs(p3 - p2)
        if direction == 'up':
            entry = p3 + 0.3 * (p2 - p3)
            sl = p3 - 0.5 * last_step
            tp_recovery = p1
        else:
            entry = p3 - 0.3 * (p3 - p2)
            sl = p3 + 0.5 * last_step
            tp_recovery = p1

        out.append({
            'kind': setup_kind,
            'direction': direction,
            'patternType': pattern_type,
            'drives': list(zip(prices, times)),
            'entry': entry,
            'sl': sl,
            'tpRecovery': tp_recovery,
            # Offsets в барах от drive3 — где chartview расположит CHoCH /
            # retrace / entry-time. Точное число условно: после drive3 в
            # реале это N свечей до подтверждения CHoCH'а, но без подсчёта
            # бар берём sensible defaults.
            'chochOffset': 2,
            'retraceOffset': 5,
            'entryOffset': 5,
        })
        seen_third_idx.add(i)
    return out
