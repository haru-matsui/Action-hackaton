# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('flask')

block_cipher = None

a = Analysis(
    ['backend/app.py'],
    pathex=['backend'],
    binaries=[],
    datas=[
        ('backend/static', 'static'),
        ('backend/data/db.json', 'data'),
    ],
    hiddenimports=hiddenimports + ['assistant', 'ai_features', 'schedule', 'ai_service', 'ai_context'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PM-Radar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
