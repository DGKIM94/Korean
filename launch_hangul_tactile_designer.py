# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import os
import runpy
import sys
import traceback
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

def show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "Hangul Tactile Designer error", 0x10)
    except Exception:
        pass

try:
    runpy.run_path(str(APP_DIR / "hangul_tactile_designer.py"), run_name="__main__")
except SystemExit:
    raise
except BaseException:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"crash_{stamp}.log"
    details = traceback.format_exc()
    log_path.write_text(details, encoding="utf-8")
    show_error(f"프로그램 실행 중 오류가 발생했습니다.\n\n로그: {log_path}")
    raise
