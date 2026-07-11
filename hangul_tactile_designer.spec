# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
datas = [
    ('hangul_voice_backend.py', '.'),
    ('hangul_tactile_default_setup.json', '.'),
    ('korean2_no_relay_dual_device_18ch_softpwm.ino', '.'),
]
binaries = []
hiddenimports = []

# The voice backend is loaded dynamically, so explicitly collect its packages.
for package in [
    'faster_whisper', 'ctranslate2', 'av', 'sounddevice', 'webrtcvad',
    'python_speech_features', 'sklearn', 'scipy', 'numpy', 'joblib',
    'pandas', 'openpyxl', 'serial'
]:
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        hiddenimports += collect_submodules(package)

a = Analysis(
    ['hangul_tactile_designer.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HangulTactileDesigner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HangulTactileDesigner',
)
