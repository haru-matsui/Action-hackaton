"""Single-file Windows launcher for the local PM Radar web application."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import webbrowser

import tkinter as tk
from tkinter import messagebox, simpledialog
from werkzeug.serving import make_server

import ai_service
from app import app


def local_server():
    requested = os.environ.get('PORT')
    ports = [int(requested)] if requested else [*range(5000, 5010), 0]
    for port in ports:
        try:
            return make_server('127.0.0.1', port, app, threaded=True)
        except (OSError, SystemExit):
            if port == ports[-1]:
                raise RuntimeError('Не удалось запустить локальный сервер.') from None
    raise RuntimeError('Не удалось запустить локальный сервер.')


def save_ai_key(key: str) -> None:
    path = ai_service.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding='utf-8-sig'))
            if isinstance(current, dict):
                values = {k: current[k] for k in ('model', 'base_url') if k in current}
        except (OSError, ValueError):
            pass
    values['api_key'] = key
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def run() -> None:
    server = local_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'

    window = tk.Tk()
    window.title('PM Radar')
    window.geometry('400x184')
    window.resizable(False, False)
    window.configure(bg='#f6f7fb')

    title = tk.Label(window, text='PM Radar', font=('Segoe UI', 17, 'bold'),
                     fg='#24283a', bg='#f6f7fb')
    title.pack(pady=(18, 2))
    tk.Label(window, text='Проект запущен на этом компьютере',
             font=('Segoe UI', 10), fg='#697185', bg='#f6f7fb').pack()

    ai_state = tk.StringVar(value='Ключ ИИ задан' if ai_service.llm_available()
                            else 'ИИ: ключ не задан')
    tk.Label(window, textvariable=ai_state, font=('Segoe UI', 9),
             fg='#775ec9', bg='#f6f7fb').pack(pady=(7, 12))

    actions = tk.Frame(window, bg='#f6f7fb')
    actions.pack()

    tk.Button(actions, text='Открыть проект', command=lambda: webbrowser.open(url),
              bg='#725bd8', fg='white', activebackground='#624ac5',
              activeforeground='white', relief='flat', font=('Segoe UI', 9, 'bold'),
              padx=10, pady=5, cursor='hand2').pack(side='left', padx=4)

    def configure_ai():
        key = simpledialog.askstring('OpenRouter', 'Введите ключ OpenRouter:',
                                     show='*', parent=window)
        if key is None:
            return
        key = key.strip()
        if not key:
            messagebox.showerror('PM Radar', 'Ключ не может быть пустым.', parent=window)
            return
        try:
            save_ai_key(key)
        except OSError as error:
            messagebox.showerror('PM Radar', f'Не удалось сохранить ключ: {error}',
                                 parent=window)
            return
        ai_state.set('Ключ ИИ задан')
        messagebox.showinfo('PM Radar', 'Ключ сохранён только на этом компьютере.',
                            parent=window)

    tk.Button(actions, text='Подключить ИИ', command=configure_ai,
              bg='#ffffff', fg='#594b90', relief='solid', borderwidth=1,
              font=('Segoe UI', 9), padx=9, pady=5, cursor='hand2').pack(side='left', padx=4)

    def close():
        window.destroy()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    window.protocol('WM_DELETE_WINDOW', close)
    if os.environ.get('PM_RADAR_TEST_MODE') == '1':
        window.withdraw()
    else:
        window.after(350, lambda: webbrowser.open(url))
    window.mainloop()


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        fallback = tk.Tk()
        fallback.withdraw()
        messagebox.showerror('PM Radar', f'Не удалось запустить приложение:\n{error}',
                             parent=fallback)
        fallback.destroy()
