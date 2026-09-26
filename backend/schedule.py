"""Ядро планирования: расчёт раннего/позднего старта, критического пути,
анализ последствий изменений и what-if симуляции.

Модель: проект = набор задач (id, name, duration в днях, dependencies).
Календарные даты не используются — всё в "рабочих днях от старта проекта",
что делает расчёты предсказуемыми и наглядными для демонстрации.
"""
from __future__ import annotations

from typing import Optional


def _topo_order(tasks: list[dict]) -> Optional[list[str]]:
    """Топологическая сортировка. None, если обнаружен цикл."""
    by_id = {t["id"]: t for t in tasks}
    indeg = {t["id"]: len([d for d in t.get("dependencies", []) if d in by_id]) for t in tasks}
    dependents: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for t in tasks:
        for d in t.get("dependencies", []):
            if d in dependents:
                dependents[d].append(t["id"])
    queue = [tid for tid, deg in indeg.items() if deg == 0]
    order: list[str] = []
    while queue:
        queue.sort()
        cur = queue.pop(0)
        order.append(cur)
        for nxt in dependents[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(tasks) else None


def analyze(tasks: list[dict], project_deadline: Optional[int] = None) -> dict:
    """Полный CPM-анализ списка задач.

    Возвращает для каждой задачи: early_start/finish, late_start/finish,
    slack (резерв времени), is_critical; плюс сводку по проекту.
    """
    if not tasks:
        return {"tasks": [], "summary": _empty_summary(project_deadline)}

    order = _topo_order(tasks)
    if order is None:
        raise ValueError("В зависимостях между задачами обнаружен цикл")

    by_id = {t["id"]: t for t in tasks}

    # Прямой проход: ранние старт/финиш.
    # Выполненные задачи считаются нулевой длительности, но их "факт" фиксируется:
    # completed задачи имеют ES=EF=progress_day (демо: считаем, что выполнены в срок).
    es: dict[str, int] = {}
    ef: dict[str, int] = {}
    for tid in order:
        t = by_id[tid]
        preds = [d for d in t.get("dependencies", []) if d in by_id]
        start = max((ef[d] for d in preds), default=0)
        if t.get('status') != 'done':
            start += max(0, int(t.get('start_delay', 0)))
        dur = 0 if t.get("status") == "done" else int(t.get("duration", 0))
        es[tid] = start
        ef[tid] = start + dur

    project_finish = max(ef.values())
    critical_ids = set()

    # Обратный проход: поздние старт/финиш относительно фактического финиша
    # (или дедлайна проекта, если он задан и больше финиша).
    horizon = project_finish
    if project_deadline is not None and project_deadline > horizon:
        horizon = project_deadline
    ls: dict[str, int] = {}
    lf: dict[str, int] = {}
    for tid in reversed(order):
        succs = [s for s in order if tid in by_id[s].get("dependencies", [])]
        finish = min((ls[s] - (max(0, int(by_id[s].get('start_delay', 0)))
                     if by_id[s].get('status') != 'done' else 0) for s in succs), default=horizon)
        dur = 0 if by_id[tid].get("status") == "done" else int(by_id[tid].get("duration", 0))
        lf[tid] = finish
        ls[tid] = finish - dur

    slack = {tid: ls[tid] - es[tid] for tid in by_id}
    # Критический путь — самая длинная цепочка зависимостей от старта до финиша.
    # (При заданном запасе до дедлайна резерв есть у всех, поэтому путь ищем
    #  структурно: по максимуму раннего финиша.)
    best_pred: dict[str, str | None] = {}
    for tid in order:
        preds = [d for d in by_id[tid].get("dependencies", []) if d in by_id]
        best_pred[tid] = max(preds, key=lambda p: ef[p]) if preds else None
    final = max(by_id, key=lambda t: ef[t])
    critical_ids: set[str] = set()
    cur: str | None = final
    while cur is not None:
        critical_ids.add(cur)
        cur = best_pred[cur]

    result_tasks = []
    for t in tasks:
        tid = t["id"]
        item = dict(t)
        on_path = tid in critical_ids
        # Задача «под угрозой», если она на критическом пути и её задержка
        # затронет срок проекта: нулевой резерв ИЛИ проект уже впритык к дедлайну.
        tight_vs_deadline = (
            project_deadline is not None and project_finish >= project_deadline - 2
        )
        at_risk = bool(
            on_path
            and t.get("status") != "done"
            and (slack[tid] <= 0 or tight_vs_deadline)
        )
        item.update(
            {
                "early_start": es[tid],
                "early_finish": ef[tid],
                "late_start": ls[tid],
                "late_finish": lf[tid],
                "slack": slack[tid],
                "is_critical": on_path,
                "at_risk": at_risk,
            }
        )
        result_tasks.append(item)

    deadline_breached = (
        project_deadline is not None and project_finish > project_deadline
    )
    summary = {
        "project_duration": project_finish,
        "project_deadline": project_deadline,
        "deadline_breached": deadline_breached,
        "delay_vs_deadline": (
            max(0, project_finish - project_deadline)
            if project_deadline is not None
            else 0
        ),
        "critical_path": _order_path(critical_ids, best_pred, ef),
        "at_risk": sorted([i["id"] for i in result_tasks if i["at_risk"]],
                          key=lambda x: es[x]),
        "has_cycle": False,
    }
    return {"tasks": result_tasks, "summary": summary}


def _order_path(ids: set, best_pred: dict, ef: dict) -> list[str]:
    """Разворачиваем критический путь как цепочку от финишной задачи назад."""
    if not ids:
        return []
    tail = max(ids, key=lambda t: ef[t])
    path = [tail]
    # разворот по цепочке «предок на пути»
    cur = best_pred.get(tail)
    while cur is not None and cur in ids:
        path.append(cur)
        cur = best_pred.get(cur)
    return list(reversed(path))


def _empty_summary(deadline):
    return {
        "project_duration": 0,
        "project_deadline": deadline,
        "deadline_breached": False,
        "delay_vs_deadline": 0,
        "critical_path": [],
        "at_risk": [],
        "has_cycle": False,
    }


def downstream_of(tasks: list[dict], task_id: str) -> list[str]:
    """Все задачи, транзитивно зависящие от task_id."""
    by_id = {t["id"]: t for t in tasks}
    children: dict[str, list[str]] = {t["id"]: [] for t in tasks}
    for t in tasks:
        for d in t.get("dependencies", []):
            if d in children:
                children[d].append(t["id"])
    seen: list[str] = []
    stack = children.get(task_id, [])[:]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.append(cur)
        stack.extend(children[cur])
    return [s for s in seen if s in by_id]


def diff_analysis(before: dict, after: dict) -> dict:
    """Сравнение двух результатов analyze(): что изменилось после правки."""
    b_tasks = {t["id"]: t for t in before["tasks"]}
    a_tasks = {t["id"]: t for t in after["tasks"]}
    changed = []
    for tid, at in a_tasks.items():
        bt = b_tasks.get(tid)
        if bt is None:
            changed.append({"id": tid, "name": at["name"], "type": "added"})
            continue
        fields = {}
        if bt["early_start"] != at["early_start"]:
            fields["shift_days"] = at["early_start"] - bt["early_start"]
        if bt["is_critical"] != at["is_critical"]:
            fields["criticality"] = "now_critical" if at["is_critical"] else "no_longer_critical"
        old_risk = tid in before["summary"]["at_risk"]
        new_risk = tid in after["summary"]["at_risk"]
        if new_risk and not old_risk:
            fields["risk"] = "now_at_risk"
        if fields:
            changed.append({"id": tid, "name": at["name"], **fields})
    for tid, bt in b_tasks.items():
        if tid not in a_tasks:
            changed.append({"id": tid, "name": bt["name"], "type": "removed"})

    bs, as_ = before["summary"], after["summary"]
    duration_delta = as_["project_duration"] - bs["project_duration"]
    deadline_now_breached = as_["deadline_breached"] and not bs["deadline_breached"]
    new_at_risk = [t for t in as_["at_risk"] if t not in bs["at_risk"]]
    requires_action = bool(
        duration_delta > 0 or deadline_now_breached or new_at_risk
        or any(a.get("shift_days", 0) > 0 for a in changed)
    )
    return {
        "affected_tasks": changed,
        "duration_delta": duration_delta,
        "new_duration": as_["project_duration"],
        "old_duration": bs["project_duration"],
        "deadline_breached": as_["deadline_breached"],
        "deadline_newly_breached": deadline_now_breached,
        "new_at_risk": new_at_risk,
        "requires_action": requires_action,
    }


def simulate(tasks: list[dict], changes: dict) -> list[dict]:
    """Что-if симуляция: применяет изменения к копии задач.

    changes: {task_id: {"duration": +N}} — дельта длительности,
             или {"remove_owner": true} — ответственный уходит в отпуск
             (задача замедляется на 50% дней, округление вверх),
             или {"set_done": true}.
    """
    import math

    sim = [dict(t) for t in tasks]
    by_id = {t["id"]: t for t in sim}
    for tid, ch in changes.items():
        t = by_id.get(tid)
        if not t:
            continue
        if "duration" in ch:
            t["duration"] = max(0, int(t.get("duration", 0)) + int(ch["duration"]))
        if 'start_delay' in ch:
            t['start_delay'] = max(0, int(t.get('start_delay', 0)) + int(ch['start_delay']))
        if ch.get("remove_owner"):
            extra = math.ceil(int(t.get("duration", 0)) * 0.5)
            t["duration"] = int(t.get("duration", 0)) + extra
        if ch.get("set_done"):
            t["status"] = "done"
    return sim
