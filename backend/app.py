"""REST API планировщика проектов на Flask.

Начальные данные лежат в backend/data/db.json, изменяемые — в DATA_DIR.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import BadRequest

import assistant
import ai_features
import ai_service
import sandbox
from ai_context import project_facts, task_facts
from schedule import diff_analysis, downstream_of, simulate
from validation import object_value, list_value, text_value, integer, boolean, dependencies
from planning_calendar import analyze_project, set_dates, calendar_info

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_default_data_root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_default_data_root, "PM-Radar", "data"))
DB_FILE = os.path.join(DATA_DIR, "db.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DEFAULT_DB_FILE = os.path.join(BASE_DIR, "data", "db.json")

app = Flask(__name__, static_folder=STATIC_DIR)
_lock = threading.Lock()
# Short-lived server snapshots: clients can request prose, never supply its facts.
_impact_receipts = OrderedDict()
_receipt_lock = threading.Lock()
IMPACT_TTL = 600
IMPACT_LIMIT = 128


def remember_impact(pid, revision, facts, explanation):
    token = uuid.uuid4().hex
    with _receipt_lock:
        now = time.monotonic()
        for key in list(_impact_receipts):
            if now - _impact_receipts[key]['created'] > IMPACT_TTL:
                del _impact_receipts[key]
        _impact_receipts[token] = dict(pid=pid, revision=revision, facts=facts,
                                       explanation=explanation, created=now)
        while len(_impact_receipts) > IMPACT_LIMIT:
            _impact_receipts.popitem(last=False)
    return token


# --------------------------------------------------------------------------- #
#  Demo-проект (условие кейса: >=8 задач, зависимости, роли, статусы)          #
# --------------------------------------------------------------------------- #

def demo_project() -> dict:
    t = {
        "analysis": {"name": "Анализ требований", "duration": 5, "owner": "Анна Смирнова", "status": "done"},
        "design_ui": {"name": "Дизайн интерфейса", "duration": 6, "owner": "Игорь Петров", "status": "in_progress"},
        "design_db": {"name": "Проектирование БД", "duration": 4, "owner": "Олег Кузнецов", "status": "done"},
        "backend": {"name": "Разработка backend", "duration": 10, "owner": "Олег Кузнецов", "status": "todo"},
        "frontend": {"name": "Разработка frontend", "duration": 8, "owner": "Мария Иванова", "status": "todo"},
        "integration": {"name": "Интеграция модулей", "duration": 3, "owner": "Олег Кузнецов", "status": "todo"},
        "testing": {"name": "Тестирование", "duration": 5, "owner": "Пётр Орлов", "status": "todo"},
        "fixes": {"name": "Исправление дефектов", "duration": 3, "owner": "Мария Иванова", "status": "todo"},
        "docs": {"name": "Документация", "duration": 3, "owner": "Анна Смирнова", "status": "todo"},
        "deploy": {"name": "Деплой и приёмка", "duration": 2, "owner": "Пётр Орлов", "status": "todo"},
    }
    deps = {
        "analysis": [],
        "design_ui": ["analysis"],
        "design_db": ["analysis"],
        "backend": ["design_db", "design_ui"],
        "frontend": ["design_ui"],
        "integration": ["backend", "frontend"],
        "testing": ["integration"],
        "fixes": ["testing"],
        "docs": ["analysis"],
        "deploy": ["fixes", "docs"],
    }
    tasks = [
        {"id": tid, **spec, "dependencies": deps[tid]} for tid, spec in t.items()
    ]
    return {
        "id": "demo-migration",
        "name": "Запуск CRM-платформы",
        "description": "Разработка и запуск CRM-платформы.",
        "deadline": None,
        "start_date": "2026-09-22",
        "deadline_date": "2026-11-03",
        "tasks": tasks,
    }


def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(DEFAULT_DB_FILE):
            try:
                shutil.copy2(DEFAULT_DB_FILE, DB_FILE)
            except OSError:
                pass
        if os.path.exists(DB_FILE):
            with open(DB_FILE, encoding="utf-8") as f:
                return json.load(f)
        db = {"projects": {demo_project()["id"]: demo_project()}}
        save_db(db)
        return db
    with open(DB_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_db(db: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_FILE)


# --------------------------------------------------------------------------- #
#  Валидация и вспомогательные функции                                          #
# --------------------------------------------------------------------------- #

VALID_STATUS = {"todo", "in_progress", "done"}
TASK_FIELDS = {'id', 'name', 'duration', 'start_delay', 'owner', 'status', 'dependencies'}


def read_body(*allowed):
    body = object_value(request.get_json(force=True), 'Запрос', allowed or None)
    if 'base_revision' in body:
        text_value(body['base_revision'], 'Версия проекта', 128, empty=False)
    return body


def days(value, label='Срок', minimum=0):
    return integer(value, label, minimum)


def deadline_value(value):
    return None if value in (None, '') else days(value, 'Дедлайн', 1)


def check_revision(body, project):
    if body.get('base_revision') and body['base_revision'] != sandbox.revision(project):
        return jsonify({'error': 'Проект изменился. Обновите страницу перед сохранением.',
                        'code': 'revision_conflict'}), 409


@app.errorhandler(ValueError)
def invalid_input(error):
    return jsonify({'error': str(error)}), 400


@app.errorhandler(BadRequest)
def invalid_json(error):
    return jsonify({'error': 'Некорректный JSON. Проверьте данные запроса.'}), 400


def norm_tasks(tasks: list[dict]) -> list[dict]:
    out = []
    for t in list_value(tasks, 'Задачи'):
        object_value(t, 'Задача', TASK_FIELDS)
        tid = text_value(t['id'], 'Идентификатор задачи', 128, empty=False) if 'id' in t else uuid.uuid4().hex[:8]
        status = t.get("status", "todo")
        if not isinstance(status, str) or status not in VALID_STATUS:
            raise ValueError('Неизвестный статус задачи.')
        name = text_value(t.get('name', ''), 'Название задачи', empty=False)
        out.append({
            "id": str(tid),
            "name": name,
            "duration": days(t.get("duration", 1), 'Длительность'),
            "start_delay": days(t.get("start_delay", 0), 'Ожидание'),
            "owner": text_value(t.get("owner", ""), 'Ответственный', 120),
            "status": status,
            "dependencies": dependencies(t.get('dependencies', [])),
        })
    ids = {t["id"] for t in out}
    if len(ids) != len(out):
        raise ValueError('Идентификаторы задач не должны повторяться.')
    for t in out:
        if t['id'] in t['dependencies']:
            raise ValueError('Задача не может зависеть от самой себя.')
        if any(d not in ids for d in t['dependencies']):
            raise ValueError('Одна из задач в зависимостях не найдена. Обновите план.')
        t['dependencies'] = list(dict.fromkeys(t['dependencies']))
    return out


def project_payload(project: dict) -> dict:
    """Проект + полный анализ (для основного представления)."""
    analysis = analyze_project(project)
    owners = sorted({t["owner"] for t in project["tasks"] if t["owner"]})
    return {"project": project, "analysis": analysis, "owners": owners,
            "revision": sandbox.revision(project)}


# --------------------------------------------------------------------------- #
#  Маршруты                                                                    #
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get('/api/calendar')
def calendar_settings():
    return jsonify(calendar_info())


@app.get("/api/projects")
def list_projects():
    with _lock:
        db = load_db()
    items = [
        {"id": p["id"], "name": p["name"], "tasks": len(p["tasks"]),
         "deadline": p.get("deadline")}
        for p in db["projects"].values()
    ]
    return jsonify(items)


@app.post("/api/projects")
def create_project():
    body = read_body('name', 'description', 'deadline', 'tasks', 'start_date', 'deadline_date')
    name = text_value(body.get("name", "Новый проект"), 'Название проекта', empty=False)
    deadline = body.get("deadline")
    pid = uuid.uuid4().hex[:8]
    project = {
        "id": pid,
        "name": name,
        "description": text_value(body.get("description", ""), 'Описание', 4000),
        "deadline": deadline_value(deadline),
        "tasks": norm_tasks(body.get("tasks", [])),
    }
    set_dates(project, body)
    payload = project_payload(project)
    with _lock:
        db = load_db()
        db["projects"][pid] = project
        save_db(db)
    return jsonify(payload), 201


@app.get("/api/projects/<pid>")
def get_project(pid: str):
    with _lock:
        db = load_db()
    project = db["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    try:
        return jsonify(project_payload(project))
    except ValueError as e:
        return jsonify({"error": str(e), "project": project}), 409


@app.put("/api/projects/<pid>")
def update_project(pid: str):
    body = read_body('name', 'description', 'deadline', 'tasks', 'base_revision', 'start_date', 'deadline_date')
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
        if not project:
            return jsonify({"error": "Проект не найден"}), 404
        conflict = check_revision(body, project)
        if conflict:
            return conflict
        if "name" in body:
            project["name"] = text_value(body['name'], 'Название проекта', empty=False)
        if "description" in body:
            project["description"] = text_value(body['description'], 'Описание', 4000)
        if "deadline" in body:
            if project.get('start_date'):
                raise ValueError('Для этого проекта укажите календарный дедлайн.')
            d = body["deadline"]
            project["deadline"] = deadline_value(d)
        set_dates(project, body)
        if "tasks" in body:
            project["tasks"] = norm_tasks(body["tasks"])
        try:
            payload = project_payload(project)
        except ValueError as e:
            return jsonify({"error": str(e)}), 409
        db["projects"][pid] = project
        save_db(db)
    return jsonify(payload)


@app.delete("/api/projects/<pid>")
def delete_project(pid: str):
    with _lock:
        db = load_db()
        if pid not in db["projects"]:
            return jsonify({"error": "Проект не найден"}), 404
        del db["projects"][pid]
        save_db(db)
    return jsonify({"ok": True})


@app.post("/api/projects/<pid>/reset-demo")
def reset_demo(pid: str):
    with _lock:
        db = load_db()
        if pid not in db["projects"]:
            return jsonify({"error": "Проект не найден"}), 404
        demo = demo_project()
        demo["id"] = pid
        db["projects"][pid] = demo
        save_db(db)
    return jsonify(project_payload(demo))


@app.post("/api/projects/<pid>/impact")
def impact(pid: str):
    """Главный сценарий: применяет изменение к задаче и возвращает
    «до/после», разницу последствий и текстовое объяснение ассистента.

    Тело: {"task_id": ..., "changes": {...}, "apply": bool}
      changes может содержать: duration (новая длительность),
      duration_delta (+/- дн.), owner, status, dependencies, name.
      apply=true — изменения сохраняются в проекте; иначе это «предпросмотр».
    """
    body = read_body('task_id', 'changes', 'apply', 'tasks', 'base_revision')
    task_id = text_value(body.get('task_id'), 'Задача', 128, empty=False)
    changes = object_value(body.get('changes', {}), 'Изменение задачи', TASK_FIELDS | {'duration_delta'})
    if 'id' in changes and changes['id'] != task_id:
        raise ValueError('Идентификатор изменяемой задачи не совпадает.')
    if 'duration' in changes and 'duration_delta' in changes:
        raise ValueError('Укажите длительность или её изменение, но не оба значения.')
    apply_it = boolean(body.get('apply', False), 'Сохранение')
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
        if not project:
            return jsonify({"error": "Проект не найден"}), 404

    conflict = check_revision(body, project)
    if conflict:
        return conflict
    before = analyze_project(project)
    base_tasks = norm_tasks(body["tasks"]) if 'tasks' in body \
        else project["tasks"]
    sim = [dict(t) for t in base_tasks]
    target = next((t for t in sim if t["id"] == task_id), None)
    if not target:
        return jsonify({"error": "Задача не найдена"}), 404

    if "name" in changes:
        target["name"] = text_value(changes['name'], 'Название задачи', empty=False)
    if "owner" in changes:
        target["owner"] = text_value(changes['owner'], 'Ответственный', 120)
    if "status" in changes:
        status = changes['status']
        if not isinstance(status, str) or status not in VALID_STATUS:
            raise ValueError('Неизвестный статус задачи.')
        target["status"] = status
    if "dependencies" in changes:
        target['dependencies'] = dependencies(changes['dependencies'])
    if "duration" in changes:
        target["duration"] = days(changes["duration"], "Длительность")
    elif "duration_delta" in changes:
        delta = integer(changes['duration_delta'], 'Изменение длительности', -100000)
        target['duration'] = days(target['duration'] + delta, 'Итоговая длительность')
    if "start_delay" in changes:
        target["start_delay"] = days(changes["start_delay"], "Ожидание")

    sim = norm_tasks(sim)
    try:
        after = analyze_project(project, sim, before["calendar"]["today"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    diff = diff_analysis(before, after)
    diff["downstream"] = downstream_of(base_tasks, task_id)
    explanation = assistant.explain_change(before, after, diff, target["name"])
    if apply_it:
        updated = {**project, "tasks": norm_tasks(sim)}
        with _lock:
            db = load_db()
            if sandbox.revision(db['projects'].get(pid)) != sandbox.revision(project):
                return jsonify({'error': 'Проект изменился. Обновите план и повторите изменение.',
                                'code': 'revision_conflict'}), 409
            db["projects"][pid] = updated
            save_db(db)
    result_revision = sandbox.revision(updated if apply_it else project)
    facts = project_facts(project, after, 'impact', before=before,
                          diff=diff, changed_task=target, saved=apply_it)
    explanation_id = remember_impact(pid, result_revision, facts, explanation)

    return jsonify({
        "before": before,
        "after": after,
        "diff": diff,
        "explanation": explanation, "llm": False, "ai": {"source": "pending"},
        "explanation_id": explanation_id, "result_revision": result_revision,
        "applied": apply_it,
    })


@app.post('/api/projects/<pid>/impact/explanation')
def impact_explanation(pid):
    body = read_body('explanation_id')
    token = body.get('explanation_id')
    if not isinstance(token, str) or not token:
        raise ValueError('Укажите результат оценки изменений.')
    with _receipt_lock:
        receipt = _impact_receipts.get(token)
        if not receipt or receipt['pid'] != pid or time.monotonic() - receipt['created'] > IMPACT_TTL:
            return jsonify({'error': 'Оценка устарела. Оцените последствия ещё раз.'}), 410
    with _lock:
        current = load_db()['projects'].get(pid)
    if sandbox.revision(current) != receipt['revision']:
        return jsonify({'error': 'Проект изменился. Оцените последствия ещё раз.',
                        'code': 'revision_conflict'}), 409
    narration = ai_service.generate(receipt['facts'],
        'Объясни последствия изменения и предложи действия.', receipt['explanation'])
    with _lock:
        current = load_db()['projects'].get(pid)
    if sandbox.revision(current) != receipt['revision']:
        return jsonify({'error': 'Проект изменился во время анализа. Обновите план.',
                        'code': 'revision_conflict'}), 409
    return jsonify(explanation=narration['text'], llm=narration['llm'], ai=narration['ai'],
                   explanation_id=token, result_revision=receipt['revision'])


@app.post("/api/projects/<pid>/assistant")
def assistant_chat(pid: str):
    """Контр-фича: чат с ИИ-ассистентом руководителя проектов."""
    body = read_body('message')
    message = text_value(body.get('message', ''), 'Вопрос', 4000, empty=False)
    if not message:
        return jsonify({"error": "Пустой запрос"}), 400
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    try:
        analysis = analyze_project(project)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    answer, facts = assistant.chat(message, project, analysis)
    if facts.get('type') in {'unsupported_scenario', 'insufficient_data', 'unchanged'}:
        return jsonify({'reply': answer, 'facts': facts, 'llm': False})
    narration = ai_service.generate(project_facts(project, analysis, 'chat',
        question_result=facts, calculated_answer=answer), message, answer)
    return jsonify({"reply": narration['text'], "facts": facts,
                    "llm": narration['llm'], "ai": narration['ai']})


@app.post("/api/projects/<pid>/simulate")
def simulate_endpoint(pid: str):
    """What-if без сохранения: {"changes": {task_id: {"duration": +N}}}."""
    body = read_body('changes')
    changes = body.get("changes", {})
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    before = analyze_project(project)
    sim = simulate(project["tasks"], changes)
    try:
        sim = norm_tasks(sim)
        after = analyze_project(project, sim, before["calendar"]["today"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    diff = diff_analysis(before, after)
    base = assistant.explain_change(before, after, diff, "симулируемые задачи")
    narration = ai_service.generate(project_facts(project, after, 'simulation', before=before,
        diff=diff, simulation=changes, saved=False), 'Объясни последствия сценария.', base)
    return jsonify({"after": after, "diff": diff, "explanation": narration['text'],
                    "llm": narration['llm'], "ai": narration['ai']})


# --------------------------------------------------------------------------- #
#  ИИ-фичи: радар рисков / песочница / чек-листы / объяснения / отчёт          #
#   Правило: НИЧЕГО не считаем здесь — только дергаем CPM-движок и просим       #
#   ассистента перевести готовые JSON-факты в человеческий текст.               #
# --------------------------------------------------------------------------- #

@app.get('/api/ai/status')
def ai_status():
    return jsonify(ai_service.status())


@app.get("/api/projects/<pid>/radar")
def radar_endpoint(pid: str):
    """Проактивный «Радар рисков»: фронт опрашивает его при каждой загрузке
    и после изменений. Ассистент сам находит проблемы и предлагает решения."""
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    analysis = analyze_project(project)
    signals = ai_features.radar(analysis)
    narration = ai_service.generate(project_facts(project, analysis, 'radar'),
        'Кратко предупреди о самых важных рисках и предложи действия.', ai_features.radar_text(signals))
    return jsonify({"signals": signals, **narration})


@app.post("/api/projects/<pid>/sandbox")
def sandbox_endpoint(pid: str):
    """Calculate first; interpret the same revision only after the user pauses."""
    body = read_body('shifts', 'task_id', 'shift_days', 'base_revision', 'explain')
    explain = boolean(body.get('explain', True), 'Пояснение')
    if 'shifts' in body and ('task_id' in body or 'shift_days' in body):
        raise ValueError('Укажите один формат сценария.')
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    if body.get('base_revision') and body['base_revision'] != sandbox.revision(project):
        return jsonify({'error': 'Проект изменился. Обновите план перед новым сценарием.',
                        'code': 'revision_conflict'}), 409
    shifts = body['shifts'] if 'shifts' in body else {
        text_value(body.get('task_id'), 'Задача', 128, empty=False): body.get('shift_days', 0)}
    try:
        result = sandbox.calculate(project, shifts)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    text = sandbox.describe(result)
    # Preserve the original single-task API while the UI uses a whole scenario.
    if len(result['changes']) == 1:
        result['fact'] = result['changes'][0]
    if not explain or not result['shifts']:
        return jsonify({**result, 'explanation': text, 'llm': False,
                        'ai': {'source': 'pending' if result['shifts'] else 'unchanged'}})
    narration = ai_service.generate(project_facts(project, result['after'], 'sandbox',
        changes=result['changes'], before_summary=result['before']['summary'],
        diff=result['diff'], saved=False),
        'Объясни весь сценарий: какие задачи сдвинутся, как изменится прогноз и что можно сделать. '
        'Длительности и согласованный дедлайн не менялись.', text)
    with _lock:
        current = load_db()['projects'].get(pid)
    if sandbox.revision(current) != result['base_revision']:
        return jsonify({'error': 'Проект изменился во время анализа. Обновите план.',
                        'code': 'revision_conflict'}), 409
    return jsonify({**result, 'explanation': narration['text'],
                    'llm': narration['llm'], 'ai': narration['ai']})


@app.post('/api/projects/<pid>/sandbox/apply')
def apply_sandbox(pid: str):
    body = read_body('shifts', 'base_revision', 'scenario_key')
    if not body.get('base_revision') or not body.get('scenario_key'):
        return jsonify({'error': 'Сначала рассчитайте сценарий.'}), 400
    text_value(body['scenario_key'], 'Сценарий', 128, empty=False)
    with _lock:
        db = load_db()
        project = db['projects'].get(pid)
        if not project:
            return jsonify({'error': 'Проект не найден'}), 404
        if body['base_revision'] != sandbox.revision(project):
            return jsonify({'error': 'Проект изменился. Сценарий не сохранён. Обновите план.',
                            'code': 'revision_conflict'}), 409
        try:
            result = sandbox.calculate(project, body.get('shifts'))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        if body['scenario_key'] != result['scenario_key'] or not result['shifts']:
            return jsonify({'error': 'Сценарий изменился. Сначала рассчитайте его заново.'}), 409
        updated = {**project, 'tasks': simulate(project['tasks'],
                   {key: {'start_delay': value} for key, value in result['shifts'].items()})}
        db['projects'][pid] = updated
        save_db(db)
    return jsonify({**project_payload(updated), 'applied': True, 'diff': result['diff']})


@app.post("/api/projects/<pid>/checklist")
def checklist_endpoint(pid: str):
    """Генерация чек-листа подзадач для (новой или существующей) сложной задачи."""
    body = read_body(*TASK_FIELDS, 'task_id')
    name = text_value(body.get('name', ''), 'Название задачи')
    duration = days(body.get("duration", 5), "Длительность")
    owner = text_value(body.get('owner', ''), 'Ответственный', 120)
    deps = dependencies(body.get('dependencies', []))
    task_id = body.get("task_id")
    if 'task_id' in body:
        text_value(task_id, 'Задача', 128, empty=False)
    if 'id' in body:
        text_value(body['id'], 'Идентификатор задачи', 128, empty=False)
    if 'start_delay' in body:
        days(body['start_delay'], 'Ожидание')
    if 'status' in body and (not isinstance(body['status'], str) or body['status'] not in VALID_STATUS):
        raise ValueError('Неизвестный статус задачи.')
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    if any(dep not in {t['id'] for t in project['tasks']} for dep in deps):
        raise ValueError('Одна из задач в зависимостях не найдена.')
    if task_id:
        t = next((x for x in project["tasks"] if x["id"] == task_id), None)
        if not t:
            return jsonify({"error": "Задача не найдена"}), 404
        name, duration = t["name"], int(t.get("duration", duration))
        owner, deps = t.get("owner", ""), t.get("dependencies", [])
    if not name:
        return jsonify({"error": "Укажите название задачи"}), 400
    sug = ai_features.suggest_checklist(name, duration, deps, owner)
    narration = ai_service.generate({'task_name': name, 'mode': 'checklist_names',
        'proposal_only': True}, 'Предложи от 2 до 6 коротких названий подзадач для этой работы.',
        ai_features.checklist_text(sug), names=True)
    if narration['llm']:
        names = narration['subtask_names']
        total = max(0, duration)
        count = len(names)
        sug['subtasks'] = [{'name': title, 'duration': total // count + (i < total % count),
            'owner': owner, 'dependencies': deps if i == 0 else []} for i, title in enumerate(names)]
        sug['checklist_total_duration'] = total
        sug['note'] = 'Проверьте предложенные подзадачи и их длительность перед добавлением.'
    return jsonify({"suggestion": sug, "text": ai_features.checklist_text(sug),
                    "llm": narration['llm'], "ai": narration['ai']})


@app.post("/api/projects/<pid>/apply-checklist")
def apply_checklist_endpoint(pid: str):
    """Кнопка «Согласен»: подзадачи добавляются в проект одной операцией."""
    body = read_body('subtasks', 'base_revision')
    subs = list_value(body.get('subtasks', []), 'Подзадачи')
    if not subs:
        return jsonify({"error": "Нет подзадач для добавления"}), 400
    for sub in subs:
        object_value(sub, 'Подзадача', TASK_FIELDS)
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
        if not project:
            return jsonify({"error": "Проект не найден"}), 404
        conflict = check_revision(body, project)
        if conflict:
            return conflict
        new_tasks = project["tasks"] + [dict(s) for s in subs]
        project["tasks"] = norm_tasks(new_tasks)
        payload = project_payload(project)
        db["projects"][pid] = project
        save_db(db)
    return jsonify(payload)


@app.get("/api/projects/<pid>/explain/<task_id>")
def explain_endpoint(pid: str, task_id: str):
    """«Объясни простыми словами»: клик по проблемной задаче — ИИ рассказывает
    цепочку причинности. Все даты/резервы берёт движок, ИИ только переводит."""
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    analysis = analyze_project(project)
    if not any(t['id'] == task_id for t in analysis['tasks']):
        return jsonify({'error': 'Задача не найдена'}), 404
    text = ai_features.explain_task_simple(task_id, analysis)
    narration = ai_service.generate(project_facts(project, analysis, 'explain',
        **task_facts(analysis, task_id)), 'Объясни выбранную задачу простыми словами.', text)
    return jsonify({"explanation": narration['text'], "llm": narration['llm'], "ai": narration['ai']})


@app.get("/api/projects/<pid>/report.md")
def report_md_endpoint(pid: str):
    """Автоматический отчёт для заказчика/руководства: связный текст из сухих
    данных базы. Скачивается как .md — PM делает это часами, продукт — секундой."""
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    analysis = analyze_project(project)
    base_text = assistant.report(project, analysis)
    narration = ai_service.generate(project_facts(project, analysis, 'report'),
        'Сформируй краткий отчёт для руководства.', base_text)
    return app.response_class(narration['text'], mimetype="text/markdown; charset=utf-8",
                              headers={"Content-Disposition":
                                       f"attachment; filename=report-{pid}.md",
                                       'X-AI-Source': narration['ai']['source'],
                                       'X-AI-Model': narration['ai']['model'],
                                       'X-AI-Reason': narration['ai'].get('reason', '')})


# Статика фронтенда (single-page app) ---------------------------------------- #

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Не найдено"}), 404
    return send_from_directory(STATIC_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, threaded=True)
