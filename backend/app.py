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

from flask import Flask, jsonify, request, send_from_directory

import assistant
import ai_features
import ai_service
from ai_context import project_facts, task_facts
from schedule import analyze, diff_analysis, downstream_of, simulate

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_default_data_root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_default_data_root, "PM-Radar", "data"))
DB_FILE = os.path.join(DATA_DIR, "db.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DEFAULT_DB_FILE = os.path.join(BASE_DIR, "data", "db.json")

app = Flask(__name__, static_folder=STATIC_DIR)
_lock = threading.Lock()


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
        "description": "Демонстрационный проект: разработка и вывод в продакшн CRM-платформы.",
        "deadline": 30,  # рабочих дней от старта
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


def norm_tasks(tasks: list[dict]) -> list[dict]:
    out = []
    for t in tasks:
        tid = t.get("id") or uuid.uuid4().hex[:8]
        status = t.get("status", "todo")
        if status not in VALID_STATUS:
            status = "todo"
        out.append({
            "id": str(tid),
            "name": str(t.get("name", "Без названия")).strip() or "Без названия",
            "duration": max(0, int(t.get("duration", 1))),
            "start_delay": max(0, int(t.get("start_delay", 0))),
            "owner": str(t.get("owner", "")).strip(),
            "status": status,
            "dependencies": [str(d) for d in t.get("dependencies", [])],
        })
    ids = {t["id"] for t in out}
    for t in out:
        t["dependencies"] = [d for d in t["dependencies"] if d in ids and d != t["id"]]
    return out


def project_payload(project: dict) -> dict:
    """Проект + полный анализ (для основного представления)."""
    analysis = analyze(project["tasks"], project.get("deadline"))
    owners = sorted({t["owner"] for t in project["tasks"] if t["owner"]})
    return {"project": project, "analysis": analysis, "owners": owners}


# --------------------------------------------------------------------------- #
#  Маршруты                                                                    #
# --------------------------------------------------------------------------- #

@app.get("/api/health")
def health():
    return jsonify({"ok": True})


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
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip() or "Новый проект"
    deadline = body.get("deadline")
    pid = uuid.uuid4().hex[:8]
    project = {
        "id": pid,
        "name": name,
        "description": str(body.get("description", "")),
        "deadline": int(deadline) if deadline not in (None, "", 0) else None,
        "tasks": norm_tasks(body.get("tasks", [])),
    }
    with _lock:
        db = load_db()
        db["projects"][pid] = project
        save_db(db)
    return jsonify(project_payload(project)), 201


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
    body = request.get_json(force=True) or {}
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
        if not project:
            return jsonify({"error": "Проект не найден"}), 404
        if "name" in body:
            project["name"] = str(body["name"]).strip() or project["name"]
        if "description" in body:
            project["description"] = str(body["description"])
        if "deadline" in body:
            d = body["deadline"]
            project["deadline"] = int(d) if d not in (None, "", 0) else None
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
    body = request.get_json(force=True) or {}
    task_id = str(body.get("task_id", ""))
    changes = body.get("changes", {})
    apply_it = bool(body.get("apply", False))
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
        if not project:
            return jsonify({"error": "Проект не найден"}), 404

    before = analyze(project["tasks"], project.get("deadline"))
    base_tasks = norm_tasks(body["tasks"]) if isinstance(body.get("tasks"), list) \
        else project["tasks"]
    sim = [dict(t) for t in base_tasks]
    target = next((t for t in sim if t["id"] == task_id), None)
    if not target:
        return jsonify({"error": "Задача не найдена"}), 404

    if "name" in changes:
        target["name"] = str(changes["name"]).strip() or target["name"]
    if "owner" in changes:
        target["owner"] = str(changes["owner"]).strip()
    if "status" in changes and changes["status"] in VALID_STATUS:
        target["status"] = changes["status"]
    if "dependencies" in changes:
        target["dependencies"] = [str(d) for d in changes["dependencies"]]
    if "duration" in changes:
        target["duration"] = max(0, int(changes["duration"]))
    elif "duration_delta" in changes:
        target["duration"] = max(0, int(target["duration"]) + int(changes["duration_delta"]))
    if "start_delay" in changes:
        target["start_delay"] = max(0, int(changes["start_delay"]))

    try:
        after = analyze(sim, project.get("deadline"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    diff = diff_analysis(before, after)
    diff["downstream"] = downstream_of(base_tasks, task_id)
    explanation = assistant.explain_change(before, after, diff, target["name"])
    narration = ai_service.generate(project_facts(project, after, 'impact', before=before,
        diff=diff, changed_task=target, saved=apply_it),
        'Объясни последствия изменения и предложи действия.', explanation)

    if apply_it:
        updated = {**project, "tasks": norm_tasks(sim)}
        with _lock:
            db = load_db()
            db["projects"][pid] = updated
            save_db(db)
        after = analyze(updated["tasks"], updated.get("deadline"))

    return jsonify({
        "before": before,
        "after": after,
        "diff": diff,
        "explanation": narration['text'], "llm": narration['llm'], "ai": narration['ai'],
        "applied": apply_it,
    })


@app.post("/api/projects/<pid>/assistant")
def assistant_chat(pid: str):
    """Контр-фича: чат с ИИ-ассистентом руководителя проектов."""
    body = request.get_json(force=True) or {}
    message = str(body.get("message", "")).strip()
    if not message:
        return jsonify({"error": "Пустой запрос"}), 400
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    try:
        analysis = analyze(project["tasks"], project.get("deadline"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 409

    answer, facts = assistant.chat(message, project, analysis)
    narration = ai_service.generate(project_facts(project, analysis, 'chat',
        question_result=facts, calculated_answer=answer), message, answer)
    return jsonify({"reply": narration['text'], "facts": facts,
                    "llm": narration['llm'], "ai": narration['ai']})


@app.post("/api/projects/<pid>/simulate")
def simulate_endpoint(pid: str):
    """What-if без сохранения: {"changes": {task_id: {"duration": +N}}}."""
    body = request.get_json(force=True) or {}
    changes = body.get("changes", {})
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    before = analyze(project["tasks"], project.get("deadline"))
    sim = simulate(project["tasks"], changes)
    try:
        after = analyze(sim, project.get("deadline"))
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
    analysis = analyze(project["tasks"], project.get("deadline"))
    signals = ai_features.radar(analysis)
    narration = ai_service.generate(project_facts(project, analysis, 'radar'),
        'Кратко предупреди о самых важных рисках и предложи действия.', ai_features.radar_text(signals))
    return jsonify({"signals": signals, **narration})


@app.post("/api/projects/<pid>/sandbox")
def sandbox_endpoint(pid: str):
    """Режим «Песочница»: пользователь перетащил задачу на timeline, ничего не
    сохраняя. Считаем последствия виртуального сдвига и отдаём сухой JSON-факт:
    {"task","shift","affected","deadline_shift","risk"} + текстовое объяснение."""
    body = request.get_json(force=True) or {}
    task_id = str(body.get("task_id", ""))
    shift = int(body.get("shift_days", 0))
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
    if not any(t["id"] == task_id for t in project["tasks"]):
        return jsonify({"error": "Задача не найдена"}), 404
    before = analyze(project["tasks"], project.get("deadline"))
    original = next(t for t in project['tasks'] if t['id'] == task_id)
    if original['status'] == 'done':
        return jsonify({'error': 'Выполненную задачу нельзя сдвигать в песочнице'}), 400
    if int(original.get('start_delay', 0)) + shift < 0:
        return jsonify({'error': 'Задача не может стартовать раньше завершения предшественников'}), 400
    sim = simulate(project["tasks"], {task_id: {"start_delay": shift}})
    after = analyze(sim, project.get("deadline"))
    diff = diff_analysis(before, after)
    fact = ai_features.sandbox_json(before, after, diff, task_id, shift)
    text = _sandbox_text(fact)
    if body.get('explain') is False:
        return jsonify({'fact': fact, 'explanation': text, 'llm': False,
            'ai': {'source': 'pending'}, 'after_summary': after['summary']})
    narration = ai_service.generate(project_facts(project, after, 'sandbox', fact=fact,
        before_summary=before['summary'], diff=diff, saved=False),
        'Объясни последствия сдвига начала задачи. Длительность не менялась.', text)
    return jsonify({"fact": fact, "explanation": narration['text'],
                    "llm": narration['llm'], "ai": narration['ai'],
                    "after_summary": after["summary"]})


def _sandbox_text(f: dict) -> str:
    """Интерпретация JSON-факта песочницы (цифры — из движка, не отсюда)."""
    if f["shift"] > 0:
        head = f"Ты сдвинул «{f['task']}» на {_days_ru(f['shift'])}."
    elif f["shift"] < 0:
        head = f"Ты вернул «{f['task']}» на {_days_ru(-f['shift'])} назад."
    else:
        head = f"«{f['task']}» вернулась на исходную позицию."
    lines = [head]
    if f["affected"]:
        lines.append("Сдвинутся последующие задачи: " + ", ".join(f"«{n}»" for n in f["affected"]) + ".")
    if f["now_at_risk"]:
        lines.append("Новые задачи под угрозой: " + ", ".join(f"«{n}»" for n in f["now_at_risk"]) + ".")
    if f["duration_delta"] > 0:
        lines.append(f"Общий срок проекта сдвинется на {_days_ru(f['duration_delta'])}.")
    elif f["duration_delta"] < 0:
        lines.append(f"Общий срок проекта сократится на {_days_ru(-f['duration_delta'])}.")
    else:
        lines.append("Общий срок проекта не изменится — сдвиг закрылся резервом.")
    if f["deadline_breached"]:
        lines.append(f"⚠ Дедлайн нарушен на {_days_ru(f['delay_vs_deadline'])}.")
    lines.append(f"Риск срыва сдачи проекта — {f['risk']}.")
    return "\n".join(lines)


def _days_ru(n: int) -> str:
    return ai_features._days(n)


@app.post("/api/projects/<pid>/checklist")
def checklist_endpoint(pid: str):
    """Генерация чек-листа подзадач для (новой или существующей) сложной задачи."""
    body = request.get_json(force=True) or {}
    name = str(body.get("name", "")).strip()
    duration = max(0, int(body.get("duration", 5)))
    owner = str(body.get("owner", ""))
    deps = [str(d) for d in body.get("dependencies", [])]
    task_id = body.get("task_id")
    with _lock:
        project = load_db()["projects"].get(pid)
    if not project:
        return jsonify({"error": "Проект не найден"}), 404
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
        sug['note'] = 'Черновик DeepSeek: названия предложены ИИ; дни распределены Python. Проверьте перед применением.'
    return jsonify({"suggestion": sug, "text": ai_features.checklist_text(sug),
                    "llm": narration['llm'], "ai": narration['ai']})


@app.post("/api/projects/<pid>/apply-checklist")
def apply_checklist_endpoint(pid: str):
    """Кнопка «Согласен»: подзадачи добавляются в проект одной операцией."""
    body = request.get_json(force=True) or {}
    subs = body.get("subtasks", [])
    if not isinstance(subs, list) or not subs:
        return jsonify({"error": "Нет подзадач для добавления"}), 400
    with _lock:
        db = load_db()
        project = db["projects"].get(pid)
        if not project:
            return jsonify({"error": "Проект не найден"}), 404
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
    analysis = analyze(project["tasks"], project.get("deadline"))
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
    analysis = analyze(project["tasks"], project.get("deadline"))
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
