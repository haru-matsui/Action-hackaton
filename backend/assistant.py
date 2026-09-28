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
from planning_calendar import date_label
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
    labels = {'name': 'Название', 'duration': 'Оценка, раб. дн.', 'start_delay': 'Ожидание, раб. дн.',
              'status': 'Статус', 'owner': 'Ответственный', 'dependencies': 'Предшественники',
              'early_start': 'Начало, рабочий день', 'early_finish': 'Окончание, рабочий день',
              'slack': 'Резерв, раб. дн.', 'planned_start_date': 'Начало оставшейся работы',
              'planned_finish_date': 'Завершение по плану'}
    dated = after.get('calendar', {}).get('configured')
    if dated:
        labels.pop('early_start'); labels.pop('early_finish')
    statuses = {'todo': 'к выполнению', 'in_progress': 'в работе', 'done': 'выполнено'}
    def shown(field, value, analysis):
        if value is None:
            return '—'
        if field == 'dependencies':
            return ', '.join(_tname(analysis, tid) for tid in value) or 'нет'
        if field == 'status':
            return statuses.get(value, value)
        if field in ('planned_start_date', 'planned_finish_date'):
            return date_label(value)
        return str(value) if value != '' else 'не назначен'
    for item in diff.get('edited_tasks', [])[:6]:
        parts = []
        for field, change in {**item['changes'], **item['schedule_changes']}.items():
            if field in labels:
                parts.append(f"{labels[field]}: {shown(field, change['before'], before)} → {shown(field, change['after'], after)}")
        lines.append(f"• «{item['name']}»: " + '; '.join(parts) + '.')
    if any('owner' in t['changes'] for t in diff.get('edited_tasks', [])):
        lines.append('Смена ответственного сама по себе не сокращает оценку: навыки и доступность не заданы.')
    dd = diff["duration_delta"]
    if dated:
        finish = after['summary'].get('forecast_finish_date')
        lines.append(f"• Прогноз завершения: {date_label(finish)}. Осталось {diff['new_duration']} раб. дн."
                     if finish else '• Незавершённых задач нет. Фактическая дата завершения не записана.')
        if before['summary'].get('forecast_finish_date') and dd:
            lines.append(f"Ранее прогноз: {date_label(before['summary']['forecast_finish_date'])}; изменение {dd:+d} раб. дн.")
    elif dd > 0:
        lines.append(f"• Общий срок проекта увеличился с {diff['old_duration']} до "
                     f"{diff['new_duration']} рабочих дней (+{dd} дн.).")
    elif dd < 0:
        lines.append(f"• Общий срок проекта сократился на {-dd} дн. — теперь "
                     f"{diff['new_duration']} дн. Это хорошая новость.")
    else:
        lines.append(f"• Прогноз завершения не изменился: {diff['new_duration']} рабочих дней.")

    affected = [a for a in diff.get('consequences', diff['affected_tasks']) if a.get("shift_days")
                and ("downstream" not in diff or a['id'] in diff['downstream'])]
    if affected:
        names = ", ".join(f"«{a['name']}» ({a['shift_days']:+d} дн.)" for a in affected[:6])
        lines.append(f"• Сдвинулись последующие задачи: {names}.")
    newly_crit = [a for a in diff["affected_tasks"] if a.get("criticality") == "now_critical"]
    if newly_crit:
        lines.append("• Задачи стали критическими (определяют прогноз завершения): "
                     + ", ".join(f"«{a['name']}»" for a in newly_crit) + ".")
    if diff["deadline_newly_breached"]:
        s = after["summary"]
        deadline = date_label(s['deadline_date']) if dated else f"{s['project_deadline']} дн."
        lines.append(f"⚠ Прогноз превышает дедлайн ({deadline}), "
                     f"превышение по прогнозу {s['delay_vs_deadline']} дн. Требуется вмешательство руководителя.")
    elif diff["deadline_breached"]:
        s = after["summary"]
        lines.append(f"Проект по-прежнему превышает дедлайн на {s['delay_vs_deadline']} дн.")
    if after['summary'].get('status_conflicts'):
        lines.append('Статусы задач противоречат зависимостям. Проверьте их: прогноз по этим связям условный.')
    if diff.get('existing_issues_remain'):
        lines.append('Ранее выявленные проблемы сохраняются и требуют внимания.')
    elif not diff["requires_action"]:
        lines.append("Дополнительное вмешательство из-за этого изменения не требуется.")
    lines.append("Рекомендации: " + _recommend(after, diff))
    return "\n".join(lines)


