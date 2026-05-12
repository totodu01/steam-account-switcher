# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['steam_switcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('rsc/ico.ico', 'rsc'),   # bundled into _MEIPASS/rsc/ico.ico at runtime
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='steam_switcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='rsc/ico.ico',           # sets the .exe file icon in Explorer
)
