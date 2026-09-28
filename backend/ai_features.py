"""Продуктовые фичи ИИ-ассистента поверх готовых расчётов системы.

Здесь НЕТ никакой математики по срокам: все дни, резервы, критический путь и
последствия считает schedule.py (CPM-движок). Этот модуль берёт JSON-результаты
движка и переводит их в текстовые предупреждения, рекомендации и объяснения.

Фичи:
  • radar(analysis)                — проактивный «Радар рисков» (загрузка людей,
                                     просрочки, нулевой резерв, запас до дедлайна);
  • checklist_suggestions(...)     — генерация чек-листа подзадач для сложной задачи;
  • explain_task(task_id, ...)     — «объясни простыми словами» про задачу/цепочку;
  • sandbox_json(shifted_days,...) — сухой JSON-факт для панели «Песочница»
                                     (frontend перетаскивает задачу, движок считает,
                                     здесь только цифра риска и список блокируемых).
"""
from __future__ import annotations

import re
from planning_calendar import date_label

# --------------------------------------------------------------------------- #
#  Мелкие хелперы над структурой analyze()                                     #
# --------------------------------------------------------------------------- #

def task_map(analysis: dict) -> dict:
    return {t["id"]: t for t in analysis["tasks"]}


def _days(n: int) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not (11 <= n % 100 <= 14):
        return f"{n} дня"
    return f"{n} дней"


def _pct(a: float, b: float) -> int:
    return round(100 * a / b) if b else 0


# --------------------------------------------------------------------------- #
#  1. Радар рисков (проактивный анализ без запроса пользователя)               #
# --------------------------------------------------------------------------- #

def workload_by_owner(analysis: dict) -> dict:
    """Распределение незавершённых задач, без оценки доступности и часов."""
    load: dict[str, dict] = {}
    for t in analysis["tasks"]:
        owner = t.get("owner") or "Без ответственного"
        item = load.setdefault(owner, {"total": 0, "active": 0, "critical": 0,
                                       "at_risk": 0, "names": []})
        item["total"] += 1
        if t["status"] != "done":
            item["active"] += 1
            item["names"].append(t["name"])
            if t.get("is_critical"):
                item["critical"] += 1
            if t.get("at_risk"):
                item["at_risk"] += 1
    return load