def _recommend(after: dict, diff: dict | None = None) -> str:
    recs = []
    s = after["summary"]
    cp = s["critical_path"]
    if s.get('status_conflicts'):
        recs.append('проверьте противоречивые статусы и зависимости перед принятием решений по прогнозу;')
    if s["deadline_breached"]:
        over = s["delay_vs_deadline"]
        recs.append(f"для соблюдения дедлайна прогноз нужно сократить на {over} дн.; проверьте "
                    "возможность сократить объём или выполнить часть работ параллельно, затем пересчитайте план;")
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
        if t.get("status") != "done" and t.get("is_critical") and t.get('owner'):
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
    from schedule import progress_summary
    progress = s.get('progress', progress_summary(tasks))
    pct = progress['completion_percent_by_task_count']
    signals = ai_features.radar(analysis)
    status = 'под угрозой' if s['deadline_breached'] else 'требует внимания' if signals else 'в норме'
    lines = [
        f"ОТЧЁТ ПО ПРОЕКТУ «{project['name']}» — статус: {status}",
        f"• Прогноз завершения: через {s['project_duration']} раб. дн. от точки планирования."
        + (f" Дедлайн — рабочий день {s['project_deadline']} от той же точки." if s['project_deadline'] is not None else ' Дедлайн не задан.'),
        f"• Выполнено задач: {len(done)} из {len(tasks)} ({pct}%).",
        f"• В работе: {len(active)}; к выполнению: {len(todo)}.",
        ('• Критические задачи всех веток: ' if s.get('critical_branching') else '• Критический путь: ')
        + ((', ' if s.get('critical_branching') else ' → ').join(_tname(analysis, c) for c in
           (s['critical_tasks'] if s.get('critical_branching') else s['critical_path'])) or '—'),
        '• Завершённые задачи: ' + (', '.join(t['name'] for t in done) or 'нет'),
        '• Незавершённые задачи: ' + (', '.join(t['name'] for t in tasks if t['status'] != 'done') or 'нет'),
    ]
    if analysis.get('calendar', {}).get('configured'):
        lines[1] = (f"• Прогноз завершения: {date_label(s['forecast_finish_date'])}. Осталось {s['project_duration']} раб. дн."
                    if s.get('forecast_finish_date') else '• Незавершённых задач нет. Фактическая дата завершения не записана.')
        lines[1] += f" Дедлайн — {date_label(s['deadline_date'])}." if s.get('deadline_date') else ' Дедлайн не задан.'
        lines.insert(1, f"• По состоянию на {date_label(analysis['calendar']['today'])}.")
    if s['deadline_breached']:
        lines.append(f"• Превышение дедлайна по прогнозу: {s['delay_vs_deadline']} раб. дн.")
    if s.get('status_conflicts'):
        lines.append('• Статусы противоречат зависимостям. Прогноз условный до проверки этих данных.')
    lines.append('• Главные проблемы: ' + ('; '.join(signal['message'] for signal in signals[:3])
                                         if signals else 'явных рисков по имеющимся данным не обнаружено.'))
    lines.append('• Вывод: ' + ('требуется внимание руководителя.' if signals
                               else 'по имеющимся данным вмешательство не требуется.'))
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

# Only explicit task scenarios are supported. Absence is not a scheduling model.
ABSENCE_RE = re.compile(r'отпуск|увол|забол|больничн|недоступ|уедет|выгор', re.IGNORECASE)
HYPOTHETICAL_RE = re.compile(
    r'(задержится|сорвётся|сорвется|сдвинется|удлинится|затянется|выполним|закроем|готово|раньше|позже|ускор|сократ)',
    re.IGNORECASE,
)


