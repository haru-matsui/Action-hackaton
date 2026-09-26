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
    """Загрузка сотрудников: активные незавершённые задачи на человека."""
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

    # --- перегрузка сотрудников -------------------------------------------- #
    load = {owner: value for owner, value in workload_by_owner(analysis).items()
            if owner != 'Без ответственного'}
    actives = [v["active"] for v in load.values()]
    busiest = max(load.items(), key=lambda kv: kv[1]["active"], default=(None, None))
    laziest = min(load.items(), key=lambda kv: kv[1]["active"], default=(None, None))
    if busiest[0] is not None and len(load) > 1:
        diff = busiest[1]["active"] - laziest[1]["active"]
        if busiest[1]["active"] >= 3 and diff >= 2:
            risky = [n for n, t in tm.items()
                     if (t.get("owner") or "Без ответственного") == busiest[0] and t["at_risk"]]
            msg = (f"{busiest[0]} ведёт {busiest[1]['active']} активных задач, "
                   f"тогда как у {laziest[0]} — {laziest[1]['active']}.")
            if risky:
                msg += " Под угрозой срыва: " + ", ".join(f"«{tm[r]['name']}»" for r in risky) + "."
            signals.append({
                "severity": "high", "type": "overload",
                "title": "Неравномерная загрузка сотрудников",
                "message": msg,
                "suggestion": f"Обсудите перераспределение части задач с {busiest[0]} "
                              f"на {laziest[0]}; предварительно проверьте навыки и доступность.",
            })

    # --- дедлайн ------------------------------------------------------------ #
    if s["deadline_breached"]:
        signals.append({
            "severity": "high", "type": "deadline",
            "title": "Срыв срока проекта",
            "message": f"Прогноз {_days(s['project_duration'])} против дедлайна "
                       f"{_days(s['project_deadline'])} — просрочка {_days(s['delay_vs_deadline'])}.",
            "suggestion": "Сократите критический путь (разбить/параллелить самую длинную "
                          "задачу пути) или согласуйте сдвиг дедлайна с заказчиком.",
        })
    elif s["project_deadline"] is not None and 0 <= s["project_deadline"] - s["project_duration"] <= 2:
        signals.append({
            "severity": "medium", "type": "tight_deadline",
            "title": "График впритык к дедлайну",
            "message": f"Запас до дедлайна всего {_days(s['project_deadline'] - s['project_duration'])} — "
                       "любая задержка на критическом пути сорвёт срок.",
            "suggestion": "Держите критический путь под ежедневным контролем; найдите, "
                          "что можно ускорить заранее.",
        })

    # --- задачи под угрозой -------------------------------------------------- #
    for tid in s["at_risk"]:
        t = tm[tid]
        signals.append({
            "severity": "medium", "type": "at_risk",
            "title": f"Под угрозой: {t['name']}",
            "message": f"Задача «{t['name']}» на критическом пути, резерв {t['slack']} дн., "
                       f"ответственный — {t.get('owner') or 'не назначен'}.",
            "suggestion": "Уточните прогресс сегодня; при необходимости усильте ресурсом "
                          "или снимите часть объёма.",
        })

    # --- «в работе», но старт уже просрочен --------------------------------- #
    for t in analysis["tasks"]:
        if t["status"] == "in_progress":
            waiting = [tm[d]['name'] for d in t['dependencies'] if d in tm and tm[d]['status'] != 'done']
            if waiting:
                signals.append({
                    "severity": "info", "type": "started_late",
                    "title": f"Проверьте старт «{t['name']}»",
                    "message": f"Задача в работе, хотя предшественники не завершены: {', '.join(waiting)}.",
                    "suggestion": "Уточните фактические статусы и необходимость указанных зависимостей.",
                })

    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(signals, key=lambda x: order[x["severity"]])