def radar(analysis: dict) -> list[dict]:
    """Список сигналов риска, отсортированных по важности.

    Каждый сигнал: {severity: high|medium|info, type, title, message, suggestion}.
    Все числа берутся из расчёта движка — здесь только пороги и формулировки.
    """
    s = analysis["summary"]
    tm = task_map(analysis)
    signals: list[dict] = []
    reserve = s.get('deadline_reserve', s['project_deadline'] - s['project_duration'] if s['project_deadline'] is not None else None)

    # --- неравномерное распределение задач --------------------------------- #
    load = {owner: value for owner, value in workload_by_owner(analysis).items()
            if owner != 'Без ответственного'}
    busiest = max(load.items(), key=lambda kv: kv[1]["active"], default=(None, None))
    fewest = min(load.items(), key=lambda kv: kv[1]["active"], default=(None, None))
    if busiest[0] is not None and len(load) > 1:
        diff = busiest[1]["active"] - fewest[1]["active"]
        if busiest[1]["active"] >= 3 and diff >= 2:
            risky = [n for n, t in tm.items()
                     if (t.get("owner") or "Без ответственного") == busiest[0] and t["at_risk"]]
            msg = (f"У {busiest[0]} — {busiest[1]['active']} незавершённых задач, "
                   f"у {fewest[0]} — {fewest[1]['active']}.")
            if risky:
                msg += " Среди них задачи с малым резервом: " + ", ".join(f"«{tm[r]['name']}»" for r in risky) + "."
            signals.append({
                "severity": "info", "type": "task_distribution",
                "title": "Неравномерное распределение задач",
                "message": msg,
                "suggestion": f"Обсудите перераспределение части задач с {busiest[0]} "
                              f"на {fewest[0]}; предварительно проверьте навыки и доступность.",
            })

    # --- дедлайн ------------------------------------------------------------ #
    if s["deadline_breached"]:
        signals.append({
            "severity": "high", "type": "deadline",
            "title": "Прогноз превышает дедлайн",
            "message": (f"Прогноз завершения — {date_label(s['forecast_finish_date'])}, дедлайн — "
                       f"{date_label(s['deadline_date'])}. Превышение — {s['delay_vs_deadline']} раб. дн."
                       if s.get('deadline_date') else f"Прогноз {_days(s['project_duration'])} против дедлайна "
                       f"{_days(s['project_deadline'])} — превышение {_days(s['delay_vs_deadline'])}."),
            "suggestion": "Проверьте возможность сократить объём или выполнить часть критических "
                          "работ параллельно; затем пересчитайте план. Альтернатива — согласовать дедлайн.",
        })
    elif any(t['status'] != 'done' for t in analysis['tasks']) and reserve is not None and 0 <= reserve <= 2:
        signals.append({
            "severity": "medium", "type": "tight_deadline",
            "title": "График впритык к дедлайну",
            "message": f"Запас до дедлайна всего {_days(reserve)} — "
                       "задержка на критическом пути, превышающая этот запас, нарушит срок.",
            "suggestion": "Держите критический путь под ежедневным контролем; найдите, "
                          "что можно ускорить заранее.",
        })

    # --- задачи под угрозой -------------------------------------------------- #
    for tid in s["at_risk"]:
        t = tm[tid]
        signals.append({
            "severity": "medium", "type": "at_risk",
            "title": f"Малый резерв: {t['name']}",
            "message": f"Задача «{t['name']}» на критическом пути, резерв {t['slack']} дн., "
                       f"ответственный — {t.get('owner') or 'не назначен'}.",
            "suggestion": "Уточните оставшуюся оценку и проверьте возможность сократить объём. "
                          "Переназначение обсуждайте с учётом навыков и доступности.",
        })

    for conflict in s.get('status_conflicts', []):
        t = tm[conflict['task_id']]
        waiting = ', '.join(tm[d]['name'] for d in conflict['unfinished_dependencies'])
        signals.append({
            'severity': 'medium', 'type': 'status_conflict',
            'title': f"Проверьте связи «{t['name']}»",
            'message': f"Задача {'выполнена' if t['status'] == 'done' else 'в работе'}, "
                       f"но предшественники не завершены: {waiting}. Прогноз требует проверки.",
            'suggestion': 'Уточните статусы и зависимости. Фактические даты неизвестны.',
        })

    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(signals, key=lambda x: order[x["severity"]])


def radar_text(signals: list[dict], limit: int = 5) -> str:
    if not signals:
        return 'Явных рисков по данным проекта не обнаружено.'
    icon = {"high": "🔴", "medium": "🟠", "info": "🔵"}
    lines = [f"{icon[x['severity']]} {x['title']}. {x['message']} → {x['suggestion']}"
             for x in signals[:limit]]
    return "РАДАР РИСКОВ:\n" + "\n".join(lines)


# --------------------------------------------------------------------------- #
#  2. Генерация чек-листов для сложных задач                                   #
# --------------------------------------------------------------------------- #

