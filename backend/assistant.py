"""ИИ-ассистент руководителя проектов (counter-feature).

Ассистент НЕ считает даты и НЕ строит зависимости — он получает от системы
готовые структурированные результаты CPM-анализа и симуляций и интерпретирует
их человеческим языком: объясняет последствия изменений, предлагает решения,
отвечает на вопросы «что будет, если…» и формирует отчёты.

Этот модуль разбирает типовые сценарии и готовит резервные ответы.
Flask-маршруты передают рассчитанные факты DeepSeek через ai_service.
Если модель недоступна, интерфейс явно обозначает ответ расчётного движка.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

import ai_features
from ai_service import SYSTEM_PROMPT, call_llm, llm_available  # noqa: F401 — реэкспорт


# --------------------------------------------------------------------------- #
#  Детерминированная интерпретация (работает всегда, без сети)                #
# --------------------------------------------------------------------------- #

def _tname(analysis: dict, tid: str) -> str:
    for t in analysis["tasks"]:
        if t["id"] == tid:
            return t["name"]
    return tid


def explain_change(before: dict, after: dict, diff: dict, changed_task_name: str,
                   subject_label: str | None = None) -> str:
    subject = subject_label or f"задаче «{changed_task_name}»"
    lines = [f"Изменение по {subject} проанализировано."]
    dd = diff["duration_delta"]
    if dd > 0:
        lines.append(f"• Общий срок проекта увеличился с {diff['old_duration']} до "
                     f"{diff['new_duration']} рабочих дней (+{dd} дн.).")
    elif dd < 0:
        lines.append(f"• Общий срок проекта сократился на {-dd} дн. — теперь "
                     f"{diff['new_duration']} дн. Это хорошая новость.")
    else:
        lines.append("• Общий срок проекта не изменился — изменение попало в резерв.")

    affected = [a for a in diff["affected_tasks"] if a.get("shift_days")
                and ("downstream" not in diff or a['id'] in diff['downstream'])]
    if affected:
        names = ", ".join(f"«{a['name']}» ({a['shift_days']:+d} дн.)" for a in affected[:6])
        lines.append(f"• Сдвинулись последующие задачи: {names}.")
    newly_crit = [a for a in diff["affected_tasks"] if a.get("criticality") == "now_critical"]
    if newly_crit:
        lines.append("• Задачи стали критическими (потеряли резерв): "
                     + ", ".join(f"«{a['name']}»" for a in newly_crit) + ".")
    if diff["deadline_newly_breached"]:
        s = after["summary"]
        lines.append(f"⚠ ВНИМАНИЕ: проект вышел за дедлайн ({s['project_deadline']} дн.), "
                     f"просрочка {s['delay_vs_deadline']} дн. Требуется вмешательство руководителя.")
    elif diff["deadline_breached"]:
        s = after["summary"]
        lines.append(f"Проект по-прежнему превышает дедлайн на {s['delay_vs_deadline']} дн.")
    if not diff["requires_action"]:
        lines.append("Дополнительное вмешательство из-за этого изменения не требуется.")
    lines.append("Рекомендации: " + _recommend(after, diff))
    return "\n".join(lines)


def _recommend(after: dict, diff: dict | None = None) -> str:
    recs = []
    s = after["summary"]
    cp = s["critical_path"]
    if s["deadline_breached"]:
        over = s["delay_vs_deadline"]
        recs.append(f"сократить критический путь минимум на {over} дн.: разбить самую "
                    "длинную задачу пути на параллельные подзадачи или добавить ресурс;")
        recs.append("как альтернатива — согласовать с заказчиком сдвиг дедлайна;")
    if cp:
        last = _tname(after, cp[-1])
        recs.append(f"усилить контроль по критическому пути (финиш — «{last}»);")
    risk = s["at_risk"]
    if risk:
        recs.append("задачи с малым резервом держать в еженедельном мониторинге: "
                    + ", ".join(f"«{_tname(after, r)}»" for r in risk[:4]) + ";")
    owners = {}
    for t in after["tasks"]:
        if t.get("status") != "done" and t.get("is_critical"):
            owners.setdefault(t.get("owner", "—"), []).append(t["name"])
    overload = {o: ts for o, ts in owners.items() if len(ts) >= 2}
    if overload:
        o, ts = next(iter(overload.items()))
        recs.append(f"сотрудник {o} ведёт несколько критических задач («{'», «'.join(ts)}») — "
                    "обсудите переназначение части задач после проверки навыков и доступности;")
    if not recs:
        recs.append("план устойчив: действуйте по текущему графику, резервы достаточны.")
    return " ".join(recs)


def report(project: dict, analysis: dict) -> str:
    s = analysis["summary"]
    tasks = analysis["tasks"]
    done = [t for t in tasks if t["status"] == "done"]
    active = [t for t in tasks if t["status"] == "in_progress"]
    todo = [t for t in tasks if t["status"] == "todo"]
    total_dur = sum(int(t.get("duration", 0)) for t in tasks)
    done_dur = sum(int(t.get("duration", 0)) for t in done)
    pct = round(100 * done_dur / total_dur) if total_dur else 0
    status = "ПОД УГРОЗОЙ" if s["deadline_breached"] else ("требует внимания" if s["at_risk"] else "в норме")
    lines = [
        f"ОТЧЁТ ПО ПРОЕКТУ «{project['name']}» — статус: {status}",
        f"• Прогноз длительности: {s['project_duration']} раб. дн."
        + (f", дедлайн: {s['project_deadline']} дн." if s["project_deadline"] else ""),
        f"• Готовность по трудоёмкости: {pct}%.",
        f"• Выполнено: {len(done)} из {len(tasks)} задач"
        + (f"; в работе: {len(active)}; к выполнению: {len(todo)}." if tasks else "."),
        "• Критический путь: " + (" → ".join(_tname(analysis, c) for c in s["critical_path"]) or "—"),
        "• Завершённые задачи: " + (", ".join(t['name'] for t in done) or "нет"),
        "• Незавершённые задачи: " + (", ".join(t['name'] for t in tasks if t['status'] != 'done') or "нет"),
    ]
    if s["deadline_breached"]:
        lines.append(f"⚠ ПРОСРОЧКА ДЕДЛАЙНА: прогноз {s['project_duration']} дн. против "
                     f"{s['project_deadline']} дн. (+{s['delay_vs_deadline']} дн.) — требуется вмешательство.")
    if s["at_risk"]:
        lines.append("• Под угрозой (на критическом пути, запас проекта мал): "
                     + ", ".join(f"«{_tname(analysis, r)}»" for r in s["at_risk"]))
    problems = []
    if s["deadline_breached"]:
        problems.append(f"просрочка дедлайна на {s['delay_vs_deadline']} дн.")
    for t in tasks:
        if t["status"] == "in_progress" and t["slack"] <= 0:
            problems.append(f"задача «{t['name']}» в работе, но без резерва времени")
    lines.append("• Главные проблемы: " + ("; ".join(problems) if problems else "критичных проблем нет.")
                 )
    need = "ДА, требуется внимание руководителя." if (s["deadline_breached"] or problems or s['at_risk']) \
        else "Нет — команда справляется по плану."
    lines.append(f"• Вывод: {need}")
    return "\n".join(lines)


WHAT_IF_RE = re.compile(
    r"(?:(?:что\s+будет|что\s+произойдет|что\s+случится|как\s+повлияет)"
    r"(?:\s+если)?|\bесли\b)",
    re.IGNORECASE,
)

# Конец вопросительного предложения (для извлечения «хвоста» после фразы-триггера)
SENT_END_RE = re.compile(r"[.?!](?=\s|$)")


def _what_if_query(message: str) -> str:
    """Возвращает содержательную часть what-if-вопроса.

    Триггер («что будет если», «как повлияет», «если …») может стоять в начале
    или в конце предложения: «Что если X задержится?» и «X задержится — как
    повлияет?» оба сводятся к тексту про изменение.
    """
    m = WHAT_IF_RE.search(message)
    if not m:
        return message
    tail = message[m.end():].strip().lstrip(",:?—- ").rstrip("?!.")
    if tail:
        return tail
    head = SENT_END_RE.split(message)[0]  # текст до конца вопросительного предложения
    head = re.sub(WHAT_IF_RE, "", head).strip(" ,:?—-.")
    return head or message

# Скрытый what-if: вопрос без «что если», но с явным гипотетическим сценарием
# («Иванов уйдёт в отпуск…», «задача X задержится на неделю…»)
HYPOTHETICAL_RE = re.compile(
    r"(уйдёт|уйдет|уходит|возьмёт|возьмет|уедет|в\s+отпуске|забол|больничн|"
    r"сгорит|выгор|недоступен|увол|задержится|сорвётся|сорвется|сдвинется|"
    r"удлинится|затянется|выполним|закроем|готово)",
    re.IGNORECASE,
)
_NUM_WORD = {
    "один": 1, "одну": 1, "две": 2, "двумя": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "месяц": 20, "два": 2, "десять": 10,
}


def _find_task(tasks: list[dict], text: str) -> dict | None:
    tl = text.lower()
    best = None
    for t in tasks:
        name = t["name"].lower()
        words = [w for w in re.split(r"\W+", name) if len(w) >= 4]
        # совпадение по полному названию либо по ВСЕМ значимым словам названия
        # (например «разработка backend» → «Разработка backend»)
        if name in tl or (words and all(w in tl for w in words)):
            if best is None or len(name) > len(best["name"]):
                best = t
    return best


def _tasks_of_owner(tasks: list[dict], owner_words: list[str]) -> list[dict]:
    ow = " ".join(owner_words).lower()
    return [t for t in tasks if t.get("owner") and (
        all(w in t["owner"].lower() for w in owner_words) or ow in t["owner"].lower())]


OWNER_RE = re.compile(
    r"(?:если\s+)?([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){0,2})\s+"
    r"(?:уйдёт|уйдет|уходит|возьмёт|возьмет|сгорит|забол|недоступен|в отпуске|уедет|уедет в отпуск)")


def _extract_days(text: str) -> int:
    m = re.search(r"(\d+)\s*(?:дн|день|дня|дней|days?)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    tl = text.lower()
    if "недел" in tl:
        n = 1
        m2 = re.search(r"(одна|один|одну|две|двумя|три|четыре|пять)\s+\w*недел", tl)
        if m2:
            n = {"одна": 1, "один": 1, "одну": 1, "две": 2, "двумя": 2,
                 "три": 3, "четыре": 4, "пять": 5}[m2.group(1)]
        elif re.search(r"\b(\d+)\s*\w*недел", tl):
            n = int(re.search(r"\b(\d+)\s*\w*недел", tl).group(1))
        return n * 5
    for w, v in _NUM_WORD.items():
        if re.search(rf"\b{w}\b", tl):
            return v
    return 5  # по умолчанию — неделя


def answer_what_if(question: str, project: dict, analysis: dict) -> tuple[str, dict]:
    """Разбор вопроса «что если…», симуляция на данных системы, ответ."""
    from schedule import analyze as run_analyze, simulate, downstream_of, diff_analysis

    q = _what_if_query(question).strip().rstrip("!.")
    ql = q.lower()
    tasks = project["tasks"]
    before = analysis

    # --- Сценарий: сотрудник уходит в отпуск / на больничный ---------------
    vacation_words = ("отпуск", "увол", "забол", "больничн", "недоступ", "уедет", "выгор")
    if any(w in ql for w in vacation_words):
        om = OWNER_RE.search(q)
        owned = _tasks_of_owner(tasks, om.group(1).split()) if om else []
        if not owned:
            owned_t = _find_task(tasks, ql)
            owned = [owned_t] if owned_t else []
        owned = [t for t in owned if t.get("status") != "done"]
        if not owned:
            who = om.group(1) if om else "этот сотрудник"
            return (f"Данных недостаточно: не удалось найти незавершённые задачи сотрудника «{who}». "
                    "Уточните имя из проекта. Последствия отпуска не рассчитаны.",
                    {'type': 'insufficient_data'})
        changes = {t["id"]: {"remove_owner": True} for t in owned}
        sim_tasks = simulate(tasks, changes)
        try:
            after = run_analyze(sim_tasks, project.get("deadline"))
        except ValueError:
            return ("После такого изменения в графике возникает цикл зависимостей — "
                    "проверьте связи задачи.", {})
        diff = diff_analysis(before, after)
        names = ", ".join(f"«{t['name']}»" for t in owned)
        who = om.group(1) if om else owned[0].get("owner", "ответственный")
        assumption = ('Условная модель отсутствия: длительность каждой незавершённой задачи '
                      'сотрудника увеличивается на 50%, с округлением добавки вверх. '
                      'Даты отпуска и возможность замены неизвестны. Это допущение, не факт.')
        head = f"СИМУЛЯЦИЯ БЕЗ СОХРАНЕНИЯ: {who}, задачи: {names}. {assumption}"
        body = explain_change(before, after, diff, who, subject_label=f"персоне «{who}»")
        extra = ""
        others = sorted({t["owner"] for t in tasks
                         if t["owner"] and t["owner"] != owned[0].get("owner")})
        if others:
            extra = ("\nВариант решения: переназначить часть задач на "
                     + ", ".join(others[:4]) + ". Сначала проверьте навыки и доступность; эффект переназначения не рассчитан.")
        payload = {"question": question, "simulation": changes, "diff": diff,
                   "affected_owner_tasks": [t["id"] for t in owned],
                   "assumptions": [assumption], "after": after, "saved": False}
        return f"{head}\n{body}{extra}", payload

    # --- Сценарии по конкретной задаче --------------------------------------
    target = _find_task(tasks, ql)
    if not target:
        return ("Я не смог определить задачу, о которой идёт речь. Уточните название задачи "
                "из списка проекта — и я смоделирую последствия.", {})

    changes: dict[str, dict] = {}
    desc = ""
    if "сдвин" in ql or "задерж" in ql or "сорв" in ql or "позже" in ql or "больше" in ql or "дольше" in ql or "сложнее" in ql or "передел" in ql or "неделя" in ql or "недели" in ql or "дней" in ql or "день" in ql:
        days = _extract_days(ql)
        changes[target["id"]] = {"duration": days}
        desc = f"срок задачи сдвинется на {days} дн."
    elif "быстрее" in ql or "раньше" in ql or "успе" in ql or "сокр" in ql or "меньше" in ql:
        days = _extract_days(ql)
        changes[target["id"]] = {"duration": -days}
        desc = f"задача завершится на {days} дн. раньше"
    elif "завершим" in ql or "сделаем" in ql or "закроем" in ql or "готова" in ql:
        changes[target["id"]] = {"set_done": True}
        desc = "задача будет выполнена досрочно"
    else:
        days = _extract_days(ql)
        changes[target["id"]] = {"duration": days}
        desc = f"задержка составит {days} дн."

    sim_tasks = simulate(tasks, changes)
    try:
        after = run_analyze(sim_tasks, project.get("deadline"))
    except ValueError:
        return ("После такого изменения в графике возникает цикл зависимостей — "
                "проверьте связи задачи.", {})
    diff = diff_analysis(before, after)
    touched = downstream_of(tasks, target["id"])

    head = f"СИМУЛЯЦИЯ: если по задаче «{target['name']}» {desc}…"
    body = explain_change(before, after, diff, target["name"])
    payload = {"question": question, "simulation": changes, "diff": diff,
               "downstream": touched, "after_summary": after["summary"], "after": after, "saved": False}
    return f"{head}\n{body}", payload


def chat(message: str, project: dict, analysis: dict) -> tuple[str, dict]:
    """Главная точка входа ассистента."""
    ml = message.lower().strip()
    payload: dict = {}

    if WHAT_IF_RE.search(message):
        return answer_what_if(message, project, analysis)

    # Скрытый what-if: «Иванов уйдёт в отпуск на неделю», «Тест задержится на 3 дня» —
    # тоже моделируем, а не отвечаем рекомендациями по текущему состоянию.
    if HYPOTHETICAL_RE.search(message):
        return answer_what_if("что будет если " + message, project, analysis)

    if any(w in ml for w in ("отчет", "отчёт", "доклад", "статус проекта", "выжимк", "report")):
        return report(project, analysis), {"type": "report"}

    # --- Проактивный радар рисков ------------------------------------------- #
    if any(w in ml for w in ("радар", "перегруз", "загрузк", "нагрузк", "распредели",
                             "кого не хватает", "кто занят", "рискам", "по рискам")):
        signals = ai_features.radar(analysis)
        return (ai_features.radar_text(signals),
                {"type": "radar", "signals": signals})

    # --- «Объясни простыми словами» по конкретной задаче --------------------- #
    if any(w in ml for w in ("объясн", "почему стоит", "почему блокир", "простыми словам",
                             "что не так с", "из-за чего")):
        t = _find_task(analysis["tasks"], ml)
        if not t:
            return ("Данных недостаточно: назовите задачу из списка проекта — "
                    "и я объясню простыми словами, почему она стоит и что от неё зависит.",
                    {"type": "explain"})
        text = ai_features.explain_task_simple(t["id"], analysis)
        payload = {"type": "explain", "task_id": t["id"]}
        return text, payload

    # --- Чек-лист: «разбей задачу X на подзадачи» ----------------------------- #
    if any(w in ml for w in ("чек-лист", "чеклист", "checklist", "разбей", "разложи",
                             "подзадач", "декомпозиц")):
        t = _find_task(analysis["tasks"], ml)
        if not t:
            return ("Не могу применить чек-лист: задача не найдена в проекте. "
                    "Уточните название задачи — система предложит декомпозицию.", {})
        sug = ai_features.suggest_checklist(t["name"], int(t.get("duration") or 5),
                                            t.get("dependencies", []), t.get("owner", ""))
        return (ai_features.checklist_text(sug) +
                "\n\nНажмите «Развернуть чек-лист» в карточке задачи, чтобы добавить "
                "подзадачи в проект автоматически.",
                {"type": "checklist", "suggestion": sug, "task_id": t["id"]})

    if any(w in ml for w in ("рекомендац", "совет", "что делать", "как исправить", "решени")):
        return ("Рекомендации по текущему состоянию:\n" + _recommend(analysis), {"type": "advice"})

    if any(w in ml for w in ("критич", "главн", "важн", "приорите")):
        cp = analysis["summary"]["critical_path"]
        if cp:
            chain = " → ".join(_tname(analysis, c) for c in cp)
            return (f"Наиболее критичные задачи — это критический путь: {chain}. "
                    "Любая задержка здесь двигает весь проект. Держите их под ежедневным контролем.",
                    {"type": "critical"})
        return "Сейчас нет задач с нулевым резервом — прямых критических угроз нет.", {"type": "critical"}

    if any(w in ml for w in ("угроз", "риск", "проблем")):
        risk = analysis["summary"]["at_risk"]
        if analysis["summary"]["deadline_breached"]:
            return ("Главная угроза: прогноз проекта превышает дедлайн на "
                    f"{analysis['summary']['delay_vs_deadline']} дн. " + _recommend(analysis),
                    {"type": "risk"})
        if risk:
            return ("Задачи под угрозой (на критическом пути при малом запасе проекта): "
                    + ", ".join(f"«{_tname(analysis, r)}»" for r in risk)
                    + ". По ним стоит уточнить прогресс уже сегодня.", {"type": "risk"})
        return "Задач под угрозой нет — у всех незавершённых работ достаточный резерв времени.", {"type": "risk"}

    if any(w in ml for w in ("привет", "здравств", "помощь", "help", "что ты умеешь")):
        return ("Я ИИ-ассистент руководителя проектов. Я получаю от системы готовые расчёты "
                "и объясняю их простым языком. Спросите:\n"
                "• «Что будет, если задача X задержится на неделю?»\n"
                "• «Что будет, если Иванов уйдёт в отпуск?»\n"
                "• «Дай отчёт по проекту»\n"
                "• «Какие задачи критичны?» / «Что делать?»\n"
                "Также при каждом изменении задачи я автоматически объясняю последствия.",
                {"type": "help"})

    return ("Я анализирую последствия изменений в проекте на основе расчётов системы. "
            "Попробуйте вопрос со слов «что будет если…» или попросите отчёт по проекту.",
            {"type": "fallback"})


# --------------------------------------------------------------------------- #
#  Опциональный LLM-слой (вынесен в ai_service.py; здесь — обратная совместимость)
# --------------------------------------------------------------------------- #

def enhance_with_llm(user_message: str, system_facts: str) -> str | None:
    """Если задан OPENAI_API_KEY — переформулировать ответ ассистента через LLM.
    LLM получает ТОЛЬКО готовые факты от системы, сам ничего не считает."""
    if not llm_available():
        return None
    try:
        payload = json.loads(system_facts)
    except ValueError:
        payload = {"facts_text": system_facts}
    return call_llm(payload, user_message)
