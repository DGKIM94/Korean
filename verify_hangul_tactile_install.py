# -*- coding: utf-8 -*-
from __future__ import annotations
import importlib
import platform
import struct
import sys
from pathlib import Path

required = [
    "PySide6", "serial", "openpyxl", "numpy", "scipy", "sounddevice",
    "webrtcvad", "python_speech_features", "faster_whisper", "sklearn",
    "joblib", "pandas",
]
failed = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed.append(f"{name}: {exc}")

print(f"Python: {platform.python_version()} ({struct.calcsize('P') * 8}-bit)")
print(f"Executable: {sys.executable}")
print(f"Project: {Path(__file__).resolve().parent}")
if failed:
    print("FAILED IMPORTS:")
    for item in failed:
        print(" -", item)
    raise SystemExit(1)
print("All required packages imported successfully.")