TEMPLATES: list[tuple[str, list[tuple[str, float]]]] = [
    (r"api|бэк|back|сервер|endpoint", [
        ("Спроектировать схему данных", 0.2),
        ("Реализовать основные эндпоинты", 0.45),
        ("Настроить авторизацию и валидацию", 0.15),
        ("Написать автотесты", 0.2)]),
    (r"разработ|код|реализ|программ", [
        ("Спроектировать решение", 0.2),
        ("Основная реализация", 0.5),
        ("Код-ревью и правки", 0.15),
        ("Тестирование модуля", 0.15)]),
    (r"тест|qa|проверк", [
        ("Написать тест-кейсы", 0.3),
        ("Прогнать ручное тестирование", 0.4),
        ("Оформить отчёт о дефектах", 0.3)]),
    (r"дизайн|ui|ux|интерфейс|макет", [
        ("Исследование и прототип", 0.3),
        ("Макеты экранов", 0.4),
        ("Согласование с заказчиком", 0.3)]),
    (r"аналит|требован|исследован", [
        ("Собрать требования (интервью)", 0.4),
        ("Задокументировать требования", 0.35),
        ("Утвердить с заказчиком", 0.25)]),
    (r"деплой|развёрт|release|приёмк", [
        ("Подготовить окружение", 0.4),
        ("Выкатка и проверка", 0.35),
        ("Приёмка и откат-план", 0.25)]),
    (r"документ|инструкц", [
        ("Написать черновик", 0.5),
        ("Вычитать и дополнить примерами", 0.3),
        ("Опубликовать", 0.2)]),
    (r"интеграц|миграц|соедин", [
        ("Согласовать контракты", 0.25),
        ("Интеграция и настройка", 0.5),
        ("Сквозная проверка", 0.25)]),
]

GENERIC_CHECKLIST = [
    ("Уточнить объём и критерии готовности", 0.25),
    ("Основная работа", 0.45),
    ("Проверка результата", 0.2),
    ("Сдать и задокументировать", 0.1)]


def suggest_checklist(name: str, duration: int, dependencies: list[str] | None = None,
                      owner: str = "") -> dict:
    """Чек-лист подзадач для новой/сложной задачи. Длительности делит система
    пропорционально шаблону (это арифметика планирования, не текст)."""
    deps = list(dependencies or [])
    dur = max(0, int(duration))
    pattern = None
    for rx, items in TEMPLATES:
        if re.search(rx, name, re.IGNORECASE):
            pattern = items
            break
    if pattern is None:
        pattern = GENERIC_CHECKLIST
    subs, used = [], 0
    for i, (sub_name, share) in enumerate(pattern):
        d = min(dur - used, max(0, round(dur * share))) if i < len(pattern) - 1 else dur - used
        used += d
        subs.append({"name": sub_name, "duration": d, "owner": owner,
                     "dependencies": deps if i == 0 else []})
    total = sum(x["duration"] for x in subs)
    return {"task_name": name, "original_duration": dur, "subtasks": subs,
            "checklist_total_duration": total,
            "note": ("Суммарная длительность подзадач больше исходной оценки — "
                     "проверьте суммарную длительность перед добавлением."
                     if total > dur else "Декомпозиция сохраняет общий срок задачи.")}