def radar_text(signals: list[dict], limit: int = 5) -> str:
    if not signals:
        return ("Радар рисков чист: перегрузки нет, дедлайн в резерве, "
                "задач под угрозой не обнаружено.")
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
    dur = max(1, int(duration))
    pattern = None
    for rx, items in TEMPLATES:
        if re.search(rx, name, re.IGNORECASE):
            pattern = items
            break
    if pattern is None:
        pattern = GENERIC_CHECKLIST
    subs, used = [], 0
    for i, (sub_name, share) in enumerate(pattern):
        d = max(1, round(dur * share)) if i < len(pattern) - 1 else max(1, dur - used)
        used += d
        subs.append({"name": sub_name, "duration": d, "owner": owner,
                     "dependencies": deps if i == 0 else []})
    total = sum(x["duration"] for x in subs)
    return {"task_name": name, "original_duration": dur, "subtasks": subs,
            "checklist_total_duration": total,
            "note": ("Суммарная длительность подзадач больше исходной оценки — "
                     "это нормально для декомпозиции, проверьте итог на timeline."
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
    parts = [f"«{t['name']}»: {t['duration']} дн., ответственный — "
             f"{t.get('owner') or 'не назначен'}, статус — {t['status']}."]

    waiting_on = [tm[d] for d in t["dependencies"] if d in tm and tm[d]["status"] != "done"]
    if waiting_on:
        chain = ", ".join(
            f"«{w['name']}»" + (f" (ждёт: {', '.join(tm[p]['name'] for p in w['dependencies'] if p in tm)},"
                                f" ответственный {w.get('owner') or '—'})" if w["dependencies"] else "")
            for w in waiting_on)
        parts.append(f"Ты не можешь начать «{t['name']}», пока не закончатся: {chain}.")
    else:
        parts.append("Все предшественники выполнены — задача может идти прямо сейчас.")

    blockers = [x for x in analysis["tasks"]
                if task_id in x["dependencies"] and x["status"] != "done"]
    if blockers:
        parts.append("Из-за неё стоят: " + ", ".join(f"«{b['name']}»" for b in blockers) + ".")
    parts.append(("Задача на КРИТИЧЕСКОМ пути (резерв " + str(t["slack"]) +
                  " дн.): любой её день просрочки двигает весь проект.")
                 if t["is_critical"] else
                 ("Резерв " + str(t["slack"]) + " дн.: небольшая задержка не тронет срок проекта.")
                 )
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
#  4. Песочница: сухой JSON-факт для мгновенной реакции панели ИИ              #
# --------------------------------------------------------------------------- #

def risk_level(deadline_breached: bool, delay: int, slack_left: int) -> str:
    if deadline_breached:
        return "высокий"
    if delay > 0 or slack_left <= 0:
        return "средний"
    if slack_left <= 2:
        return "умеренный"
    return "низкий"


def sandbox_json(before: dict, after: dict, diff: dict, moved_task_id: str,
                 shift_days: int) -> dict:
    """Формат вида {"task": ..., "shift": 3, "affected": [...], "deadline_shift": 2}.
    Frontend перетаскивает бар на timeline, бэкенд считает, здесь — только факт."""
    bt = task_map(before).get(moved_task_id, {})
    at = task_map(after).get(moved_task_id, {})
    blocked = [a["name"] for a in diff["affected_tasks"] if a.get("shift_days") and a['id'] != moved_task_id]
    s = after["summary"]
    slack_left = ((s["project_deadline"] - s["project_duration"])
                  if s["project_deadline"] is not None else 999)
    return {
        "task_id": moved_task_id,
        "task": bt.get("name", moved_task_id),
        "owner": at.get("owner") or bt.get("owner") or "",
        "shift": int(shift_days),
        "new_finish": at.get("early_finish"),
        "old_start": bt.get('early_start'), "new_start": at.get('early_start'),
        "old_finish": bt.get('early_finish'), "task_duration": at.get('duration'),
        "new_start_delay": at.get('start_delay', 0),
        "affected": blocked,
        "now_at_risk": [task_map(after)[i]["name"] for i in diff["new_at_risk"]
                        if i in task_map(after)],
        "duration_delta": diff["duration_delta"],
        "deadline_shift": max(0, diff["duration_delta"]),
        "deadline_breached": s["deadline_breached"],
        "delay_vs_deadline": s["delay_vs_deadline"],
        "slack_left": slack_left,
        "risk": risk_level(s["deadline_breached"], s["delay_vs_deadline"], slack_left),
    }