def unsupported_absence():
    return ('Этот сценарий не поддерживается. Можно проверить изменение срока конкретной задачи.',
            {'type': 'unsupported_scenario', 'saved': False})


_NUM_WORD = {
    'ноль': 0, 'один': 1, 'одна': 1, 'одну': 1, 'два': 2, 'две': 2,
    'три': 3, 'четыре': 4, 'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8,
    'девять': 9, 'десять': 10, 'одиннадцать': 11, 'двенадцать': 12,
    'тринадцать': 13, 'четырнадцать': 14, 'пятнадцать': 15,
    'шестнадцать': 16, 'семнадцать': 17, 'восемнадцать': 18,
    'девятнадцать': 19, 'двадцать': 20,
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


def _scenario_task(tasks, text):
    """Only choose an unambiguous task; nested names prefer the full match."""
    matches = []
    for task in tasks:
        name = task['name'].casefold().strip()
        for found in re.finditer(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text):
            matches.append((task, found.span()))
    matches = [(task, span) for task, span in matches if not any(
        other[0] <= span[0] and other[1] >= span[1] and other != span
        for _, other in matches)]
    ids = {task['id'] for task, _ in matches}
    if len(ids) == 1:
        target = matches[0][0]
        for _, (start, end) in sorted(matches, key=lambda item: item[1], reverse=True):
            text = text[:start] + ' ' * (end-start) + text[end:]
        return target, text
    if matches:
        return None, text
    # A partial name is accepted only if every significant word is present.
    words = set(re.findall(r'\w+', text))
    candidates = [task for task in tasks if (parts := [w for w in re.findall(
        r'\w+', task['name'].casefold()) if len(w) >= 4]) and all(w in words for w in parts)]
    if len(candidates) == 1:
        target = candidates[0]
        for word in re.findall(r'\w+', target['name'].casefold()):
            text = re.sub(r'\b' + re.escape(word) + r'\b', ' ', text)
        return target, text
    return None, text


def _extract_days(text: str) -> int | None:
    """One explicit nonnegative quantity; a week is five working days."""
    if re.search(r'[+−-]\s*\d', text):
        return None
    numbers = '|'.join(sorted(_NUM_WORD, key=len, reverse=True))
    pattern = (r'(?<![\w.,+−-])(?P<number>\d+|' + numbers + r')\s+'
               r'(?:(?:рабочих|рабочие|рабочий)\s+)?'
               r'(?P<unit>дней|день|дня|дн\.?|недели|недель|неделю|неделя)(?!\w)')
    matches = list(re.finditer(pattern, text))
    if len(matches) == 1:
        found = matches[0]
        rest = text[:found.start()] + text[found.end():]
        # Do not silently ignore a second number, range, or compound word-number.
        if re.search(r'\d|\b(?:' + numbers + r')\b|тридцат|сорок|десят|сот|тысяч|миллион|полтора|половин', rest):
            return None
        value = found['number']
        value = int(value) if value.isdigit() else _NUM_WORD[value]
        return value * (5 if found['unit'].startswith('недел') else 1)
    if not matches and re.search(r'\bна\s+(?:неделю|день)\b', text):
        if len(re.findall(r'\b(?:дней|день|дня|неделю|недели|недель)\b', text)) != 1:
            return None
        if re.search(r'\d|\b(?:' + numbers + r')\b', text):
            return None
        return 5 if re.search(r'\bна\s+неделю\b', text) else 1
    return None


def clarify_scenario(message):
    return message, {'type': 'insufficient_data', 'saved': False}


def answer_what_if(question: str, project: dict, analysis: dict) -> tuple[str, dict]:
    """Разбор вопроса «что если…», симуляция на данных системы, ответ."""
    from schedule import simulate, downstream_of, diff_analysis
    from planning_calendar import analyze_project

    q = _what_if_query(question).strip().rstrip("!.")
    ql = q.lower()
    tasks = project["tasks"]
    before = analysis

    if ABSENCE_RE.search(q):
        return unsupported_absence()

    target, action = _scenario_task(tasks, ql)
    if not target:
        return clarify_scenario('Укажите полное название одной задачи и изменение её срока, например: «Тестирование завершится на 3 дня раньше».')
    if target.get('status') == 'done':
        return clarify_scenario('Эта задача уже выполнена. Для проверки изменения срока выберите незавершённую задачу.')
    if re.search(r'\b(?:не|или|либо|от|до|около|примерно)\b', action):
        return clarify_scenario('Уточните один вариант: какая задача завершится раньше или позже и на сколько рабочих дней.')
    later = bool(re.search(r'задерж|позже|дольше|увелич|удлин|затян|больше', action))
    earlier = bool(re.search(r'раньше|быстрее|сократ|сокр[а-яё]*|ускор|меньше', action))
    complete = bool(re.search(r'завершим|закроем|сделаем|выполним|готова|будет выполнена', action))
    if later and earlier:
        return clarify_scenario('В вопросе указаны и ускорение, и задержка. Уточните одно изменение срока задачи.')
    if earlier or later:
        days = _extract_days(action)
        if days is None or not 0 <= days <= 100000:
            return clarify_scenario('Укажите точную величину изменения: целое число рабочих дней или недель, например «Разработка задержится на 3 дня».')
        delta = -days if earlier else days
        duration = int(target['duration'])
        if not 0 <= duration + delta <= 100000:
            return clarify_scenario(f'Длительность задачи сейчас {duration} дн. Укажите изменение, после которого она останется в пределах от 0 до 100000 дней.')
        if delta == 0:
            return 'Изменение на 0 дней сохраняет текущий план. Сценарий не сохранён.', {'type':'unchanged', 'saved':False}
        changes = {target['id']: {'duration': delta}}
        desc = f"длительность {'уменьшится' if earlier else 'увеличится'} на {days} дн."
    elif complete and not re.search(r'\d|дн|день|недел', action):
        changes = {target['id']: {'set_done': True}}
        desc = 'задача будет отмечена выполненной'
    else:
        return clarify_scenario('Уточните действие: задача завершится раньше или позже, и на сколько рабочих дней. Можно также проверить её завершение.')

    sim_tasks = simulate(tasks, changes)
    try:
        after = analyze_project(project, sim_tasks, before.get('calendar', {}).get('today'))
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

    if ABSENCE_RE.search(message):
        return unsupported_absence()

    if WHAT_IF_RE.search(message):
        return answer_what_if(message, project, analysis)

    # Скрытый what-if: «Тестирование задержится на 3 дня» —
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
        cp = analysis["summary"].get("critical_tasks", analysis["summary"]["critical_path"])
        if cp:
            chain = ", ".join(_tname(analysis, c) for c in cp)
            return (f"Критические задачи: {chain}. "
                    "Любая задержка здесь двигает весь проект. Держите их под ежедневным контролем.",
                    {"type": "critical"})
        return "Сейчас нет задач с нулевым резервом — прямых критических угроз нет.", {"type": "critical"}

    if any(w in ml for w in ("угроз", "риск", "проблем")):
        signals = ai_features.radar(analysis)
        return ai_features.radar_text(signals), {'type': 'risk', 'signals': signals}

    if any(w in ml for w in ("привет", "здравств", "помощь", "help", "что ты умеешь")):
        return ("Помогу оценить риски, последствия изменений и подготовить отчёт. Спросите:\n"
                "• «Что будет, если задача X задержится на неделю?»\n"
                "• «Дай отчёт по проекту»\n"
                "• «Какие задачи критичны?» / «Что делать?»\n"
                "Также при каждом изменении задачи я автоматически объясняю последствия.",
                {"type": "help"})

    return ("Могу оценить последствия изменения задачи, показать риски или подготовить отчёт. "
            "Например, спросите: «Что будет, если задача задержится?»",
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