def checklist_text(sug: dict) -> str:
    lines = [f"Предлагаю разбить «{sug['task_name']}» ({_days(sug['original_duration'])}) "
             "на подзадачи:"]
    lines += [f"  {i+1}. {s['name']} — {s['duration']} дн."
              for i, s in enumerate(sug["subtasks"])]
    lines.append(f"Итого: {sug['checklist_total_duration']} дн. {sug['note']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  3. «Объясни простыми словами»                                               #
# --------------------------------------------------------------------------- #

def explain_task_simple(task_id: str, analysis: dict) -> str:
    """Цепочка причинности вокруг задачи: от чего зависит, что ждёт её, почему стоит."""
    tm = task_map(analysis)
    t = tm.get(task_id)
    if not t:
        return ("Данных по этой задаче нет — не могу ответить. "
                "Выберите задачу из списка проекта.")
    status = {'todo': 'к выполнению', 'in_progress': 'в работе', 'done': 'выполнена'}[t['status']]
    remaining = t.get('remaining_duration', 0 if t['status'] == 'done' else t['duration'])
    parts = [f"«{t['name']}»: осталось {remaining} раб. дн., ответственный — "
             f"{t.get('owner') or 'не назначен'}, статус — {status}."]

    waiting_on = [tm[d] for d in t["dependencies"] if d in tm and tm[d]["status"] != "done"]
    if waiting_on:
        chain = ', '.join(f"«{w['name']}»" for w in waiting_on)
        if t['status'] == 'todo':
            parts.append(f"По плану начало зависит от завершения: {chain}.")
        else:
            parts.append(f"Есть противоречие: задача {status}, но предшественники не завершены: {chain}. "
                         'Проверьте статусы и зависимости; прогноз по этим связям условный.')
    elif t['status'] == 'done':
        parts.append('Задача выполнена и не добавляет оставшейся работы. Фактическая дата завершения не задана.')
    elif t['status'] == 'in_progress':
        parts.append('Задача уже в работе. В прогнозе используется оставшаяся оценка.')
    else:
        parts.append('Незавершённых предшественников нет.' if t['dependencies'] else 'Предшественники не заданы.')
        if t.get('start_delay', 0):
            parts.append(f"Перед началом запланировано ожидание {t['start_delay']} раб. дн.")

    blockers = [x for x in analysis["tasks"]
                if task_id in x["dependencies"] and x["status"] != "done"]
    if blockers:
        parts.append('От задачи зависят: ' + ', '.join(f"«{b['name']}»" for b in blockers) + '.')
    if t['status'] != 'done':
        if t.get('planned_start_date'):
            parts.append(f"Оставшаяся работа по плану: {date_label(t['planned_start_date'])} — {date_label(t['planned_finish_date'])}.")
        parts.append(f"Резерв по текущему плану: {t['slack']} раб. дн.")
        if t['is_critical']:
            parts.append('Задача на критическом пути: увеличение оставшегося срока сдвигает прогноз завершения проекта.')
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
#  4. Песочница: сухой JSON-факт для мгновенной реакции панели ИИ              #
# --------------------------------------------------------------------------- #

def sandbox_json(before: dict, after: dict, diff: dict, moved_task_id: str,
                 shift_days: int) -> dict:
    """Формат вида {"task": ..., "shift": 3, "affected": [...], "deadline_shift": 2}.
    Frontend перетаскивает бар на timeline, бэкенд считает, здесь — только факт."""
    bt = task_map(before).get(moved_task_id, {})
    at = task_map(after).get(moved_task_id, {})
    blocked = [a["name"] for a in diff["affected_tasks"] if a.get("shift_days") and a['id'] != moved_task_id]
    s = after["summary"]
    slack_left = ((s["project_deadline"] - s["project_duration"])
                  if s["project_deadline"] is not None else None)
    slack_left = s.get('deadline_reserve', slack_left)
    return {
        "task_id": moved_task_id,
        "task": bt.get("name", moved_task_id),
        "owner": at.get("owner") or bt.get("owner") or "",
        "shift": at.get('early_start', 0) - bt.get('early_start', 0),
        "start_shift_days": at.get('early_start', 0) - bt.get('early_start', 0),
        "wait_change_days": int(shift_days),
        "new_finish": at.get("early_finish"),
        "old_start": bt.get('early_start'), "new_start": at.get('early_start'),
        "old_start_date": bt.get('planned_start_date'), "new_start_date": at.get('planned_start_date'),
        "old_finish_date": bt.get('planned_finish_date'), "new_finish_date": at.get('planned_finish_date'),
        "old_finish": bt.get('early_finish'), "task_duration": at.get('duration'),
        "new_start_delay": at.get('start_delay', 0),
        "affected": blocked,
        "now_at_risk": [task_map(after)[i]["name"] for i in diff["new_at_risk"]
                        if i in task_map(after)],
        "duration_delta": diff["duration_delta"],
        "deadline_shift": 0,
        "deadline_breached": s["deadline_breached"],
        "delay_vs_deadline": s["delay_vs_deadline"],
        "slack_left": slack_left,
        "risk": s['risk_assessment']['level'],
        "risk_basis": s['risk_assessment']['basis'],
    }
