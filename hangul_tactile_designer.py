# -*- coding: utf-8 -*-
"""
Hangul Tactile Designer
==========================
A highly configurable Hangul tactile-code designer and tester.

Core functions
- Map each consonant/vowel to an atomic tactile stimulus, a composite of other
  jamo, or a raw serial script.
- Configure duration-dependent CV/CVC onset-to-onset SOA and motion-length SOA.
- Configure syllable and word boundaries as end-to-start ISI.
- Preserve the current Arduino dot syntax and raw /i, /d motion commands.
- Save/load a complete setup as JSON.
- Type a Hangul string such as "각" and immediately feel the compiled stimulus.
- Run voice-response quizzes using the legacy v20 voice backend and a syllable
  XLSX file.
- Light Apple-inspired PySide6 UI with rounded frosted cards, gray controls, and clear selection states.

Hardware defaults for the current dual-arm rig
- LEFT arm  = device 2 = '#'
- RIGHT arm = device 1 = '@'
- Logical UI positions 1..9 are mapped to physical motors:
    1->3, 2->2, 3->1, 4->6, 5->5, 6->4, 7->9, 8->8, 9->7
- Serial baud: 115200

The app can run in DRY RUN mode without Arduino connection.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from PySide6.QtCore import Qt, QTimer, QSize
    from PySide6.QtGui import QColor, QFont, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGraphicsDropShadowEffect,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:  # pragma: no cover
    print("PySide6가 필요합니다.  python -m pip install PySide6", file=sys.stderr)
    raise

try:
    import serial  # type: ignore
    import serial.tools.list_ports  # type: ignore
except Exception:
    serial = None

try:
    from openpyxl import load_workbook
except Exception:
    load_workbook = None

APP_VERSION = "Hangul Tactile Designer portable v8"
# APP_DIR is always the user-visible program folder. RESOURCE_DIR is where
# bundled read-only files live when built with PyInstaller.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR
DATA_DIR = APP_DIR / "hangul_designer_results"
SETUP_DIR = APP_DIR / "hangul_tactile_setups"
DATA_DIR.mkdir(exist_ok=True)
SETUP_DIR.mkdir(exist_ok=True)

UI_ASSET_DIR = APP_DIR / "hangul_ui_assets"
UI_ASSET_DIR.mkdir(exist_ok=True)

def _write_ui_asset(name: str, content: str) -> Path:
    path = UI_ASSET_DIR / name
    try:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    except Exception:
        pass
    return path

ARROW_UP_SVG = _write_ui_asset(
    "chevron_up.svg",
    """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 20 20'>
    <path d='M4.5 12.25L10 6.75l5.5 5.5' fill='none' stroke='#6E6E73' stroke-width='2.15' stroke-linecap='round' stroke-linejoin='round'/>
    </svg>""",
)
ARROW_DOWN_SVG = _write_ui_asset(
    "chevron_down.svg",
    """<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 20 20'>
    <path d='M4.5 7.75L10 13.25l5.5-5.5' fill='none' stroke='#6E6E73' stroke-width='2.15' stroke-linecap='round' stroke-linejoin='round'/>
    </svg>""",
)
TOGGLE_ON_SVG = _write_ui_asset(
    "toggle_on.svg",
    """<svg xmlns='http://www.w3.org/2000/svg' width='56' height='34' viewBox='0 0 56 34'>
    <rect x='1' y='1' width='54' height='32' rx='16' fill='#34C759'/>
    <circle cx='39' cy='17' r='13' fill='#FFFFFF'/>
    <circle cx='39' cy='17' r='12.2' fill='#FFFFFF' stroke='#E5E5EA' stroke-width='.7'/>
    </svg>""",
)
TOGGLE_OFF_SVG = _write_ui_asset(
    "toggle_off.svg",
    """<svg xmlns='http://www.w3.org/2000/svg' width='56' height='34' viewBox='0 0 56 34'>
    <rect x='1' y='1' width='54' height='32' rx='16' fill='#E5E5EA'/>
    <circle cx='17' cy='17' r='13' fill='#FFFFFF'/>
    <circle cx='17' cy='17' r='12.2' fill='#FFFFFF' stroke='#D1D1D6' stroke-width='.7'/>
    </svg>""",
)

CONSONANTS = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
VOWELS = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
COMPOUND_FINALS: Dict[str, List[str]] = {
    "ㄳ": ["ㄱ", "ㅅ"], "ㄵ": ["ㄴ", "ㅈ"], "ㄶ": ["ㄴ", "ㅎ"],
    "ㄺ": ["ㄹ", "ㄱ"], "ㄻ": ["ㄹ", "ㅁ"], "ㄼ": ["ㄹ", "ㅂ"],
    "ㄽ": ["ㄹ", "ㅅ"], "ㄾ": ["ㄹ", "ㅌ"], "ㄿ": ["ㄹ", "ㅍ"],
    "ㅀ": ["ㄹ", "ㅎ"], "ㅄ": ["ㅂ", "ㅅ"],
}

CHOSUNG = CONSONANTS
JUNGSUNG = VOWELS
JONGSUNG = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")

TEMPORAL_PRESETS = {
    "S200": {"label": "짧음 · 200 ms", "on1_ms": 200, "gap_ms": 0, "on2_ms": 0},
    "L400": {"label": "김 · 400 ms", "on1_ms": 400, "gap_ms": 0, "on2_ms": 0},
    "R200_100_200": {"label": "연속 · 200–100–200", "on1_ms": 200, "gap_ms": 100, "on2_ms": 200},
    "CUSTOM": {"label": "사용자 설정", "on1_ms": 200, "gap_ms": 100, "on2_ms": 200},
}

DEFAULT_LOGICAL_TO_MOTOR = {
    "1": 3, "2": 2, "3": 1,
    "4": 6, "5": 5, "6": 4,
    "7": 9, "8": 8, "9": 7,
}

# ----------------------------- data model -----------------------------

# Matrix classes. Motion is split automatically using its actual compiled
# duration so a short and a long motion can use different SOA values.
TIMING_CLASS_LABELS: Dict[str, str] = {
    "short": "짧음",
    "long": "김",
    "repeat": "연속/반복",
    "motion_short": "짧은 모션",
    "motion_long": "긴 모션",
    "composite": "Composite",
    "custom": "사용자/기타",
}

# The mapping editor also offers a generic motion override. Its short/long
# matrix class is still selected automatically from the compiled duration.
TIMING_CLASS_EDITOR_LABELS: Dict[str, str] = {
    "short": "짧음",
    "long": "김",
    "repeat": "연속/반복",
    "motion": "모션 · 길이 자동",
    "motion_short": "짧은 모션 · 고정",
    "motion_long": "긴 모션 · 고정",
    "composite": "Composite",
    "custom": "사용자/기타",
}

TIMING_CONTEXT_LABELS: Dict[str, str] = {
    "composite": "Composite 내부",
    "cv": "CV · 자음→모음",
    "cvc_cv": "CVC · 첫 자음→모음",
    "cvc_vc": "CVC · 모음→끝 자음",
    "compound_final": "복합 종성 내부",
}

BOUNDARY_ISI_DEFAULTS_MS: Dict[str, int] = {
    "inter_syllable": 350,
    "inter_word": 650,
}

# Used only to create sensible defaults and migrate the previous ISI-based setup.
# The actual duration is always calculated from the designed command/timeline.
NOMINAL_TIMING_CLASS_DURATION_MS: Dict[str, int] = {
    "short": 200,
    "long": 400,
    "repeat": 500,
    "motion": 400,          # legacy alias
    "motion_short": 300,
    "motion_long": 550,
    "composite": 500,
    "custom": 300,
}

LEGACY_ISI_DEFAULTS_MS: Dict[str, int] = {
    "composite": 150,
    "cv": 250,
    "cvc_cv": 250,
    "cvc_vc": 250,
    "compound_final": 150,
}


def _default_timing_defaults_ms() -> Dict[str, int]:
    # Defaults are SOA: previous onset -> next onset.
    return {
        ctx: NOMINAL_TIMING_CLASS_DURATION_MS["short"] + isi
        for ctx, isi in LEGACY_ISI_DEFAULTS_MS.items()
    }


def _deep_copy_timing_matrix(src: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, int]]]:
    out: Dict[str, Dict[str, Dict[str, int]]] = {}
    for ctx, rows in (src or {}).items():
        if not isinstance(rows, dict):
            continue
        out[str(ctx)] = {}
        for prev_cls, cols in rows.items():
            if not isinstance(cols, dict):
                continue
            out[str(ctx)][str(prev_cls)] = {
                str(next_cls): int(value) for next_cls, value in cols.items()
            }
    return out


def _expand_motion_duration_matrix(
    src: Dict[str, Dict[str, Dict[str, int]]],
    defaults: Dict[str, int],
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Upgrade the old single `motion` row/column to short/long motion.

    Old setup files remain usable: both new motion classes inherit the old
    motion cell until the user changes them in the advanced SOA dialog.
    """
    copied = _deep_copy_timing_matrix(src)
    out: Dict[str, Dict[str, Dict[str, int]]] = {}
    for context in TIMING_CONTEXT_LABELS:
        old_rows = copied.get(context, {})
        default = int(defaults.get(context, 0))
        rows: Dict[str, Dict[str, int]] = {}
        for prev_cls in TIMING_CLASS_LABELS:
            prev_candidates = [prev_cls]
            if prev_cls in ("motion_short", "motion_long"):
                prev_candidates.append("motion")
            source_cols: Dict[str, int] = {}
            for candidate in prev_candidates:
                if isinstance(old_rows.get(candidate), dict):
                    source_cols = old_rows[candidate]
                    break
            cols: Dict[str, int] = {}
            for next_cls in TIMING_CLASS_LABELS:
                next_candidates = [next_cls]
                if next_cls in ("motion_short", "motion_long"):
                    next_candidates.append("motion")
                value = None
                for candidate in next_candidates:
                    if candidate in source_cols:
                        value = int(source_cols[candidate])
                        break
                cols[next_cls] = default if value is None else value
            rows[prev_cls] = cols
        out[context] = rows
    return out


@dataclass
class JamoSpec:
    mode: str = "atomic"  # atomic | composite | raw | unmapped
    arm: str = "left"
    position: int = 1
    temporal: str = "S200"
    on1_ms: int = 200
    gap_ms: int = 100
    on2_ms: int = 200
    steps: List[Dict[str, Any]] = field(default_factory=list)
    raw_command: str = ""
    note: str = ""
    # auto | short | long | repeat | motion | composite | custom
    timing_class: str = "auto"


@dataclass
class DesignSetup:
    setup_name: str = "Default Hangul Design"
    setup_version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    baudrate: int = 115200
    left_marker: str = "#"
    right_marker: str = "@"
    logical_to_motor: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LOGICAL_TO_MOTOR))

    # Retained only so old setup JSON files can be opened safely. In timing
    # semantics v4 these fields are compatibility mirrors; the dedicated SOA
    # and boundary-ISI fields below are authoritative.
    default_composite_gap_ms: int = 150
    cv_gap_ms: int = 250
    cvc_cv_gap_ms: int = 250
    cvc_vc_gap_ms: int = 250
    compound_final_gap_ms: int = 150
    inter_syllable_gap_ms: int = 350
    inter_word_gap_ms: int = 650

    # v4: boundary timing is true end-to-start ISI.
    inter_syllable_isi_ms: int = 350
    inter_word_isi_ms: int = 650

    # v4: ordinary consonants branch at 300 ms by default. The threshold is
    # editable in the advanced SOA dialog. Raw motion stimuli have a separate
    # duration threshold and use short-motion / long-motion matrix rows.
    cv_duration_split_ms: int = 300
    motion_duration_split_ms: int = 300
    cv_short_soa_ms: int = 450
    cv_long_soa_ms: int = 700
    cvc_cv_short_soa_ms: int = 450
    cvc_cv_long_soa_ms: int = 700
    use_duration_based_cv_soa: bool = True

    timing_semantics_version: int = 4
    timing_defaults_ms: Dict[str, int] = field(default_factory=_default_timing_defaults_ms)
    timing_matrix_ms: Dict[str, Dict[str, Dict[str, int]]] = field(default_factory=dict)
    timing_pair_overrides_ms: Dict[str, int] = field(default_factory=dict)
    jamo: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["updated_at"] = datetime.now().isoformat(timespec="seconds")
        # Mirror SOA defaults into the legacy-named fields so the JSON remains
        # understandable to a human. timing_semantics_version=4 is authoritative.
        out["default_composite_gap_ms"] = int(self.timing_defaults_ms.get("composite", 0))
        out["cv_gap_ms"] = int(self.timing_defaults_ms.get("cv", 0))
        out["cvc_cv_gap_ms"] = int(self.timing_defaults_ms.get("cvc_cv", 0))
        out["cvc_vc_gap_ms"] = int(self.timing_defaults_ms.get("cvc_vc", 0))
        out["compound_final_gap_ms"] = int(self.timing_defaults_ms.get("compound_final", 0))
        # Legacy field names are retained for older tools, but in v4 they
        # mirror the true boundary ISI values.
        out["inter_syllable_gap_ms"] = int(self.inter_syllable_isi_ms)
        out["inter_word_gap_ms"] = int(self.inter_word_isi_ms)
        # Remove obsolete v2 boundary-SOA entries so a saved v4 JSON has only
        # one unambiguous representation of syllable/word boundary timing.
        out["timing_defaults_ms"] = {
            k: int(v) for k, v in self.timing_defaults_ms.items()
            if k in TIMING_CONTEXT_LABELS
        }
        out["timing_matrix_ms"] = {
            k: v for k, v in out.get("timing_matrix_ms", {}).items()
            if k in TIMING_CONTEXT_LABELS
        }
        out["timing_pair_overrides_ms"] = {
            k: int(v) for k, v in out.get("timing_pair_overrides_ms", {}).items()
            if k.split("|", 1)[0] in TIMING_CONTEXT_LABELS
        }
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DesignSetup":
        original = dict(data or {})
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in original.items() if k in allowed}
        obj = cls(**clean)
        obj.logical_to_motor = {str(k): int(v) for k, v in obj.logical_to_motor.items()}
        obj.timing_defaults_ms = {
            **_default_timing_defaults_ms(),
            **{str(k): int(v) for k, v in (obj.timing_defaults_ms or {}).items()},
        }
        obj.timing_matrix_ms = _deep_copy_timing_matrix(obj.timing_matrix_ms)
        obj.timing_pair_overrides_ms = {
            str(k): int(v) for k, v in (obj.timing_pair_overrides_ms or {}).items()
        }

        previous_version = int(original.get("timing_semantics_version", 1) or 1)
        if previous_version < 2:
            obj._migrate_legacy_isi_to_soa(original)
        else:
            obj._normalize_composite_step_keys()

        # v1 stored boundary values as ISI. v2 stored them as SOA measured from
        # the previous last-jamo onset, so subtract the old nominal 200 ms jamo
        # duration to recover the prior physical gap as closely as possible.
        if "inter_syllable_isi_ms" not in original:
            if previous_version < 2:
                obj.inter_syllable_isi_ms = max(0, int(original.get("inter_syllable_gap_ms", 350)))
            else:
                old_soa = int((original.get("timing_defaults_ms") or {}).get(
                    "inter_syllable", original.get("inter_syllable_gap_ms", 550)
                ))
                obj.inter_syllable_isi_ms = max(0, old_soa - NOMINAL_TIMING_CLASS_DURATION_MS["short"])
        if "inter_word_isi_ms" not in original:
            if previous_version < 2:
                obj.inter_word_isi_ms = max(0, int(original.get("inter_word_gap_ms", 650)))
            else:
                old_soa = int((original.get("timing_defaults_ms") or {}).get(
                    "inter_word", original.get("inter_word_gap_ms", 850)
                ))
                obj.inter_word_isi_ms = max(0, old_soa - NOMINAL_TIMING_CLASS_DURATION_MS["short"])

        # Existing v1/v2 setups had one CV SOA. Keep their behavior unchanged
        # until the user explicitly gives short/long consonants different values.
        if "cv_short_soa_ms" not in original:
            obj.cv_short_soa_ms = int(obj.timing_defaults_ms.get("cv", 450))
        if "cv_long_soa_ms" not in original:
            obj.cv_long_soa_ms = int(obj.cv_short_soa_ms)
        if "cvc_cv_short_soa_ms" not in original:
            obj.cvc_cv_short_soa_ms = int(obj.timing_defaults_ms.get("cvc_cv", 450))
        if "cvc_cv_long_soa_ms" not in original:
            obj.cvc_cv_long_soa_ms = int(obj.cvc_cv_short_soa_ms)

        # v4 uses dedicated ISI fields for text boundaries; remove stale v2
        # boundary entries after they have been migrated.
        obj.timing_defaults_ms = {
            k: int(v) for k, v in obj.timing_defaults_ms.items()
            if k in TIMING_CONTEXT_LABELS
        }
        obj.timing_matrix_ms = {
            k: v for k, v in obj.timing_matrix_ms.items()
            if k in TIMING_CONTEXT_LABELS
        }
        obj.timing_pair_overrides_ms = {
            k: int(v) for k, v in obj.timing_pair_overrides_ms.items()
            if k.split("|", 1)[0] in TIMING_CONTEXT_LABELS
        }
        obj.timing_matrix_ms = _expand_motion_duration_matrix(
            obj.timing_matrix_ms, obj.timing_defaults_ms
        )
        obj.timing_semantics_version = 4
        return obj

    def _normalize_composite_step_keys(self) -> None:
        for raw_spec in self.jamo.values():
            if not isinstance(raw_spec, dict):
                continue
            steps = raw_spec.get("steps") or []
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                if "soa_before_ms" not in step:
                    step["soa_before_ms"] = int(step.get("gap_before_ms", 0 if index == 0 else self.timing_defaults_ms["composite"]))
                step.pop("gap_before_ms", None)

    def _migrate_legacy_isi_to_soa(self, original: Dict[str, Any]) -> None:
        legacy = {
            "composite": int(original.get("default_composite_gap_ms", 150)),
            "cv": int(original.get("cv_gap_ms", 250)),
            "cvc_cv": int(original.get("cvc_cv_gap_ms", 250)),
            "cvc_vc": int(original.get("cvc_vc_gap_ms", 250)),
            "compound_final": int(original.get("compound_final_gap_ms", 150)),
        }
        self.inter_syllable_isi_ms = max(0, int(original.get("inter_syllable_gap_ms", 350)))
        self.inter_word_isi_ms = max(0, int(original.get("inter_word_gap_ms", 650)))
        self.timing_defaults_ms = {
            ctx: NOMINAL_TIMING_CLASS_DURATION_MS["short"] + isi
            for ctx, isi in legacy.items()
        }
        self.timing_matrix_ms = {}
        for ctx, isi in legacy.items():
            self.timing_matrix_ms[ctx] = {}
            for prev_cls in TIMING_CLASS_LABELS:
                soa = NOMINAL_TIMING_CLASS_DURATION_MS.get(prev_cls, 300) + isi
                self.timing_matrix_ms[ctx][prev_cls] = {
                    next_cls: int(soa) for next_cls in TIMING_CLASS_LABELS
                }

        # Previous composite rows stored an ISI after the previous referenced
        # jamo. Convert it to an approximate onset-to-onset value using the
        # previous jamo's timing class. This keeps old setups close to their old
        # physical timing while switching them to SOA semantics.
        for raw_spec in self.jamo.values():
            if not isinstance(raw_spec, dict):
                continue
            steps = raw_spec.get("steps") or []
            previous_ref = ""
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                ref = str(step.get("ref", ""))
                if index == 0:
                    step["soa_before_ms"] = 0
                else:
                    old_isi = int(step.get("gap_before_ms", legacy["composite"]))
                    prev_cls = self.timing_class_for(previous_ref)
                    step["soa_before_ms"] = NOMINAL_TIMING_CLASS_DURATION_MS.get(prev_cls, 300) + old_isi
                step.pop("gap_before_ms", None)
                previous_ref = ref

    def seed_timing_matrix_from_legacy_isi(self, legacy: Optional[Dict[str, int]] = None) -> None:
        legacy = dict(legacy or LEGACY_ISI_DEFAULTS_MS)
        self.timing_defaults_ms = {
            ctx: NOMINAL_TIMING_CLASS_DURATION_MS["short"] + int(legacy.get(ctx, 0))
            for ctx in TIMING_CONTEXT_LABELS
        }
        self.timing_matrix_ms = {}
        for ctx in TIMING_CONTEXT_LABELS:
            isi = int(legacy.get(ctx, 0))
            self.timing_matrix_ms[ctx] = {}
            for prev_cls in TIMING_CLASS_LABELS:
                soa = NOMINAL_TIMING_CLASS_DURATION_MS.get(prev_cls, 300) + isi
                self.timing_matrix_ms[ctx][prev_cls] = {
                    next_cls: int(soa) for next_cls in TIMING_CLASS_LABELS
                }

    def get_spec(self, label: str) -> JamoSpec:
        raw = self.jamo.get(label, {"mode": "unmapped"})
        allowed = {f.name for f in JamoSpec.__dataclass_fields__.values()}
        return JamoSpec(**{k: v for k, v in raw.items() if k in allowed})

    def set_spec(self, label: str, spec: JamoSpec) -> None:
        self.jamo[label] = asdict(spec)

    def marker_for_arm(self, arm: str) -> str:
        return self.left_marker if arm == "left" else self.right_marker

    def motor_for_position(self, position: int) -> int:
        return int(self.logical_to_motor.get(str(int(position)), int(position)))

    def timing_class_for(self, label: str, stack: Optional[List[str]] = None) -> str:
        stack = list(stack or [])
        if label in stack:
            return "composite"
        if label in COMPOUND_FINALS and label not in self.jamo:
            return "composite"
        spec = self.get_spec(label)
        if spec.timing_class in TIMING_CLASS_EDITOR_LABELS:
            return spec.timing_class
        if spec.mode == "composite":
            return "composite"
        if spec.mode == "raw":
            raw = spec.raw_command.lower()
            if "/i" in raw or "/d" in raw or "," in raw:
                return "motion"
            return "custom"
        if spec.mode == "atomic":
            if spec.temporal == "S200":
                return "short"
            if spec.temporal == "L400":
                return "long"
            if spec.temporal == "R200_100_200":
                return "repeat"
            if int(spec.on2_ms) > 0:
                return "repeat"
            return "short" if int(spec.on1_ms) <= 300 else "long"
        return "custom"

    def refined_timing_class(self, timing_class: str, duration_ms: Optional[int]) -> str:
        if timing_class == "motion":
            duration = int(duration_ms or 0)
            return (
                "motion_short"
                if duration <= int(self.motion_duration_split_ms)
                else "motion_long"
            )
        return timing_class if timing_class in TIMING_CLASS_LABELS else "custom"

    @staticmethod
    def pair_override_key(context: str, from_label: str, to_label: str) -> str:
        return f"{context}|{from_label}|{to_label}"

    def resolve_soa_ms(
        self,
        context: str,
        from_label: str,
        to_label: str,
        from_duration_ms: Optional[int] = None,
        to_duration_ms: Optional[int] = None,
    ) -> int:
        # A specific jamo pair always wins.
        pair_key = self.pair_override_key(context, from_label, to_label)
        if pair_key in self.timing_pair_overrides_ms:
            return max(0, int(self.timing_pair_overrides_ms[pair_key]))

        prev_base = self.timing_class_for(from_label)
        next_base = self.timing_class_for(to_label)
        prev_cls = self.refined_timing_class(prev_base, from_duration_ms)
        next_cls = self.refined_timing_class(next_base, to_duration_ms)

        # Ordinary consonants use the dedicated actual-duration CV rule. A raw
        # motion consonant instead uses the short/long motion rows in the
        # advanced matrix, so motion length can have its own SOA.
        if (
            self.use_duration_based_cv_soa
            and from_duration_ms is not None
            and prev_base not in ("motion", "motion_short", "motion_long")
        ):
            is_short = int(from_duration_ms) <= int(self.cv_duration_split_ms)
            if context == "cv":
                return max(0, int(self.cv_short_soa_ms if is_short else self.cv_long_soa_ms))
            if context == "cvc_cv":
                return max(0, int(self.cvc_cv_short_soa_ms if is_short else self.cvc_cv_long_soa_ms))

        try:
            return max(0, int(self.timing_matrix_ms[context][prev_cls][next_cls]))
        except Exception:
            return max(0, int(self.timing_defaults_ms.get(context, 0)))

    def stable_hash(self) -> str:
        blob = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:16]


class CompileError(RuntimeError):
    pass


@dataclass
class TimelineEvent:
    onset_ms: int
    command: str
    duration_ms: int
    label: str = ""

    @property
    def end_ms(self) -> int:
        return int(self.onset_ms) + int(self.duration_ms)


class HangulCompiler:
    """Compile Hangul into a tactile timeline for the current Arduino code.

    Raw ``/i`` and ``/d`` motion commands are preserved. The current Arduino
    dot syntax can represent sequential steps and equal-onset simultaneous
    steps, but not a new staggered onset before a prior step has ended. Such an
    unsupported overlap is reported instead of silently converting ramps to
    fixed PWM values.
    """

    def __init__(self, setup: DesignSetup):
        self.setup = setup

    @staticmethod
    def join(parts: Sequence[str]) -> str:
        return ".".join(p.strip(".") for p in parts if str(p).strip("."))

    @staticmethod
    def _step_duration_ms(step: str) -> int:
        step = re.sub(r"\^(\d+)\s*$", "", str(step).strip())
        durations = [int(x) for x in re.findall(r"/(\d+)", step)]
        low = step.lower()
        if re.search(r"/[s](?:@|#|$)", low):
            durations.append(200)
        if re.search(r"/[l](?:@|#|$)", low):
            durations.append(400)
        if re.search(r"/[r](?:@|#|$)", low):
            durations.append(500)
        return max(durations) if durations else 0

    @staticmethod
    def _shift(events: Sequence[TimelineEvent], offset_ms: int) -> List[TimelineEvent]:
        return [
            TimelineEvent(int(e.onset_ms) + int(offset_ms), e.command, e.duration_ms, e.label)
            for e in events
        ]

    @staticmethod
    def timeline_duration_ms(events: Sequence[TimelineEvent]) -> int:
        return max((e.end_ms for e in events), default=0)

    def atomic_timeline(self, spec: JamoSpec, label: str = "") -> List[TimelineEvent]:
        marker = self.setup.marker_for_arm(spec.arm)
        motor = self.setup.motor_for_position(spec.position)
        preset = TEMPORAL_PRESETS.get(spec.temporal, TEMPORAL_PRESETS["CUSTOM"])
        if spec.temporal == "CUSTOM":
            on1, gap_ms, on2 = int(spec.on1_ms), int(spec.gap_ms), int(spec.on2_ms)
        else:
            on1, gap_ms, on2 = int(preset["on1_ms"]), int(preset["gap_ms"]), int(preset["on2_ms"])
        if on1 <= 0:
            raise CompileError("첫 번째 ON duration은 1 ms 이상이어야 합니다.")
        events = [TimelineEvent(0, f"{marker}{motor}/{on1}", on1, label)]
        if on2 > 0:
            onset2 = on1 + max(0, gap_ms)
            events.append(TimelineEvent(onset2, f"{marker}{motor}/{on2}", on2, label))
        return events

    def _raw_timeline(self, command: str, label: str = "") -> List[TimelineEvent]:
        command = str(command).strip().strip(".")
        if not command:
            raise CompileError(f"{label} raw command가 비어 있습니다.")
        events: List[TimelineEvent] = []
        current_onset = 0
        current_marker = ""
        for original_step in command.split("."):
            step = original_step.strip()
            if not step:
                continue
            explicit_advance: Optional[int] = None
            m = re.search(r"\^(\d+)\s*$", step)
            if m:
                raise CompileError(
                    "현재 Arduino 코드는 ^N onset 문법을 지원하지 않습니다. "
                    "Raw command에서 ^N을 제거하세요."
                )
            if re.fullmatch(r"0/(\d+)", step):
                rest_ms = int(step.split("/", 1)[1])
                current_onset += explicit_advance if explicit_advance is not None else rest_ms
                continue
            if step.startswith(("@", "#")):
                markers = re.findall(r"[@#]", step)
                if markers:
                    current_marker = markers[-1]
                normalized = step
            else:
                if not current_marker:
                    raise CompileError("Raw script는 @ 또는 # marker로 시작해야 합니다.")
                normalized = current_marker + step
            duration = self._step_duration_ms(normalized)
            events.append(TimelineEvent(current_onset, normalized, duration, label))
            current_onset += explicit_advance if explicit_advance is not None else duration
        return events

    def compile_jamo_timeline(self, label: str, stack: Optional[List[str]] = None) -> List[TimelineEvent]:
        stack = list(stack or [])
        if label in stack:
            raise CompileError("순환 참조: " + " → ".join(stack + [label]))
        if label in COMPOUND_FINALS and label not in self.setup.jamo:
            events: List[TimelineEvent] = []
            onset = 0
            previous = ""
            previous_duration: Optional[int] = None
            for index, comp in enumerate(COMPOUND_FINALS[label]):
                comp_events = self.compile_jamo_timeline(comp, stack + [label])
                comp_duration = self.timeline_duration_ms(comp_events)
                if index > 0:
                    onset += self.setup.resolve_soa_ms(
                        "compound_final", previous, comp,
                        from_duration_ms=previous_duration,
                        to_duration_ms=comp_duration,
                    )
                events.extend(self._shift(comp_events, onset))
                previous = comp
                previous_duration = comp_duration
            return events

        spec = self.setup.get_spec(label)
        if spec.mode == "unmapped":
            raise CompileError(f"{label} 매핑이 없습니다.")
        if spec.mode == "atomic":
            return self.atomic_timeline(spec, label)
        if spec.mode == "raw":
            return self._raw_timeline(spec.raw_command, label)
        if spec.mode == "composite":
            if not spec.steps:
                raise CompileError(f"{label} composite step이 없습니다.")
            events: List[TimelineEvent] = []
            onset = 0
            previous_ref = ""
            previous_duration: Optional[int] = None
            for index, step in enumerate(spec.steps):
                ref = str(step.get("ref", "")).strip()
                if not ref:
                    raise CompileError(f"{label}의 {index + 1}번째 구성 자모가 비어 있습니다.")
                ref_events = self.compile_jamo_timeline(ref, stack + [label])
                ref_duration = self.timeline_duration_ms(ref_events)
                if index > 0:
                    if "soa_before_ms" in step:
                        soa = int(step.get("soa_before_ms", 0))
                    elif "gap_before_ms" in step:  # last-resort compatibility
                        soa = int(step.get("gap_before_ms", 0))
                    else:
                        soa = self.setup.resolve_soa_ms(
                            "composite", previous_ref, ref,
                            from_duration_ms=previous_duration,
                            to_duration_ms=ref_duration,
                        )
                    onset += max(0, soa)
                events.extend(self._shift(ref_events, onset))
                previous_ref = ref
                previous_duration = ref_duration
            return events
        raise CompileError(f"지원하지 않는 mode: {spec.mode}")

    def compile_syllable_timeline(self, ch: str) -> Tuple[List[TimelineEvent], str, str, int]:
        dec = self.decompose_syllable(ch)
        if dec is None:
            if ch in self.setup.jamo or ch in COMPOUND_FINALS:
                return self.compile_jamo_timeline(ch), ch, ch, 0
            raise CompileError(f"지원하지 않는 문자: {ch}")
        cho, jung, jong = dec
        cho_events = self.compile_jamo_timeline(cho)
        jung_events = self.compile_jamo_timeline(jung)
        cho_duration = self.timeline_duration_ms(cho_events)
        jung_duration = self.timeline_duration_ms(jung_events)
        jung_onset = self.setup.resolve_soa_ms(
            "cvc_cv" if jong else "cv", cho, jung,
            from_duration_ms=cho_duration,
            to_duration_ms=jung_duration,
        )
        events = list(cho_events)
        events.extend(self._shift(jung_events, jung_onset))
        last_label = jung
        last_jamo_onset = jung_onset
        if jong:
            jong_events = self.compile_jamo_timeline(jong)
            jong_duration = self.timeline_duration_ms(jong_events)
            jong_onset = jung_onset + self.setup.resolve_soa_ms(
                "cvc_vc", jung, jong,
                from_duration_ms=jung_duration,
                to_duration_ms=jong_duration,
            )
            events.extend(self._shift(jong_events, jong_onset))
            last_label = jong
            last_jamo_onset = jong_onset
        return events, cho, last_label, int(last_jamo_onset)

    @staticmethod
    def decompose_syllable(ch: str) -> Optional[Tuple[str, str, str]]:
        if not ch:
            return None
        code = ord(ch[0])
        if not (0xAC00 <= code <= 0xD7A3):
            return None
        sidx = code - 0xAC00
        return CHOSUNG[sidx // 588], JUNGSUNG[(sidx % 588) // 28], JONGSUNG[sidx % 28]

    @staticmethod
    def serialize_timeline(events: Sequence[TimelineEvent]) -> str:
        """Serialize using the user's unchanged Arduino dot-step syntax.

        Raw ramp tokens remain intact, for example::

            #5/150.#5/d,4/i/100.#4/150

        Empty onset gaps are emitted as ``0/N``. Equal-onset events are joined
        into one step. A staggered overlap cannot be expressed by the current
        firmware without rewriting a ramp, so it raises a clear error instead.
        """
        clean = [e for e in events if int(e.duration_ms) > 0 and str(e.command).strip()]
        if not clean:
            return ""

        grouped: Dict[int, List[TimelineEvent]] = {}
        for event in clean:
            grouped.setdefault(int(event.onset_ms), []).append(event)

        parts: List[str] = []
        cursor = 0
        for onset in sorted(grouped):
            if onset < cursor:
                overlap = cursor - onset
                raise CompileError(
                    f"현재 Arduino 문법으로는 {overlap} ms 겹침 SOA를 /i·/d 원형 그대로 "
                    "전송할 수 없습니다. 해당 SOA를 앞 자극 duration 이상으로 설정하세요."
                )
            if onset > cursor:
                parts.append(f"0/{onset - cursor}")
            group = grouped[onset]
            commands = [str(e.command).strip().strip(".") for e in group if str(e.command).strip(".")]
            if commands:
                parts.append("".join(commands))
            cursor = max(int(e.end_ms) for e in group)
        return ".".join(parts)

    def compile_jamo(self, label: str, stack: Optional[List[str]] = None) -> str:
        return self.serialize_timeline(self.compile_jamo_timeline(label, stack))

    def compile_syllable(self, ch: str) -> str:
        events, _first, _last, _last_onset = self.compile_syllable_timeline(ch)
        return self.serialize_timeline(events)

    def compile_text(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        text = str(text)
        events: List[TimelineEvent] = []
        trace: List[Dict[str, Any]] = []
        previous_char_start = 0
        previous_end_ms = 0
        previous_last_label = ""
        have_previous = False
        pending_word_boundary = False

        for ch in text:
            if ch.isspace():
                if have_previous:
                    pending_word_boundary = True
                continue

            syllable_events, first_label, last_label, last_jamo_onset = self.compile_syllable_timeline(ch)
            if not have_previous:
                char_start = 0
            else:
                boundary_isi = (
                    self.setup.inter_word_isi_ms
                    if pending_word_boundary
                    else self.setup.inter_syllable_isi_ms
                )
                # Boundary timing is true ISI: wait after the complete previous
                # syllable has physically ended, then start the next syllable.
                char_start = int(previous_end_ms) + max(0, int(boundary_isi))
            shifted = self._shift(syllable_events, char_start)
            events.extend(shifted)
            relative_command = self.serialize_timeline(syllable_events)
            trace.append({
                "char": ch,
                "command": relative_command,
                "onset_ms": int(char_start),
                "first_label": first_label,
                "last_label": last_label,
            })
            previous_char_start = char_start
            previous_end_ms = max((e.end_ms for e in shifted), default=char_start)
            previous_last_label = last_label
            have_previous = True
            pending_word_boundary = False

        if not trace:
            raise CompileError("입력된 한글이 없습니다.")
        return self.serialize_timeline(events), trace

    @staticmethod
    def estimate_duration_ms(command: str) -> int:
        current_onset = 0
        final_end = 0
        for original_step in str(command).split("."):
            step = original_step.strip()
            if not step:
                continue
            explicit_advance: Optional[int] = None
            m = re.search(r"\^(\d+)\s*$", step)
            if m:
                explicit_advance = int(m.group(1))
                step = step[:m.start()].strip()
            if re.fullmatch(r"0/(\d+)", step):
                duration = int(step.split("/", 1)[1])
                current_onset += explicit_advance if explicit_advance is not None else duration
                final_end = max(final_end, current_onset)
                continue
            duration = HangulCompiler._step_duration_ms(step)
            final_end = max(final_end, current_onset + duration)
            current_onset += explicit_advance if explicit_advance is not None else duration
        return int(final_end)


# ----------------------------- default setup -----------------------------

def atomic(arm: str, pos: int, temporal: str, note: str = "") -> Dict[str, Any]:
    return asdict(JamoSpec(mode="atomic", arm=arm, position=pos, temporal=temporal, note=note))


def composite(refs: Sequence[str], gap: int = 150, note: str = "") -> Dict[str, Any]:
    """Create a composite using the previous API's ISI argument.

    The default setup is migrated to SOA immediately after all jamo mappings are
    created, so this helper stays compatible with older setup construction code.
    """
    steps = []
    for i, ref in enumerate(refs):
        steps.append({"ref": ref, "legacy_isi_ms": 0 if i == 0 else int(gap)})
    return asdict(JamoSpec(mode="composite", steps=steps, note=note))


def raw(command: str, note: str = "") -> Dict[str, Any]:
    return asdict(JamoSpec(mode="raw", raw_command=command, note=note))


def make_default_setup() -> DesignSetup:
    s = DesignSetup()
    # Preserve the earlier tactile-Hangul design using the current logical UI layout.
    s.jamo.update({
        "ㄱ": atomic("left", 1, "S200", "기본 ㄱ"),
        "ㄴ": atomic("left", 2, "S200", "기본 ㄴ"),
        "ㄷ": atomic("left", 3, "S200", "기본 ㄷ"),
        "ㅂ": atomic("left", 4, "S200", "기본 ㅂ"),
        "ㅅ": atomic("left", 6, "S200", "기본 ㅅ"),
        "ㅇ": atomic("left", 7, "S200", "기본 ㅇ"),
        "ㅈ": atomic("left", 9, "S200", "기본 ㅈ"),
        "ㅋ": atomic("left", 1, "L400", "ㄱ 위치 긴 자극"),
        "ㄹ": atomic("left", 2, "L400", "ㄴ 위치 긴 자극"),
        "ㅌ": atomic("left", 3, "L400", "ㄷ 위치 긴 자극"),
        "ㅍ": atomic("left", 4, "L400", "ㅂ 위치 긴 자극"),
        "ㅎ": atomic("left", 6, "L400", "ㅅ 위치 긴 자극"),
        "ㅁ": atomic("left", 7, "L400", "ㅇ 위치 긴 자극"),
        "ㅊ": atomic("left", 9, "L400", "ㅈ 위치 긴 자극"),
        "ㄲ": composite(["ㄱ", "ㄱ"], 150, "ㄱ 반복"),
        "ㄸ": composite(["ㄷ", "ㄷ"], 150, "ㄷ 반복"),
        "ㅃ": composite(["ㅂ", "ㅂ"], 150, "ㅂ 반복"),
        "ㅆ": composite(["ㅅ", "ㅅ"], 150, "ㅅ 반복"),
        "ㅉ": composite(["ㅈ", "ㅈ"], 150, "ㅈ 반복"),
        "ㅣ": atomic("left", 5, "S200", "중앙 짧은 자극"),
        "ㅡ": atomic("left", 5, "L400", "중앙 긴 자극"),
        # The old four directional vowels are retained as raw motion scripts.
        "ㅏ": raw("#5/150.#5/d,4/i/100.#4/150", "중앙→motor4 motion"),
        "ㅓ": raw("#5/150.#5/d,6/i/100.#6/150", "중앙→motor6 motion"),
        "ㅗ": raw("#5/150.#5/d,2/i/100.#2/150", "중앙→motor2 motion"),
        "ㅜ": raw("#5/150.#5/d,8/i/100.#8/150", "중앙→motor8 motion"),
        "ㅢ": composite(["ㅡ", "ㅣ"], 150, "ㅡ + ㅣ"),
        "ㅑ": composite(["ㅏ", "ㅏ"], 150),
        "ㅕ": composite(["ㅓ", "ㅓ"], 150),
        "ㅛ": composite(["ㅗ", "ㅗ"], 150),
        "ㅠ": composite(["ㅜ", "ㅜ"], 150),
        "ㅐ": composite(["ㅏ", "ㅣ"], 150),
        "ㅔ": composite(["ㅓ", "ㅣ"], 150),
        "ㅒ": composite(["ㅑ", "ㅣ"], 150),
        "ㅖ": composite(["ㅕ", "ㅣ"], 150),
        "ㅘ": composite(["ㅗ", "ㅏ"], 150),
        "ㅙ": composite(["ㅗ", "ㅏ", "ㅣ"], 150),
        "ㅚ": composite(["ㅗ", "ㅣ"], 150),
        "ㅝ": composite(["ㅜ", "ㅓ"], 150),
        "ㅞ": composite(["ㅜ", "ㅓ", "ㅣ"], 150),
        "ㅟ": composite(["ㅜ", "ㅣ"], 150),
    })

    # Start from the old physical timing, but express it as onset-to-onset SOA.
    # A short 200 ms stimulus followed by the old 150 ms ISI therefore becomes
    # a 350 ms SOA. Long/repeat/motion classes receive their own values.
    s.timing_defaults_ms = _default_timing_defaults_ms()
    s.timing_matrix_ms = {}
    for raw_spec in s.jamo.values():
        if not isinstance(raw_spec, dict) or raw_spec.get("mode") != "composite":
            continue
        previous_ref = ""
        for index, step in enumerate(raw_spec.get("steps") or []):
            ref = str(step.get("ref", ""))
            if index == 0:
                step["soa_before_ms"] = 0
                step.pop("legacy_isi_ms", None)
            else:
                legacy_isi = int(step.pop("legacy_isi_ms", LEGACY_ISI_DEFAULTS_MS["composite"]))
                prev_cls = s.timing_class_for(previous_ref)
                step["soa_before_ms"] = NOMINAL_TIMING_CLASS_DURATION_MS.get(prev_cls, 300) + legacy_isi
            step.pop("gap_before_ms", None)
            previous_ref = ref
    return s


# ----------------------------- serial -----------------------------

class SerialController:
    def __init__(self) -> None:
        self.port = None
        self.port_name = ""
        self.last_ack = ""

    def is_connected(self) -> bool:
        return bool(self.port and self.port.is_open)

    def list_ports(self) -> List[Tuple[str, str]]:
        if serial is None:
            return []
        return [(p.device, p.description) for p in serial.tools.list_ports.comports()]

    def connect(self, port_name: str, baudrate: int) -> None:
        if serial is None:
            raise RuntimeError("pyserial이 설치되지 않았습니다.")
        self.close()
        self.port = serial.Serial(port_name, int(baudrate), timeout=0.15, write_timeout=1.0)
        self.port_name = port_name
        time.sleep(1.5)
        self.port.reset_input_buffer()

    def close(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.port_name = ""

    def send(self, command: str, wait_ack: bool = True, timeout_sec: float = 2.0) -> str:
        command = command.strip()
        if not command:
            raise RuntimeError("빈 serial command입니다.")
        if not self.is_connected():
            self.last_ack = "DRY RUN"
            print("[DRY SERIAL]", command)
            return self.last_ack
        self.port.reset_input_buffer()
        self.port.write((command + "\n").encode("utf-8"))
        self.port.flush()
        if not wait_ack:
            return "SENT"
        deadline = time.perf_counter() + timeout_sec
        lines: List[str] = []
        while time.perf_counter() < deadline:
            raw = self.port.readline()
            if not raw:
                QApplication.processEvents()
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                lines.append(line)
            if line == "OK":
                self.last_ack = "OK"
                return "OK"
            if line.startswith("ERR"):
                self.last_ack = line
                raise RuntimeError(line)
        self.last_ack = "TIMEOUT: " + " | ".join(lines)
        raise RuntimeError(self.last_ack)

    def emergency_off(self) -> None:
        try:
            self.send("@0#0", wait_ack=False)
        except Exception:
            pass


# ----------------------------- utilities -----------------------------

def add_shadow(widget: QWidget, blur: int = 34, y: int = 9, alpha: int = 24) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    add_shadow(f)
    return f


def button(text: str, kind: str = "secondary") -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setCursor(Qt.PointingHandCursor)
    return b


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        child = item.layout()
        if child is not None:
            clear_layout(child)


def load_syllables(path: Path, limit: int = 200) -> List[str]:
    if load_workbook is None:
        raise RuntimeError("openpyxl이 필요합니다.")
    if not path.exists():
        raise RuntimeError(f"syllable 파일이 없습니다: {path}")
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    first = next(rows, None)
    if first is None:
        return []
    header = [str(v).strip().lower() if v is not None else "" for v in first]
    has_header = any(h in header for h in ("syl", "syll", "syllable", "count"))
    if has_header:
        if "syl" in header:
            idx = header.index("syl")
        elif "syll" in header:
            idx = header.index("syll")
        elif "syllable" in header:
            idx = header.index("syllable")
        else:
            idx = 0
        all_rows = rows
    else:
        idx = 0
        all_rows = iter([first] + list(rows))
    labels: List[str] = []
    for row in all_rows:
        if row and len(row) > idx and row[idx] is not None:
            txt = str(row[idx]).strip()
            if txt:
                labels.append(txt[0])
        if len(labels) >= int(limit):
            break
    return list(dict.fromkeys(labels))


# ----------------------------- editor widgets -----------------------------

class PositionGrid(QWidget):
    def __init__(self, on_change=None):
        super().__init__()
        self.on_change = on_change
        self.value = 1
        self.buttons: Dict[int, QPushButton] = {}
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        n = 1
        for r in range(3):
            for c in range(3):
                b = QPushButton(str(n))
                b.setObjectName("PositionButton")
                b.setCheckable(True)
                b.setMinimumSize(72, 62)
                b.clicked.connect(lambda _=False, v=n: self.set_value(v))
                self.buttons[n] = b
                lay.addWidget(b, r, c)
                n += 1
        self.set_value(1, emit=False)

    def set_value(self, value: int, emit: bool = True) -> None:
        self.value = int(value)
        for n, b in self.buttons.items():
            b.setChecked(n == self.value)
        if emit and self.on_change:
            self.on_change(self.value)



class TimingRulesDialog(QDialog):
    """Advanced duration thresholds, SOA matrix, and pair overrides."""

    def __init__(self, app: "MainWindow"):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("세부 SOA 규칙")
        self.resize(1260, 860)
        self.setMinimumSize(1000, 720)
        self.matrix_data = _deep_copy_timing_matrix(app.setup.timing_matrix_ms)
        self.pair_data = dict(app.setup.timing_pair_overrides_ms)
        self.current_context = ""
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        title = QLabel("자극 종류별 onset-to-onset 타이밍")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        hint = QLabel(
            "모든 값은 앞 자극의 시작 시점부터 뒤 자극의 시작 시점까지의 SOA입니다. "
            "앞 자극이 끝나기 전에 다음 자극을 시작하려면 앞 자극 duration보다 작은 값을 넣으세요. "
            "자모 pair override가 있으면 아래 class 행렬보다 우선합니다. "
            "일반 자음→모음은 자음 duration 규칙을 사용하고, 모션은 실제 길이에 따라 "
            "‘짧은 모션/긴 모션’ 행과 열을 자동 선택합니다."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        duration_card = QFrame()
        duration_card.setObjectName("EstimatorCard")
        duration_grid = QGridLayout(duration_card)
        duration_grid.setContentsMargins(16, 13, 16, 13)
        duration_grid.setHorizontalSpacing(16)
        duration_grid.setVerticalSpacing(8)
        duration_title = QLabel("Duration 분기 기준")
        duration_title.setObjectName("EstimatorTitle")
        duration_grid.addWidget(duration_title, 0, 0, 1, 4)
        self.consonant_duration_split = QSpinBox()
        self.consonant_duration_split.setRange(1, 5000)
        self.consonant_duration_split.setSuffix(" ms")
        self.consonant_duration_split.setValue(int(app.setup.cv_duration_split_ms))
        self.consonant_duration_split.setToolTip("이 값 이하이면 짧은 자음 SOA, 초과이면 긴 자음 SOA를 사용합니다.")
        self.motion_duration_split = QSpinBox()
        self.motion_duration_split.setRange(1, 5000)
        self.motion_duration_split.setSuffix(" ms")
        self.motion_duration_split.setValue(int(app.setup.motion_duration_split_ms))
        self.motion_duration_split.setToolTip("이 값 이하의 motion은 짧은 모션, 초과이면 긴 모션 행/열을 사용합니다.")
        duration_grid.addWidget(QLabel("자음 duration 기준"), 1, 0)
        duration_grid.addWidget(self.consonant_duration_split, 1, 1)
        duration_grid.addWidget(QLabel("모션 duration 기준"), 1, 2)
        duration_grid.addWidget(self.motion_duration_split, 1, 3)
        duration_note = QLabel(
            "기본값은 둘 다 300 ms입니다. 경계값과 같은 duration은 ‘짧은’ 쪽으로 분류됩니다."
        )
        duration_note.setObjectName("Hint")
        duration_note.setWordWrap(True)
        duration_grid.addWidget(duration_note, 2, 0, 1, 4)
        root.addWidget(duration_card)

        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("적용 구간"))
        self.context_combo = QComboBox()
        for key, label in TIMING_CONTEXT_LABELS.items():
            self.context_combo.addItem(label, key)
        context_row.addWidget(self.context_combo, 1)
        fill_btn = button("현재 기본 SOA로 전체 채우기", "ghost")
        fill_btn.clicked.connect(self.fill_matrix_with_default)
        context_row.addWidget(fill_btn)
        root.addLayout(context_row)

        class_note = QLabel("행 = 앞 자극 종류 · 열 = 뒤 자극 종류")
        class_note.setObjectName("Hint")
        root.addWidget(class_note)
        classes = list(TIMING_CLASS_LABELS)
        self.matrix_table = QTableWidget(len(classes), len(classes))
        self.matrix_table.setObjectName("TimingMatrixTable")
        self.matrix_table.setHorizontalHeaderLabels([TIMING_CLASS_LABELS[x] for x in classes])
        self.matrix_table.setVerticalHeaderLabels([TIMING_CLASS_LABELS[x] for x in classes])
        self.matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix_table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix_table.setMinimumHeight(340)
        self.matrix_spins: Dict[Tuple[str, str], QSpinBox] = {}
        for r, prev_cls in enumerate(classes):
            for c, next_cls in enumerate(classes):
                sp = QSpinBox()
                sp.setRange(0, 5000)
                sp.setSuffix(" ms")
                sp.setAlignment(Qt.AlignCenter)
                sp.setToolTip(
                    f"{TIMING_CLASS_LABELS[prev_cls]} 시작 → {TIMING_CLASS_LABELS[next_cls]} 시작"
                )
                self.matrix_table.setCellWidget(r, c, sp)
                self.matrix_spins[(prev_cls, next_cls)] = sp
        root.addWidget(self.matrix_table, 1)

        pair_title_row = QHBoxLayout()
        pair_title = QLabel("특정 자모 pair override")
        pair_title.setObjectName("EstimatorTitle")
        pair_title_row.addWidget(pair_title)
        pair_title_row.addStretch(1)
        self.pair_from = QComboBox(); self.pair_from.addItems(CONSONANTS + VOWELS + list(COMPOUND_FINALS))
        self.pair_to = QComboBox(); self.pair_to.addItems(CONSONANTS + VOWELS + list(COMPOUND_FINALS))
        self.pair_soa = QSpinBox(); self.pair_soa.setRange(0, 5000); self.pair_soa.setSuffix(" ms")
        add_pair = button("추가", "secondary")
        del_pair = button("선택 삭제", "ghost")
        add_pair.clicked.connect(self.add_pair_override)
        del_pair.clicked.connect(self.delete_pair_override)
        pair_title_row.addWidget(self.pair_from)
        pair_title_row.addWidget(QLabel("→"))
        pair_title_row.addWidget(self.pair_to)
        pair_title_row.addWidget(self.pair_soa)
        pair_title_row.addWidget(add_pair)
        pair_title_row.addWidget(del_pair)
        root.addLayout(pair_title_row)

        self.pair_table = QTableWidget(0, 3)
        self.pair_table.setHorizontalHeaderLabels(["앞 자모", "뒤 자모", "SOA"])
        self.pair_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pair_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.pair_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.pair_table.verticalHeader().setVisible(False)
        self.pair_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pair_table.setMaximumHeight(180)
        root.addWidget(self.pair_table)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = button("취소", "ghost")
        save_btn = button("SOA 규칙 저장", "primary")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept_rules)
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        root.addLayout(actions)

        self.context_combo.currentIndexChanged.connect(self._switch_context)
        self._switch_context(0)

    def _save_current_context(self) -> None:
        if self._loading or not self.current_context:
            return
        context = self.current_context
        rows: Dict[str, Dict[str, int]] = {}
        for prev_cls in TIMING_CLASS_LABELS:
            rows[prev_cls] = {}
            for next_cls in TIMING_CLASS_LABELS:
                rows[prev_cls][next_cls] = int(self.matrix_spins[(prev_cls, next_cls)].value())
        self.matrix_data[context] = rows

        prefix = context + "|"
        for key in [k for k in self.pair_data if k.startswith(prefix)]:
            self.pair_data.pop(key, None)
        for r in range(self.pair_table.rowCount()):
            from_lab = self.pair_table.item(r, 0).text()
            to_lab = self.pair_table.item(r, 1).text()
            soa_item = self.pair_table.item(r, 2)
            raw_soa = soa_item.data(Qt.UserRole)
            if raw_soa is None:
                match = re.search(r"\d+", soa_item.text())
                raw_soa = int(match.group(0)) if match else 0
            soa = int(raw_soa)
            key = DesignSetup.pair_override_key(context, from_lab, to_lab)
            self.pair_data[key] = soa

    def _switch_context(self, _index: int) -> None:
        if self.current_context:
            self._save_current_context()
        context = str(self.context_combo.currentData())
        self.current_context = context
        self._loading = True
        default = int(self.app.setup.timing_defaults_ms.get(context, 0))
        matrix = self.matrix_data.get(context, {})
        for prev_cls in TIMING_CLASS_LABELS:
            for next_cls in TIMING_CLASS_LABELS:
                value = matrix.get(prev_cls, {}).get(next_cls, default)
                self.matrix_spins[(prev_cls, next_cls)].setValue(int(value))
        self._load_pairs(context)
        self._loading = False

    def _load_pairs(self, context: str) -> None:
        self.pair_table.setRowCount(0)
        prefix = context + "|"
        items = []
        for key, value in self.pair_data.items():
            if not key.startswith(prefix):
                continue
            parts = key.split("|", 2)
            if len(parts) == 3:
                items.append((parts[1], parts[2], int(value)))
        for from_lab, to_lab, soa in sorted(items):
            self._append_pair_row(from_lab, to_lab, soa)

    def _append_pair_row(self, from_lab: str, to_lab: str, soa: int) -> None:
        r = self.pair_table.rowCount()
        self.pair_table.insertRow(r)
        self.pair_table.setItem(r, 0, QTableWidgetItem(from_lab))
        self.pair_table.setItem(r, 1, QTableWidgetItem(to_lab))
        item = QTableWidgetItem(f"{int(soa)} ms")
        item.setData(Qt.UserRole, int(soa))
        self.pair_table.setItem(r, 2, item)

    def add_pair_override(self) -> None:
        from_lab, to_lab, soa = self.pair_from.currentText(), self.pair_to.currentText(), self.pair_soa.value()
        for r in range(self.pair_table.rowCount()):
            if self.pair_table.item(r, 0).text() == from_lab and self.pair_table.item(r, 1).text() == to_lab:
                self.pair_table.item(r, 2).setText(f"{soa} ms")
                self.pair_table.item(r, 2).setData(Qt.UserRole, int(soa))
                self.pair_table.selectRow(r)
                return
        self._append_pair_row(from_lab, to_lab, soa)
        self.pair_table.selectRow(self.pair_table.rowCount() - 1)

    def delete_pair_override(self) -> None:
        r = self.pair_table.currentRow()
        if r >= 0:
            self.pair_table.removeRow(r)

    def fill_matrix_with_default(self) -> None:
        context = str(self.context_combo.currentData())
        default = int(self.app.setup.timing_defaults_ms.get(context, 0))
        for sp in self.matrix_spins.values():
            sp.setValue(default)

    def accept_rules(self) -> None:
        self._save_current_context()
        self.app.setup.timing_matrix_ms = _expand_motion_duration_matrix(
            self.matrix_data, self.app.setup.timing_defaults_ms
        )
        self.app.setup.timing_pair_overrides_ms = dict(self.pair_data)
        self.app.setup.cv_duration_split_ms = int(self.consonant_duration_split.value())
        self.app.setup.motion_duration_split_ms = int(self.motion_duration_split.value())
        self.app.update_duration_rule_summary()
        self.app.mark_dirty()
        self.app.update_duration_estimate()
        self.app.mapping_editor.preview_current(show_error=False)
        self.accept()


class MappingEditor(QWidget):
    def __init__(self, app: "MainWindow"):
        super().__init__()
        self.app = app
        self.current_label = "ㄱ"
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        title_row = QHBoxLayout()
        self.title = QLabel("ㄱ 디자인")
        self.title.setObjectName("SectionTitle")
        title_row.addWidget(self.title)
        title_row.addStretch(1)
        title_row.addWidget(QLabel("고급 SOA 유형"))
        self.timing_class_combo = QComboBox()
        self.timing_class_combo.addItem("자동 판별", "auto")
        for key, label in TIMING_CLASS_EDITOR_LABELS.items():
            self.timing_class_combo.addItem(label, key)
        self.timing_class_combo.setToolTip(
            "대부분 자동 판별로 둡니다. 모션은 실제 duration과 고급 설정의 모션 기준으로 "
            "짧은 모션/긴 모션 SOA 행렬을 자동 선택합니다."
        )
        title_row.addWidget(self.timing_class_combo)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Atomic · 한 위치/시간 패턴", "atomic")
        self.mode_combo.addItem("Composite · 다른 자모 조합", "composite")
        self.mode_combo.addItem("Raw · 직접 serial script", "raw")
        self.mode_combo.addItem("Unmapped", "unmapped")
        self.mode_combo.currentIndexChanged.connect(self.update_mode_visibility)
        title_row.addWidget(self.mode_combo)
        root.addLayout(title_row)

        self.mode_stack = QStackedWidget()
        root.addWidget(self.mode_stack, 1)

        # Atomic page
        atomic_page = QWidget()
        ag = QGridLayout(atomic_page)
        ag.setContentsMargins(4, 4, 4, 4)
        ag.setHorizontalSpacing(18)
        ag.setVerticalSpacing(12)
        ag.addWidget(QLabel("팔"), 0, 0)
        self.arm_combo = QComboBox()
        self.arm_combo.addItem("왼팔 · #", "left")
        self.arm_combo.addItem("오른팔 · @", "right")
        ag.addWidget(self.arm_combo, 0, 1)
        ag.addWidget(QLabel("Temporal factor"), 1, 0)
        self.temporal_combo = QComboBox()
        for key, cfg in TEMPORAL_PRESETS.items():
            self.temporal_combo.addItem(cfg["label"], key)
        self.temporal_combo.currentIndexChanged.connect(self.update_custom_visibility)
        ag.addWidget(self.temporal_combo, 1, 1)
        ag.addWidget(QLabel("논리적 위치"), 2, 0, Qt.AlignTop)
        self.pos_grid = PositionGrid()
        ag.addWidget(self.pos_grid, 2, 1)
        self.custom_frame = QFrame()
        custom = QHBoxLayout(self.custom_frame)
        custom.setContentsMargins(0, 0, 0, 0)
        self.on1_spin = QSpinBox(); self.on1_spin.setRange(1, 3000); self.on1_spin.setValue(200); self.on1_spin.setSuffix(" ms")
        self.gap_spin = QSpinBox(); self.gap_spin.setRange(0, 3000); self.gap_spin.setValue(100); self.gap_spin.setSuffix(" ms")
        self.on2_spin = QSpinBox(); self.on2_spin.setRange(0, 3000); self.on2_spin.setValue(200); self.on2_spin.setSuffix(" ms")
        custom.addWidget(QLabel("ON1")); custom.addWidget(self.on1_spin)
        custom.addWidget(QLabel("Gap")); custom.addWidget(self.gap_spin)
        custom.addWidget(QLabel("ON2")); custom.addWidget(self.on2_spin)
        ag.addWidget(self.custom_frame, 3, 1)
        ag.setRowStretch(4, 1)
        self.mode_stack.addWidget(atomic_page)

        # Composite page
        composite_page = QWidget()
        cg = QVBoxLayout(composite_page)
        cg.setContentsMargins(4, 4, 4, 4)
        hint = QLabel(
            "예: ㅢ = ㅡ + ㅣ. 각 step은 저장된 자모 디자인을 참조합니다. "
            "오른쪽의 Composite 기본 SOA는 새 Step을 추가할 때 들어가는 onset 간격이며, "
            "이미 만든 행의 개별 SOA는 자동으로 덮어쓰지 않습니다."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Hint")
        cg.addWidget(hint)
        self.steps_table = QTableWidget(0, 2)
        self.steps_table.setObjectName("StepsTable")
        self.steps_table.setHorizontalHeaderLabels(["구성 자모", "이전 onset → 현재 onset (ms)"])
        table_header = self.steps_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.Stretch)
        table_header.setSectionResizeMode(1, QHeaderView.Fixed)
        table_header.resizeSection(1, 196)
        table_header.setMinimumHeight(50)
        table_header.setDefaultAlignment(Qt.AlignCenter)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.verticalHeader().setDefaultSectionSize(60)
        self.steps_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.steps_table.setSelectionMode(QTableWidget.SingleSelection)
        self.steps_table.setShowGrid(False)
        self.steps_table.setMinimumHeight(260)
        cg.addWidget(self.steps_table, 1)
        cr = QHBoxLayout()
        self.ref_combo = QComboBox(); self.ref_combo.addItems(CONSONANTS + VOWELS)
        self.ref_combo.setToolTip("새로 추가할 구성 자모")
        self.step_gap_spin = QSpinBox()
        self.step_gap_spin.setRange(0, 2000)
        self.step_gap_spin.setValue(int(self.app.setup.timing_defaults_ms.get("composite", 350)))
        self.step_gap_spin.setSuffix(" ms")
        self.step_gap_spin.setToolTip("새 Step을 이전 Step 시작 후 몇 ms에 시작할지 설정합니다. 오른쪽 Composite 기본 SOA와 동기화됩니다.")
        add_btn = button("＋ Step", "secondary")
        del_btn = button("삭제", "ghost")
        apply_gap_btn = button("기존 Step에 적용", "ghost")
        apply_gap_btn.setToolTip("현재 SOA 값을 이미 만든 2번째 이후 Step에 한 번에 적용합니다.")
        up_btn = QPushButton()
        up_btn.setObjectName("RoundIconButton")
        up_btn.setIcon(QIcon(str(ARROW_UP_SVG)))
        up_btn.setIconSize(QSize(22, 22))
        up_btn.setFixedSize(48, 48)
        up_btn.setCursor(Qt.PointingHandCursor)
        up_btn.setToolTip("선택한 step을 위로 이동")
        down_btn = QPushButton()
        down_btn.setObjectName("RoundIconButton")
        down_btn.setIcon(QIcon(str(ARROW_DOWN_SVG)))
        down_btn.setIconSize(QSize(22, 22))
        down_btn.setFixedSize(48, 48)
        down_btn.setCursor(Qt.PointingHandCursor)
        down_btn.setToolTip("선택한 step을 아래로 이동")
        add_btn.clicked.connect(self.add_step)
        del_btn.clicked.connect(self.delete_step)
        apply_gap_btn.clicked.connect(self.apply_step_gap_to_existing)
        up_btn.clicked.connect(lambda: self.move_step(-1))
        down_btn.clicked.connect(lambda: self.move_step(1))
        cr.addWidget(QLabel("추가할 자모"))
        cr.addWidget(self.ref_combo)
        cr.addWidget(QLabel("새 Step SOA"))
        cr.addWidget(self.step_gap_spin)
        cr.addWidget(add_btn)
        cr.addWidget(del_btn)
        cr.addWidget(apply_gap_btn)
        cr.addStretch(1)
        cr.addWidget(up_btn)
        cr.addWidget(down_btn)
        cg.addLayout(cr)
        self.mode_stack.addWidget(composite_page)

        # Raw page
        raw_page = QWidget()
        rg = QVBoxLayout(raw_page)
        rg.setContentsMargins(4, 4, 4, 4)
        raw_hint = QLabel("고급 기능: @/# marker를 포함한 전체 serial script를 직접 입력합니다.")
        raw_hint.setObjectName("Hint")
        self.raw_edit = QPlainTextEdit()
        self.raw_edit.setPlaceholderText("예: #5/150.#5/d,4/i/100.#4/150")
        rg.addWidget(raw_hint)
        rg.addWidget(self.raw_edit, 1)
        self.mode_stack.addWidget(raw_page)

        # Unmapped page
        unmapped = QWidget()
        ul = QVBoxLayout(unmapped)
        lab = QLabel("이 자모를 사용하지 않습니다. 이 자모가 포함된 음절은 컴파일되지 않습니다.")
        lab.setObjectName("Hint")
        lab.setWordWrap(True)
        ul.addWidget(lab)
        ul.addStretch(1)
        self.mode_stack.addWidget(unmapped)

        note_row = QHBoxLayout()
        note_row.addWidget(QLabel("메모"))
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("디자인 의도 또는 설명")
        note_row.addWidget(self.note_edit, 1)
        root.addLayout(note_row)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(105)
        self.preview.setPlaceholderText("컴파일된 command가 표시됩니다.")
        root.addWidget(self.preview)

        action = QHBoxLayout()
        save_btn = button("매핑 저장", "primary")
        preview_btn = button("미리보기", "secondary")
        test_btn = button("이 자모 느껴보기", "secondary")
        save_btn.clicked.connect(self.save_current)
        preview_btn.clicked.connect(self.preview_current)
        test_btn.clicked.connect(self.test_current)
        action.addWidget(preview_btn)
        action.addWidget(test_btn)
        action.addStretch(1)
        action.addWidget(save_btn)
        root.addLayout(action)

        # The command preview is live. Every mapping control refreshes both the
        # compiled command and the estimated physical playback duration.
        self.mode_combo.currentIndexChanged.connect(self._on_editor_value_changed)
        self.timing_class_combo.currentIndexChanged.connect(self._on_editor_value_changed)
        self.arm_combo.currentIndexChanged.connect(self._on_editor_value_changed)
        self.temporal_combo.currentIndexChanged.connect(self._on_editor_value_changed)
        self.pos_grid.on_change = lambda _value: self._on_editor_value_changed()
        for spin in (self.on1_spin, self.gap_spin, self.on2_spin):
            spin.valueChanged.connect(self._on_editor_value_changed)
        self.raw_edit.textChanged.connect(self._on_editor_value_changed)

    def _on_editor_value_changed(self, *_args) -> None:
        if self._loading:
            return
        self.preview_current(show_error=False)

    def update_mode_visibility(self) -> None:
        mode = self.mode_combo.currentData()
        index = {"atomic": 0, "composite": 1, "raw": 2, "unmapped": 3}.get(mode, 3)
        self.mode_stack.setCurrentIndex(index)
        self.update_custom_visibility()

    def update_custom_visibility(self) -> None:
        self.custom_frame.setVisible(self.temporal_combo.currentData() == "CUSTOM")

    def load_label(self, label: str) -> None:
        self._loading = True
        self.current_label = label
        self.title.setText(f"{label} 디자인")
        spec = self.app.setup.get_spec(label)
        idx = self.mode_combo.findData(spec.mode)
        self.mode_combo.setCurrentIndex(max(0, idx))
        timing_idx = self.timing_class_combo.findData(spec.timing_class)
        self.timing_class_combo.setCurrentIndex(max(0, timing_idx))
        self.arm_combo.setCurrentIndex(max(0, self.arm_combo.findData(spec.arm)))
        self.pos_grid.set_value(spec.position, emit=False)
        self.temporal_combo.setCurrentIndex(max(0, self.temporal_combo.findData(spec.temporal)))
        self.on1_spin.setValue(int(spec.on1_ms))
        self.gap_spin.setValue(int(spec.gap_ms))
        self.on2_spin.setValue(int(spec.on2_ms))
        self.steps_table.setRowCount(0)
        for step in spec.steps:
            self._append_step_row(str(step.get("ref", "")), int(step.get("soa_before_ms", step.get("gap_before_ms", 0))))
        self.raw_edit.setPlainText(spec.raw_command)
        self.note_edit.setText(spec.note)
        self.update_mode_visibility()
        self.set_default_composite_gap(self.app.setup.timing_defaults_ms.get("composite", 350))
        self.preview_current(show_error=False)
        self._loading = False

    def set_default_composite_gap(self, value: int) -> None:
        """Synchronize the new-Step gap control with the global timing default.

        Existing table rows keep their explicit per-step values. This prevents a
        global default change from silently destroying a deliberately customized
        composite pattern.
        """
        value = max(0, int(value))
        self.step_gap_spin.blockSignals(True)
        self.step_gap_spin.setValue(value)
        self.step_gap_spin.blockSignals(False)

    def _append_step_row(self, ref: str, soa_before: int) -> None:
        r = self.steps_table.rowCount()
        self.steps_table.insertRow(r)
        self.steps_table.setRowHeight(r, 60)
        combo = QComboBox()
        combo.setObjectName("TableComboBox")
        combo.addItems(CONSONANTS + VOWELS)
        combo.setCurrentText(ref)
        combo.setMinimumHeight(44)
        spin = QSpinBox()
        spin.setObjectName("TableSpinBox")
        spin.setRange(0, 2000)
        spin.setSuffix(" ms")
        spin.setValue(int(soa_before))
        spin.setMinimumHeight(44)
        spin.setMinimumWidth(184)
        combo.currentTextChanged.connect(self._on_editor_value_changed)
        spin.valueChanged.connect(self._on_editor_value_changed)
        self.steps_table.setCellWidget(r, 0, combo)
        self.steps_table.setCellWidget(r, 1, spin)

    def add_step(self) -> None:
        gap = 0 if self.steps_table.rowCount() == 0 else self.step_gap_spin.value()
        self._append_step_row(self.ref_combo.currentText(), gap)
        self.steps_table.selectRow(self.steps_table.rowCount() - 1)
        self._on_editor_value_changed()

    def delete_step(self) -> None:
        r = self.steps_table.currentRow()
        if r >= 0:
            self.steps_table.removeRow(r)
            self._on_editor_value_changed()

    def apply_step_gap_to_existing(self) -> None:
        """Apply the new-Step gap value to every existing step after the first."""
        gap = int(self.step_gap_spin.value())
        for r in range(self.steps_table.rowCount()):
            spin = self.steps_table.cellWidget(r, 1)
            if spin is not None:
                spin.setValue(0 if r == 0 else gap)
        self._on_editor_value_changed()

    def move_step(self, delta: int) -> None:
        r = self.steps_table.currentRow()
        nr = r + delta
        if r < 0 or nr < 0 or nr >= self.steps_table.rowCount():
            return
        a = self._step_at(r); b = self._step_at(nr)
        self._set_step_at(r, b); self._set_step_at(nr, a)
        self.steps_table.selectRow(nr)
        self._on_editor_value_changed()

    def _step_at(self, r: int) -> Dict[str, Any]:
        return {
            "ref": self.steps_table.cellWidget(r, 0).currentText(),
            "soa_before_ms": self.steps_table.cellWidget(r, 1).value(),
        }

    def _set_step_at(self, r: int, step: Dict[str, Any]) -> None:
        self.steps_table.cellWidget(r, 0).setCurrentText(str(step["ref"]))
        self.steps_table.cellWidget(r, 1).setValue(int(step.get("soa_before_ms", step.get("gap_before_ms", 0))))

    def collect_spec(self) -> JamoSpec:
        mode = self.mode_combo.currentData()
        steps = [self._step_at(r) for r in range(self.steps_table.rowCount())]
        return JamoSpec(
            mode=mode,
            arm=self.arm_combo.currentData(),
            position=self.pos_grid.value,
            temporal=self.temporal_combo.currentData(),
            on1_ms=self.on1_spin.value(),
            gap_ms=self.gap_spin.value(),
            on2_ms=self.on2_spin.value(),
            steps=steps,
            raw_command=self.raw_edit.toPlainText().strip(),
            note=self.note_edit.text().strip(),
            timing_class=self.timing_class_combo.currentData(),
        )

    def save_current(self) -> None:
        self.app.setup.set_spec(self.current_label, self.collect_spec())
        self.app.mark_dirty()
        self.app.refresh_jamo_lists()
        self.preview_current()
        self.app.update_duration_estimate()
        self.app.toast(f"{self.current_label} 매핑 저장됨")

    def preview_current(self, show_error: bool = True) -> None:
        backup = self.app.setup.jamo.get(self.current_label)
        self.app.setup.set_spec(self.current_label, self.collect_spec())
        try:
            cmd = HangulCompiler(self.app.setup).compile_jamo(self.current_label)
            dur = HangulCompiler.estimate_duration_ms(cmd)
            timing_class = self.app.setup.timing_class_for(self.current_label)
            class_label = TIMING_CLASS_EDITOR_LABELS.get(timing_class, timing_class)
            self.preview.setPlainText(f"{cmd}\n예상 duration: {dur} ms · 고급 SOA 유형: {class_label}")
        except Exception as exc:
            self.preview.setPlainText(f"컴파일 오류: {exc}")
            if show_error:
                self.app.toast(str(exc), error=True)
        finally:
            if backup is None:
                self.app.setup.jamo.pop(self.current_label, None)
            else:
                self.app.setup.jamo[self.current_label] = backup

    def test_current(self) -> None:
        self.save_current()
        try:
            cmd = HangulCompiler(self.app.setup).compile_jamo(self.current_label)
            self.app.send_command(cmd)
        except Exception as exc:
            QMessageBox.critical(self, "자극 오류", str(exc))


# ----------------------------- main window -----------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Hangul Tactile Designer")
        self.resize(1680, 980)
        self.setMinimumSize(1280, 760)
        self.setup = make_default_setup()
        self.setup_path: Optional[Path] = None
        self.dirty = False
        self.serial_ctl = SerialController()
        self.voice_backend = None
        self.voice_backend_path = RESOURCE_DIR / "hangul_voice_backend.py"
        if not self.voice_backend_path.exists():
            legacy_backend = RESOURCE_DIR / "hangul_voice_backend_v20.py"
            if legacy_backend.exists():
                self.voice_backend_path = legacy_backend
        self.quiz_labels: List[str] = []
        self.quiz_plan: List[str] = []
        self.quiz_index = -1
        self.quiz_target = ""
        self.quiz_command = ""
        self.quiz_worker = None
        self.quiz_started_perf = 0.0
        self.quiz_rows: List[Dict[str, Any]] = []
        self.quiz_csv_path: Optional[Path] = None
        self.build_ui()
        self.apply_style()
        self.refresh_ports()
        self.refresh_jamo_lists()
        self.mapping_editor.load_label("ㄱ")
        self.sync_setup_controls_from_model()
        self.update_setup_title()

    # --------- UI shell ---------
    def build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(246)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(22, 28, 22, 24)
        sl.setSpacing(10)
        brand = QLabel("Tactile\nHangul")
        brand.setObjectName("Brand")
        sl.addWidget(brand)
        subtitle = QLabel("DESIGN STUDIO")
        subtitle.setObjectName("Eyebrow")
        sl.addWidget(subtitle)
        sl.addSpacing(22)
        self.nav_buttons: List[QPushButton] = []
        navs = [
            ("디자인", 0),
            ("심플 테스트", 1),
            ("보이스 퀴즈", 2),
            ("하드웨어 · 설정", 3),
        ]
        for text, idx in navs:
            b = QPushButton(text)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=idx: self.switch_page(i))
            self.nav_buttons.append(b)
            sl.addWidget(b)
        sl.addStretch(1)
        self.sidebar_status = QLabel("DRY RUN")
        self.sidebar_status.setObjectName("StatusPill")
        self.sidebar_status.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.sidebar_status)
        emergency = button("Emergency OFF", "danger")
        emergency.clicked.connect(self.emergency_off)
        sl.addWidget(emergency)
        outer.addWidget(sidebar)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(28, 22, 30, 28)
        rl.setSpacing(14)
        top = QFrame(); top.setObjectName("TopBar")
        tl = QHBoxLayout(top); tl.setContentsMargins(22, 14, 16, 14)
        self.setup_title = QLabel("Default Hangul Design")
        self.setup_title.setObjectName("TopTitle")
        tl.addWidget(self.setup_title)
        tl.addStretch(1)
        new_btn = button("새 디자인", "ghost")
        load_btn = button("불러오기", "secondary")
        save_btn = button("저장", "primary")
        save_as_btn = button("다른 이름으로", "secondary")
        new_btn.clicked.connect(self.new_setup)
        load_btn.clicked.connect(self.load_setup_dialog)
        save_btn.clicked.connect(self.save_setup)
        save_as_btn.clicked.connect(lambda: self.save_setup(save_as=True))
        for b in (new_btn, load_btn, save_as_btn, save_btn):
            tl.addWidget(b)
        rl.addWidget(top)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_design_page())
        self.stack.addWidget(self.build_simple_page())
        self.stack.addWidget(self.build_quiz_page())
        self.stack.addWidget(self.build_hardware_page())
        rl.addWidget(self.stack, 1)
        self.toast_label = QLabel("")
        self.toast_label.setObjectName("Toast")
        self.toast_label.setAlignment(Qt.AlignCenter)
        self.toast_label.hide()
        rl.addWidget(self.toast_label)
        outer.addWidget(right, 1)
        self.switch_page(0)

    def build_design_page(self) -> QWidget:
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left = card(); left.setMinimumWidth(340); left.setMaximumWidth(390)
        ll = QVBoxLayout(left); ll.setContentsMargins(22, 20, 22, 20); ll.setSpacing(12)
        t = QLabel("자모 라이브러리"); t.setObjectName("SectionTitle"); ll.addWidget(t)
        hint = QLabel("자모를 선택하고 atomic / composite / raw 방식으로 디자인하세요.")
        hint.setObjectName("Hint"); hint.setWordWrap(True); ll.addWidget(hint)
        self.jamo_tabs = QTabWidget()
        self.consonant_list = QListWidget(); self.vowel_list = QListWidget()
        self.consonant_list.itemClicked.connect(lambda item: self.mapping_editor.load_label(item.data(Qt.UserRole)))
        self.vowel_list.itemClicked.connect(lambda item: self.mapping_editor.load_label(item.data(Qt.UserRole)))
        self.jamo_tabs.setObjectName("JamoSegmentedTabs")
        self.jamo_tabs.addTab(self.consonant_list, "자음")
        self.jamo_tabs.addTab(self.vowel_list, "모음")
        self.jamo_tabs.setDocumentMode(True)
        self.jamo_tabs.setUsesScrollButtons(False)
        self.jamo_tabs.tabBar().setExpanding(True)
        self.jamo_tabs.currentChanged.connect(self.update_jamo_tab_state)
        self.update_jamo_tab_state(0)
        ll.addWidget(self.jamo_tabs, 1)
        validate = button("전체 디자인 검증", "secondary")
        validate.clicked.connect(self.validate_design)
        ll.addWidget(validate)
        root.addWidget(left)

        center = card()
        cl = QVBoxLayout(center); cl.setContentsMargins(24, 22, 24, 22)
        self.mapping_editor = MappingEditor(self)
        cl.addWidget(self.mapping_editor)
        root.addWidget(center, 1)

        # Keep the timing controls usable on laptops or Windows displays with
        # large DPI scaling.  The previous layout allowed Qt to vertically
        # squeeze the estimator card when the available height was short,
        # causing its labels and spin box to overlap.  A dedicated scroll area
        # now preserves each control's natural height instead.
        timing = card(); timing.setMinimumWidth(360); timing.setMaximumWidth(410)
        timing_outer = QVBoxLayout(timing)
        timing_outer.setContentsMargins(0, 0, 0, 0)
        timing_scroll = QScrollArea()
        timing_scroll.setObjectName("TimingScroll")
        timing_scroll.setWidgetResizable(True)
        timing_scroll.setFrameShape(QFrame.NoFrame)
        timing_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        timing_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        timing_body = QWidget()
        timing_body.setObjectName("TimingScrollBody")
        timing_body.setMinimumHeight(1240)
        gl = QVBoxLayout(timing_body); gl.setContentsMargins(22, 20, 22, 20); gl.setSpacing(12)
        timing_scroll.setWidget(timing_body)
        timing_outer.addWidget(timing_scroll)
        gt = QLabel("음절 타이밍"); gt.setObjectName("SectionTitle"); gl.addWidget(gt)
        gh = QLabel(
            "자모 내부는 onset→onset SOA입니다. 음절·단어 경계는 앞 음절의 모든 자극이 끝난 뒤부터 재는 ISI입니다. "
            "현재 Arduino를 그대로 쓰므로 distinct step의 SOA는 앞 step duration 이상이어야 합니다."
        )
        gh.setObjectName("Hint"); gh.setWordWrap(True); gl.addWidget(gh)
        self.default_comp_gap = self._labeled_spin(gl, "Composite 기본 SOA", 0, 5000, 350)

        duration_hint = QLabel(
            "자→모 SOA는 앞 자음의 실제 duration으로 자동 분기합니다. 기본 기준은 300 ms이며, "
            "자음·모션 duration 기준은 아래 고급 설정에서 바꿀 수 있습니다."
        )
        duration_hint.setObjectName("Hint"); duration_hint.setWordWrap(True); gl.addWidget(duration_hint)
        self.duration_rule_summary = QLabel("")
        self.duration_rule_summary.setObjectName("Hint")
        self.duration_rule_summary.setWordWrap(True)
        gl.addWidget(self.duration_rule_summary)
        self.cv_short_soa = self._labeled_spin(gl, "CV · 짧은 자음→모음 SOA", 0, 5000, 450)
        self.cv_long_soa = self._labeled_spin(gl, "CV · 긴 자음→모음 SOA", 0, 5000, 700)
        self.cvc_cv_short_soa = self._labeled_spin(gl, "CVC · 짧은 첫 자음→모음 SOA", 0, 5000, 450)
        self.cvc_cv_long_soa = self._labeled_spin(gl, "CVC · 긴 첫 자음→모음 SOA", 0, 5000, 700)
        # Compatibility aliases used by a few older helper methods.
        self.cv_gap = self.cv_short_soa
        self.cvc_cv_gap = self.cvc_cv_short_soa

        self.cvc_vc_gap = self._labeled_spin(gl, "CVC · 모음→끝 자음 SOA", 0, 5000, 450)
        self.comp_final_gap = self._labeled_spin(gl, "복합 종성 onset 간격", 0, 5000, 350)
        self.syllable_gap = self._labeled_spin(gl, "음절 경계 ISI", 0, 7000, 350)
        self.word_gap = self._labeled_spin(gl, "단어 경계 ISI", 0, 10000, 650)
        self.default_comp_gap.setToolTip(
            "Composite에서 + Step을 누를 때 이전 Step onset부터 새 Step onset까지의 기본값입니다. "
            "기존 행의 개별 SOA는 자동으로 바뀌지 않습니다."
        )
        self.cv_short_soa.setToolTip("받침 없는 CV에서 짧은 초성 시작부터 모음 시작까지")
        self.cv_long_soa.setToolTip("받침 없는 CV에서 긴 초성 시작부터 모음 시작까지")
        self.cvc_cv_short_soa.setToolTip("받침 있는 CVC에서 짧은 초성 시작부터 모음 시작까지")
        self.cvc_cv_long_soa.setToolTip("받침 있는 CVC에서 긴 초성 시작부터 모음 시작까지")
        self.cvc_vc_gap.setToolTip("받침 있는 CVC에서 모음 시작부터 종성 시작까지")
        self.comp_final_gap.setToolTip("ㄳ, ㄵ, ㄺ 등 복합 종성의 첫 자음 onset부터 둘째 자음 onset까지")
        self.syllable_gap.setToolTip("앞 음절의 마지막 모터 자극이 완전히 끝난 뒤 다음 음절 초성 시작까지")
        self.word_gap.setToolTip("앞 단어의 마지막 모터 자극이 완전히 끝난 뒤 다음 단어 첫 초성 시작까지")
        self.default_comp_gap.valueChanged.connect(self.on_default_composite_gap_changed)
        for sp in (
            self.cv_short_soa, self.cv_long_soa,
            self.cvc_cv_short_soa, self.cvc_cv_long_soa,
            self.cvc_vc_gap, self.comp_final_gap, self.syllable_gap, self.word_gap,
        ):
            sp.valueChanged.connect(self.sync_model_from_setup_controls)
        advanced_btn = button("고급 duration·유형·pair SOA", "secondary")
        advanced_btn.setToolTip(
            "자음/모션 duration 분기 기준, 짧은·긴 모션 SOA 행렬, 특정 자모 pair override를 설정합니다."
        )
        advanced_btn.clicked.connect(self.open_timing_rules)
        gl.addWidget(advanced_btn)

        gl.addSpacing(4)
        estimate_card = QFrame()
        estimate_card.setObjectName("EstimatorCard")
        estimate_card.setMinimumHeight(178)
        estimate_layout = QVBoxLayout(estimate_card)
        estimate_layout.setContentsMargins(16, 15, 16, 15)
        estimate_layout.setSpacing(7)
        estimate_title = QLabel("현재 셋업 속도 추정")
        estimate_title.setObjectName("EstimatorTitle")
        estimate_layout.addWidget(estimate_title)
        length_row = QHBoxLayout()
        length_row.addWidget(QLabel("평균 단어 길이"))
        length_row.addStretch(1)
        self.word_length_spin = QSpinBox()
        self.word_length_spin.setRange(1, 10)
        self.word_length_spin.setValue(2)
        self.word_length_spin.setSuffix(" 음절")
        self.word_length_spin.setMaximumWidth(145)
        self.word_length_spin.valueChanged.connect(self.update_duration_estimate)
        length_row.addWidget(self.word_length_spin)
        estimate_layout.addLayout(length_row)
        self.duration_estimate_value = QLabel("계산 중…")
        self.duration_estimate_value.setObjectName("EstimatorValue")
        self.duration_estimate_value.setWordWrap(True)
        estimate_layout.addWidget(self.duration_estimate_value)
        self.duration_estimate_note = QLabel("")
        self.duration_estimate_note.setObjectName("EstimatorNote")
        self.duration_estimate_note.setWordWrap(True)
        estimate_layout.addWidget(self.duration_estimate_note)
        gl.addWidget(estimate_card)

        explain = QLabel(
            "예: 자음 기준 300 ms이면 300 ms는 짧은 SOA, 550 ms는 긴 SOA 사용\n"
            "모션도 고급 설정의 기준에 따라 짧은 모션/긴 모션 SOA 행렬을 사용\n"
            "음절·단어 경계는 앞 자극 종료 후 ISI"
        )
        explain.setObjectName("MiniCard")
        explain.setWordWrap(True)
        explain.setMinimumHeight(82)
        gl.addWidget(explain)
        gl.addStretch(1)
        root.addWidget(timing)
        return page

    def build_simple_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(16)
        hero = card(); hl = QVBoxLayout(hero); hl.setContentsMargins(32, 28, 32, 28); hl.setSpacing(14)
        title = QLabel("입력한 한글을 바로 느껴보기"); title.setObjectName("HeroTitle"); hl.addWidget(title)
        sub = QLabel("예: 각, 한글, 의. 현재 저장된 디자인과 onset-to-onset SOA 규칙으로 command를 생성합니다.")
        sub.setObjectName("Hint"); hl.addWidget(sub)
        row = QHBoxLayout()
        self.simple_input = QLineEdit(); self.simple_input.setPlaceholderText("각"); self.simple_input.setMinimumHeight(58)
        compile_btn = button("Command 만들기", "secondary")
        play_btn = button("자극 재생", "primary")
        compile_btn.clicked.connect(self.compile_simple)
        play_btn.clicked.connect(self.play_simple)
        self.simple_input.returnPressed.connect(self.play_simple)
        row.addWidget(self.simple_input, 1); row.addWidget(compile_btn); row.addWidget(play_btn)
        hl.addLayout(row)
        root.addWidget(hero)

        details = card(); dl = QVBoxLayout(details); dl.setContentsMargins(24, 22, 24, 22)
        self.simple_summary = QLabel("아직 컴파일된 자극이 없습니다."); self.simple_summary.setObjectName("SectionTitle"); dl.addWidget(self.simple_summary)
        self.simple_command = QPlainTextEdit(); self.simple_command.setReadOnly(True); dl.addWidget(self.simple_command, 1)
        root.addWidget(details, 1)
        return page

    def build_quiz_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(14)
        config = card(); cl = QGridLayout(config); cl.setContentsMargins(24, 20, 24, 20); cl.setHorizontalSpacing(12); cl.setVerticalSpacing(10)
        title = QLabel("Voice Quiz"); title.setObjectName("SectionTitle"); cl.addWidget(title, 0, 0, 1, 6)
        cl.addWidget(QLabel("Subject"), 1, 0)
        self.subject_edit = QLineEdit(); self.subject_edit.setPlaceholderText("s01"); cl.addWidget(self.subject_edit, 1, 1)
        cl.addWidget(QLabel("Quiz set"), 1, 2)
        self.quiz_type = QComboBox(); self.quiz_type.addItem("저장된 전체 자모", "jamo_all"); self.quiz_type.addItem("자음", "consonant"); self.quiz_type.addItem("모음", "vowel"); self.quiz_type.addItem("Syllable XLSX", "syllable")
        cl.addWidget(self.quiz_type, 1, 3)
        cl.addWidget(QLabel("Trials"), 1, 4)
        self.quiz_trials = QSpinBox(); self.quiz_trials.setRange(1, 1000); self.quiz_trials.setValue(40); cl.addWidget(self.quiz_trials, 1, 5)
        cl.addWidget(QLabel("Voice backend"), 2, 0)
        self.backend_edit = QLineEdit(str(self.voice_backend_path)); cl.addWidget(self.backend_edit, 2, 1, 1, 4)
        backend_btn = button("찾기", "ghost"); backend_btn.clicked.connect(self.choose_backend); cl.addWidget(backend_btn, 2, 5)
        cl.addWidget(QLabel("Syllable XLSX"), 3, 0)
        self.syllable_edit = QLineEdit(str(APP_DIR / "syllable_top200.xlsx")); cl.addWidget(self.syllable_edit, 3, 1, 1, 3)
        self.syllable_edit.textChanged.connect(self.update_duration_estimate)
        syl_btn = button("찾기", "ghost"); syl_btn.clicked.connect(self.choose_syllable); cl.addWidget(syl_btn, 3, 4)
        self.syllable_limit = QSpinBox(); self.syllable_limit.setRange(1, 2000); self.syllable_limit.setValue(200); cl.addWidget(self.syllable_limit, 3, 5)
        self.syllable_limit.valueChanged.connect(self.update_duration_estimate)
        cl.addWidget(QLabel("Voice profiles"), 4, 0)
        self.voice_profiles_edit = QLineEdit(str(APP_DIR / "voice_profiles")); cl.addWidget(self.voice_profiles_edit, 4, 1, 1, 4)
        profile_btn = button("폴더", "ghost"); profile_btn.clicked.connect(self.choose_voice_profiles); cl.addWidget(profile_btn, 4, 5)
        check_btn = button("음성 모델 확인", "secondary"); check_btn.clicked.connect(self.check_voice_model)
        pooled_btn = button("Pooled 모델 생성", "secondary"); pooled_btn.clicked.connect(self.build_pooled_model)
        start_btn = button("퀴즈 시작", "primary"); start_btn.clicked.connect(self.start_quiz)
        cl.addWidget(check_btn, 5, 0, 1, 2); cl.addWidget(pooled_btn, 5, 2, 1, 2); cl.addWidget(start_btn, 5, 4, 1, 2)
        root.addWidget(config)

        stage = card(); st = QVBoxLayout(stage); st.setContentsMargins(26, 22, 26, 22); st.setSpacing(12)
        self.quiz_progress = QLabel("퀴즈를 시작하세요."); self.quiz_progress.setObjectName("Eyebrow"); st.addWidget(self.quiz_progress)
        self.quiz_instruction = QLabel("현재 디자인으로 촉각 자극을 제시하고 음성 응답 후보를 표시합니다.")
        self.quiz_instruction.setObjectName("HeroTitle"); self.quiz_instruction.setWordWrap(True); st.addWidget(self.quiz_instruction)
        self.quiz_feedback = QLabel(""); self.quiz_feedback.setObjectName("Feedback"); self.quiz_feedback.setAlignment(Qt.AlignCenter); st.addWidget(self.quiz_feedback)
        self.quiz_action = button("자극 시작 + 음성 듣기", "primary"); self.quiz_action.setMinimumHeight(62); self.quiz_action.clicked.connect(self.quiz_action_clicked); self.quiz_action.setEnabled(False); st.addWidget(self.quiz_action)
        self.candidate_widget = QWidget(); self.candidate_layout = QGridLayout(self.candidate_widget); self.candidate_layout.setSpacing(10); st.addWidget(self.candidate_widget)
        manual_row = QHBoxLayout(); self.quiz_manual = QLineEdit(); self.quiz_manual.setPlaceholderText("후보에 없으면 직접 입력"); manual_btn = button("직접 응답", "secondary"); manual_btn.clicked.connect(self.submit_manual_quiz); self.quiz_manual.returnPressed.connect(self.submit_manual_quiz); manual_row.addWidget(self.quiz_manual, 1); manual_row.addWidget(manual_btn); st.addLayout(manual_row)
        root.addWidget(stage, 1)
        return page

    def build_hardware_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(16)
        serial_card = card(); sl = QGridLayout(serial_card); sl.setContentsMargins(24, 22, 24, 22); sl.setHorizontalSpacing(12); sl.setVerticalSpacing(10)
        t = QLabel("Serial · Device mapping"); t.setObjectName("SectionTitle"); sl.addWidget(t, 0, 0, 1, 6)
        sl.addWidget(QLabel("COM"), 1, 0)
        self.port_combo = QComboBox(); sl.addWidget(self.port_combo, 1, 1, 1, 2)
        refresh = button("새로고침", "ghost"); refresh.clicked.connect(self.refresh_ports); sl.addWidget(refresh, 1, 3)
        self.connect_btn = button("연결", "primary"); self.connect_btn.clicked.connect(self.toggle_serial); sl.addWidget(self.connect_btn, 1, 4, 1, 2)
        sl.addWidget(QLabel("왼팔 marker"), 2, 0); self.left_marker_edit = QLineEdit("#"); self.left_marker_edit.setMaxLength(1); sl.addWidget(self.left_marker_edit, 2, 1)
        sl.addWidget(QLabel("오른팔 marker"), 2, 2); self.right_marker_edit = QLineEdit("@"); self.right_marker_edit.setMaxLength(1); sl.addWidget(self.right_marker_edit, 2, 3)
        sl.addWidget(QLabel("Baud"), 2, 4); self.baud_spin = QSpinBox(); self.baud_spin.setRange(9600, 2000000); self.baud_spin.setValue(115200); sl.addWidget(self.baud_spin, 2, 5)
        sl.addWidget(QLabel("논리 1..9 → motor"), 3, 0)
        self.motor_map_edit = QLineEdit("3,2,1,6,5,4,9,8,7"); sl.addWidget(self.motor_map_edit, 3, 1, 1, 4)
        apply_btn = button("mapping 적용", "secondary"); apply_btn.clicked.connect(self.apply_hardware_settings); sl.addWidget(apply_btn, 3, 5)
        self.ack_check = QCheckBox("Arduino ACK 확인")
        self.ack_check.setChecked(True)
        self.ack_check.setToolTip("ON이면 Arduino의 OK/ERR 응답을 확인한 뒤 다음 동작으로 넘어갑니다.")
        sl.addWidget(self.ack_check, 4, 0, 1, 3)
        ack_hint = QLabel("ON 상태는 초록색 스위치로 표시됩니다.")
        ack_hint.setObjectName("Hint")
        sl.addWidget(ack_hint, 4, 3, 1, 3)
        soa_fw_hint = QLabel(
            "v8은 사용 중인 기존 Arduino 코드를 그대로 사용하며 raw의 /i, /d를 PWM 숫자로 바꾸지 않습니다. "
            "기존 Arduino가 표현할 수 없는 staggered overlap은 자동 변환하지 않고 설정 오류로 알려줍니다. "
            "Arduino 코드는 지금 사용 중인 버전을 그대로 두면 됩니다."
        )
        soa_fw_hint.setObjectName("Hint")
        soa_fw_hint.setWordWrap(True)
        sl.addWidget(soa_fw_hint, 5, 0, 1, 6)
        root.addWidget(serial_card)

        test_card = card(); tl = QVBoxLayout(test_card); tl.setContentsMargins(24, 22, 24, 22)
        top = QHBoxLayout(); tt = QLabel("Hardware test"); tt.setObjectName("SectionTitle"); top.addWidget(tt); top.addStretch(1)
        self.hw_arm = QComboBox(); self.hw_arm.addItem("왼팔", "left"); self.hw_arm.addItem("오른팔", "right")
        self.hw_temporal = QComboBox();
        for k, v in TEMPORAL_PRESETS.items(): self.hw_temporal.addItem(v["label"], k)
        top.addWidget(self.hw_arm); top.addWidget(self.hw_temporal); tl.addLayout(top)
        grid = QGridLayout(); grid.setSpacing(12)
        n = 1
        for r in range(3):
            for c in range(3):
                b = QPushButton(str(n)); b.setObjectName("HardwareButton"); b.setMinimumSize(120, 82); b.clicked.connect(lambda _=False, p=n: self.test_hardware_position(p)); grid.addWidget(b, r, c); n += 1
        tl.addLayout(grid)
        root.addWidget(test_card, 1)
        return page

    def _labeled_spin(self, layout: QVBoxLayout, label: str, lo: int, hi: int, value: int) -> QSpinBox:
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel(label))
        row.addStretch(1)
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(value)
        sp.setSuffix(" ms")
        sp.setMinimumWidth(180)
        row.addWidget(sp)
        layout.addLayout(row)
        return sp

    # --------- style ---------
    def apply_style(self) -> None:
        self.setFont(QFont("Segoe UI Variable", 10))
        up_url = ARROW_UP_SVG.as_posix()
        down_url = ARROW_DOWN_SVG.as_posix()
        toggle_on_url = TOGGLE_ON_SVG.as_posix()
        toggle_off_url = TOGGLE_OFF_SVG.as_posix()
        self.setStyleSheet(f"""
        QWidget#Root {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #F5F5F7, stop:0.52 #F1F2F5, stop:1 #ECEEF2);
            color: #1C1C1E;
        }}
        QWidget {{
            font-family: "Segoe UI Variable", "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic";
            font-size: 15px;
            color: #1C1C1E;
        }}
        QFrame#Sidebar {{
            background: rgba(247, 247, 249, 246);
            border-right: 1px solid #DEDEE3;
        }}
        QLabel#Brand {{ font-size: 31px; font-weight: 780; letter-spacing: -1px; color: #1C1C1E; }}
        QLabel#Eyebrow {{ color: #8E8E93; font-size: 12px; font-weight: 760; letter-spacing: 1.5px; }}
        QPushButton#NavButton {{
            text-align: left; border: 1px solid transparent; border-radius: 18px;
            padding: 15px 17px; color: #636366; font-weight: 680; background: transparent;
        }}
        QPushButton#NavButton:hover {{ background: rgba(229,229,234,190); color: #1C1C1E; }}
        QPushButton#NavButton:checked {{
            background: #3A3A3C; color: #FFFFFF; border: 1px solid #3A3A3C;
        }}

        QFrame#TopBar, QFrame#Card {{
            background: rgba(255, 255, 255, 235);
            border: 1px solid rgba(209, 209, 214, 205);
            border-radius: 28px;
        }}
        QFrame#TopBar {{ background: rgba(255,255,255,245); }}
        QLabel#TopTitle {{ font-size: 19px; font-weight: 760; color: #1C1C1E; }}
        QLabel#SectionTitle {{ font-size: 21px; font-weight: 760; letter-spacing: -0.3px; color: #1C1C1E; }}
        QLabel#HeroTitle {{ font-size: 29px; font-weight: 790; letter-spacing: -0.8px; color: #1C1C1E; }}
        QLabel#Hint {{ color: #6E6E73; line-height: 1.35; }}
        QLabel#MiniCard {{
            background: rgba(242,242,247,220); border: 1px solid #E1E1E6;
            border-radius: 18px; padding: 15px; color: #636366;
        }}
        QLabel#StatusPill {{
            background: #E9E9ED; border: 1px solid #D8D8DC;
            border-radius: 14px; padding: 9px; color: #48484A; font-weight: 760;
        }}
        QLabel#Feedback {{
            background: #F2F2F7; border: 1px solid #E1E1E6;
            border-radius: 18px; padding: 13px; color: #48484A; font-weight: 680;
        }}
        QLabel#Toast {{ background: #3A3A3C; color: white; border-radius: 15px; padding: 11px; font-weight: 700; }}

        QPushButton {{ min-height: 40px; border-radius: 15px; padding: 9px 17px; font-weight: 700; }}
        QPushButton[kind="primary"] {{
            background: #3A3A3C; color: white; border: 1px solid #3A3A3C;
        }}
        QPushButton[kind="primary"]:hover {{ background: #2C2C2E; border-color: #2C2C2E; }}
        QPushButton[kind="primary"]:pressed {{ background: #1C1C1E; border-color: #1C1C1E; }}
        QPushButton[kind="secondary"] {{
            background: #E9E9ED; color: #1C1C1E; border: 1px solid #D8D8DC;
        }}
        QPushButton[kind="secondary"]:hover {{ background: #DEDEE3; border-color: #C7C7CC; }}
        QPushButton[kind="secondary"]:pressed {{ background: #CFCFD4; border-color: #B8B8BD; }}
        QPushButton[kind="ghost"] {{
            background: rgba(255,255,255,150); color: #3A3A3C; border: 1px solid #E1E1E6;
        }}
        QPushButton[kind="ghost"]:hover {{ background: #F0F0F3; color: #1C1C1E; }}
        QPushButton[kind="ghost"]:pressed {{ background: #E2E2E7; }}
        QPushButton[kind="danger"] {{ background: #FFF0EF; color: #D70015; border: 1px solid #FFD0CD; }}
        QPushButton[kind="danger"]:hover {{ background: #FFE4E1; border-color: #FFB8B2; }}
        QPushButton:disabled {{ background: #F0F0F2; color: #AEAEB2; border-color: #E4E4E8; }}

        QPushButton#RoundIconButton {{
            background: #E9E9ED; border: 1px solid #D8D8DC; border-radius: 17px; padding: 0px;
        }}
        QPushButton#RoundIconButton:hover {{ background: #DEDEE3; border: 1px solid #C7C7CC; }}
        QPushButton#RoundIconButton:pressed {{ background: #CFCFD4; border: 1px solid #B8B8BD; }}

        QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QListWidget, QTableWidget {{
            background: rgba(255,255,255,245);
            border: 1px solid #D8D8DC;
            border-radius: 15px; padding: 9px; color: #1C1C1E;
            selection-background-color: #D0E7FF; selection-color: #1C1C1E;
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QListWidget:focus, QTableWidget:focus {{
            border: 2px solid #8AB8F5; background: #FFFFFF;
        }}
        QComboBox {{ padding-right: 42px; min-height: 38px; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding; subcontrol-position: top right; width: 38px;
            border-left: 1px solid #E1E1E6; border-top-right-radius: 14px; border-bottom-right-radius: 14px;
            background: #F2F2F7;
        }}
        QComboBox::drop-down:hover {{ background: #E5E5EA; }}
        QComboBox::down-arrow {{ image: url("{down_url}"); width: 16px; height: 16px; }}
        QComboBox QAbstractItemView {{
            background: #FFFFFF; color: #1C1C1E; border: 1px solid #D1D1D6;
            selection-background-color: #E5E5EA; selection-color: #1C1C1E; outline: none;
        }}

        QSpinBox {{
            padding: 0px 58px 0px 16px;
            min-height: 52px;
        }}
        QSpinBox::up-button {{
            subcontrol-origin: border; subcontrol-position: top right;
            width: 50px; height: 26px;
            background: #F2F2F7;
            border-left: 1px solid #E1E1E6;
            border-bottom: 1px solid #E1E1E6;
            border-top-right-radius: 14px;
        }}
        QSpinBox::down-button {{
            subcontrol-origin: border; subcontrol-position: bottom right;
            width: 50px; height: 26px;
            background: #F2F2F7;
            border-left: 1px solid #E1E1E6;
            border-bottom-right-radius: 14px;
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #E5E5EA; }}
        QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: #D1D1D6; }}
        QSpinBox::up-arrow {{ image: url("{up_url}"); width: 16px; height: 16px; }}
        QSpinBox::down-arrow {{ image: url("{down_url}"); width: 16px; height: 16px; }}

        QTableWidget#StepsTable {{
            padding: 0px;
            border-radius: 16px;
        }}
        QTableWidget#StepsTable QComboBox,
        QTableWidget#StepsTable QSpinBox {{
            margin: 5px 7px;
            min-height: 42px;
        }}
        QTableWidget#StepsTable QSpinBox {{
            padding: 0px 52px 0px 13px;
        }}
        QTableWidget#StepsTable QSpinBox::up-button {{ width: 45px; height: 21px; }}
        QTableWidget#StepsTable QSpinBox::down-button {{ width: 45px; height: 21px; }}

        QCheckBox {{ spacing: 13px; color: #1C1C1E; font-weight: 700; min-height: 38px; }}
        QCheckBox::indicator {{ width: 56px; height: 34px; image: url("{toggle_off_url}"); }}
        QCheckBox::indicator:checked {{ image: url("{toggle_on_url}"); }}

        QListWidget {{ padding: 7px; }}
        QListWidget::item {{ padding: 12px 13px; margin: 3px; border: 1px solid transparent; border-radius: 13px; color: #48484A; }}
        QListWidget::item:hover {{ background: #EFEFF2; color: #1C1C1E; }}
        QListWidget::item:selected {{
            background: #3A3A3C; color: white; border: 1px solid #3A3A3C; font-weight: 780;
        }}

        QTabWidget#JamoSegmentedTabs::pane {{
            border: 1px solid #E1E1E6; border-radius: 20px;
            background: rgba(255,255,255,220); top: -1px;
        }}
        QTabWidget#JamoSegmentedTabs QTabBar::tab {{
            background: #ECECEF; color: #48484A;
            min-height: 32px; padding: 11px 22px; margin: 4px;
            border: 1px solid transparent; border-radius: 16px; font-size: 16px; font-weight: 700;
        }}
        QTabWidget#JamoSegmentedTabs QTabBar::tab:hover {{ background: #E1E1E5; color: #1C1C1E; }}
        QTabWidget#JamoSegmentedTabs QTabBar::tab:selected {{
            background: #3A3A3C; color: white; border: 1px solid #3A3A3C; font-weight: 820;
        }}

        QPushButton#PositionButton {{
            background: #EFEFF2; border: 1px solid #DEDEE3;
            border-radius: 21px; font-size: 20px; font-weight: 780; color: #48484A;
        }}
        QPushButton#PositionButton:hover {{ background: #E1E1E5; border-color: #C7C7CC; color: #1C1C1E; }}
        QPushButton#PositionButton:checked {{
            background: #3A3A3C; color: white; border: 2px solid #3A3A3C; font-weight: 860;
        }}
        QPushButton#HardwareButton {{
            background: #EFEFF2; border: 1px solid #DEDEE3;
            border-radius: 25px; font-size: 24px; font-weight: 790; color: #3A3A3C;
        }}
        QPushButton#HardwareButton:hover {{ background: #E1E1E5; border: 1px solid #C7C7CC; }}
        QPushButton#HardwareButton:pressed {{ background: #3A3A3C; color: white; border: 2px solid #3A3A3C; }}

        QHeaderView::section {{
            background: #F2F2F7; color: #48484A; border: none;
            border-bottom: 1px solid #DEDEE3; padding: 10px 9px; font-weight: 760;
            min-height: 28px;
        }}
        QScrollArea#TimingScroll {{
            background: transparent;
            border: none;
        }}
        QScrollArea#TimingScroll > QWidget > QWidget {{
            background: transparent;
        }}
        QWidget#TimingScrollBody {{ background: transparent; }}
        QFrame#EstimatorCard {{
            background: #F6F6F8;
            border: 1px solid #E1E1E6;
            border-radius: 18px;
        }}
        QLabel#EstimatorTitle {{ color: #3A3A3C; font-size: 15px; font-weight: 760; }}
        QLabel#EstimatorValue {{ color: #1C1C1E; font-size: 22px; font-weight: 800; }}
        QLabel#EstimatorNote {{ color: #6E6E73; font-size: 12px; }}
        QTableCornerButton::section {{ background: #F2F2F7; border: none; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
        QScrollBar::handle:vertical {{ background: #C7C7CC; border-radius: 5px; min-height: 32px; }}
        QScrollBar::handle:vertical:hover {{ background: #AEAEB2; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QToolTip {{ background: #3A3A3C; color: white; border: none; border-radius: 8px; padding: 6px; }}
        """)
        for b in self.findChildren(QPushButton):
            kind = b.property("kind")
            if kind:
                b.style().unpolish(b); b.style().polish(b)

    # --------- general ---------
    def update_jamo_tab_state(self, index: int) -> None:
        """Keep labels stable; the selected segment is shown by fill and contrast."""
        if not hasattr(self, "jamo_tabs"):
            return
        self.jamo_tabs.setTabText(0, "자음")
        self.jamo_tabs.setTabText(1, "모음")

    def switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_buttons): b.setChecked(i == index)

    def toast(self, text: str, error: bool = False) -> None:
        self.toast_label.setText(text)
        self.toast_label.setStyleSheet("background:#B3261E;color:white;border-radius:13px;padding:10px;font-weight:650;" if error else "")
        self.toast_label.show()
        QTimer.singleShot(2600, self.toast_label.hide)

    def mark_dirty(self) -> None:
        self.dirty = True
        self.update_setup_title()

    def update_setup_title(self) -> None:
        suffix = "  •  수정됨" if self.dirty else ""
        self.setup_title.setText(f"{self.setup.setup_name}{suffix}")

    def new_setup(self) -> None:
        if self.dirty and QMessageBox.question(self, "새 디자인", "저장하지 않은 변경사항을 버릴까요?") != QMessageBox.Yes:
            return
        self.setup = make_default_setup()
        self.setup.setup_name = "Untitled Hangul Design"
        self.setup_path = None
        self.dirty = True
        self.sync_setup_controls_from_model()
        self.refresh_jamo_lists()
        self.mapping_editor.load_label("ㄱ")
        self.update_setup_title()

    def save_setup(self, save_as: bool = False) -> None:
        self.sync_model_from_setup_controls()
        if save_as or self.setup_path is None:
            default = SETUP_DIR / (re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", self.setup.setup_name) + ".json")
            path, _ = QFileDialog.getSaveFileName(self, "디자인 저장", str(default), "JSON (*.json)")
            if not path:
                return
            self.setup_path = Path(path)
            self.setup.setup_name = self.setup_path.stem
        self.setup_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.setup_path, "w", encoding="utf-8") as f:
            json.dump(self.setup.to_dict(), f, ensure_ascii=False, indent=2)
        self.dirty = False
        self.update_setup_title()
        self.toast(f"저장됨 · {self.setup_path.name}")

    def load_setup_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "디자인 불러오기", str(SETUP_DIR), "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.setup = DesignSetup.from_dict(json.load(f))
            self.setup_path = Path(path)
            self.dirty = False
            self.sync_setup_controls_from_model()
            self.refresh_jamo_lists()
            self.mapping_editor.load_label("ㄱ")
            self.update_setup_title()
            self.toast(f"불러옴 · {self.setup_path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "불러오기 실패", str(exc))

    def sync_setup_controls_from_model(self) -> None:
        defaults = self.setup.timing_defaults_ms
        for widget, value in [
            (self.default_comp_gap, defaults.get("composite", 350)),
            (self.cv_short_soa, self.setup.cv_short_soa_ms),
            (self.cv_long_soa, self.setup.cv_long_soa_ms),
            (self.cvc_cv_short_soa, self.setup.cvc_cv_short_soa_ms),
            (self.cvc_cv_long_soa, self.setup.cvc_cv_long_soa_ms),
            (self.cvc_vc_gap, defaults.get("cvc_vc", 450)),
            (self.comp_final_gap, defaults.get("compound_final", 350)),
            (self.syllable_gap, self.setup.inter_syllable_isi_ms),
            (self.word_gap, self.setup.inter_word_isi_ms),
        ]:
            widget.blockSignals(True); widget.setValue(int(value)); widget.blockSignals(False)
        self.left_marker_edit.setText(self.setup.left_marker)
        self.right_marker_edit.setText(self.setup.right_marker)
        self.baud_spin.setValue(self.setup.baudrate)
        self.motor_map_edit.setText(",".join(str(self.setup.logical_to_motor[str(i)]) for i in range(1, 10)))
        if hasattr(self, "mapping_editor"):
            self.mapping_editor.set_default_composite_gap(self.setup.timing_defaults_ms.get("composite", 350))
        self.update_duration_rule_summary()
        self.update_duration_estimate()

    def on_default_composite_gap_changed(self, value: int) -> None:
        """Update the global default and the editor's new-Step gap immediately."""
        if hasattr(self, "mapping_editor"):
            self.mapping_editor.set_default_composite_gap(int(value))
        self.sync_model_from_setup_controls()

    def sync_model_from_setup_controls(self) -> None:
        if not hasattr(self, "cv_gap"):
            return
        self.setup.timing_semantics_version = 4
        new_defaults = {
            "composite": self.default_comp_gap.value(),
            # Keep these fallback defaults synchronized with the short-duration
            # values for old setup compatibility and advanced pair dialogs.
            "cv": self.cv_short_soa.value(),
            "cvc_cv": self.cvc_cv_short_soa.value(),
            "cvc_vc": self.cvc_vc_gap.value(),
            "compound_final": self.comp_final_gap.value(),
        }
        # Matrix cells that still equal the old default behave like inherited
        # values and follow the basic control. Deliberately customized cells are
        # left untouched.
        for context, new_value in new_defaults.items():
            old_value = int(self.setup.timing_defaults_ms.get(context, new_value))
            rows = self.setup.timing_matrix_ms.get(context, {})
            for cols in rows.values():
                for next_cls, cell_value in list(cols.items()):
                    if int(cell_value) == old_value:
                        cols[next_cls] = int(new_value)
        self.setup.timing_defaults_ms.update(new_defaults)
        self.setup.cv_short_soa_ms = self.cv_short_soa.value()
        self.setup.cv_long_soa_ms = self.cv_long_soa.value()
        self.setup.cvc_cv_short_soa_ms = self.cvc_cv_short_soa.value()
        self.setup.cvc_cv_long_soa_ms = self.cvc_cv_long_soa.value()
        self.setup.use_duration_based_cv_soa = True
        self.setup.inter_syllable_isi_ms = self.syllable_gap.value()
        self.setup.inter_word_isi_ms = self.word_gap.value()
        # Keep deprecated fields synchronized only for human readability in old tools.
        self.setup.default_composite_gap_ms = self.default_comp_gap.value()
        self.setup.cv_gap_ms = self.cv_gap.value()
        self.setup.cvc_cv_gap_ms = self.cvc_cv_gap.value()
        self.setup.cvc_vc_gap_ms = self.cvc_vc_gap.value()
        self.setup.compound_final_gap_ms = self.comp_final_gap.value()
        self.setup.inter_syllable_gap_ms = self.setup.inter_syllable_isi_ms
        self.setup.inter_word_gap_ms = self.setup.inter_word_isi_ms
        self.mark_dirty()
        self.update_duration_estimate()
        if hasattr(self, "mapping_editor"):
            self.mapping_editor.preview_current(show_error=False)

    def _speed_estimate_syllables(self) -> Tuple[List[str], str]:
        """Return syllables used for the live speed estimate and a source label."""
        candidate_paths: List[Path] = []
        if hasattr(self, "syllable_edit"):
            text = self.syllable_edit.text().strip()
            if text:
                candidate_paths.append(Path(text))
        candidate_paths.extend([
            APP_DIR / "syllable_top200.xlsx",
            APP_DIR / "syllable.xlsx",
        ])
        seen: set[str] = set()
        for path in candidate_paths:
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.exists():
                try:
                    labels = load_syllables(path, self.syllable_limit.value() if hasattr(self, "syllable_limit") else 200)
                    if labels:
                        return labels, path.name
                except Exception:
                    pass

        # File-independent fallback: a broad set of CV and frequent-final CVC
        # syllables. This keeps the estimate available even before an XLSX is copied.
        labels: List[str] = []
        common_finals = ["", "ㄱ", "ㄴ", "ㄹ", "ㅁ", "ㅂ", "ㅅ", "ㅇ"]
        jong_index = {j: i for i, j in enumerate(JONGSUNG)}
        for cho_idx in range(len(CHOSUNG)):
            for jung_idx in range(len(JUNGSUNG)):
                for jong in common_finals:
                    code = 0xAC00 + (cho_idx * 21 + jung_idx) * 28 + jong_index[jong]
                    labels.append(chr(code))
        return labels, "내장 CV/CVC 표본"

    def update_duration_estimate(self, *_args) -> None:
        if not hasattr(self, "duration_estimate_value"):
            return
        compiler = HangulCompiler(self.setup)
        labels, source = self._speed_estimate_syllables()
        valid: List[str] = []
        syllable_durations: List[int] = []
        for label in labels:
            try:
                command = compiler.compile_syllable(label)
                syllable_durations.append(HangulCompiler.estimate_duration_ms(command))
                valid.append(label)
            except Exception:
                continue
        if not valid:
            self.duration_estimate_value.setText("계산 불가")
            self.duration_estimate_note.setText("컴파일 가능한 음절이 없습니다. 자모 매핑을 확인하세요.")
            return

        word_len = self.word_length_spin.value() if hasattr(self, "word_length_spin") else 2
        sample_count = min(120, max(24, len(valid)))
        word_durations: List[int] = []
        word_onset_cycles: List[int] = []
        n = len(valid)
        for i in range(sample_count):
            word = "".join(valid[(i + j * 37) % n] for j in range(word_len))
            next_word = "".join(valid[(i + 19 + j * 53) % n] for j in range(word_len))
            try:
                command, _trace = compiler.compile_text(word)
                word_durations.append(HangulCompiler.estimate_duration_ms(command))

                _pair_command, pair_trace = compiler.compile_text(word + " " + next_word)
                if len(pair_trace) > word_len:
                    word_onset_cycles.append(int(pair_trace[word_len]["onset_ms"]))
            except Exception:
                continue

        if not word_durations:
            self.duration_estimate_value.setText("계산 불가")
            self.duration_estimate_note.setText("현재 SOA 규칙으로 단어를 컴파일할 수 없습니다.")
            return

        avg_syllable_ms = sum(syllable_durations) / len(syllable_durations)
        avg_word_ms = sum(word_durations) / len(word_durations)
        avg_cycle_ms = (sum(word_onset_cycles) / len(word_onset_cycles)) if word_onset_cycles else avg_word_ms
        words_per_min = 60000.0 / avg_cycle_ms if avg_cycle_ms > 0 else 0.0
        self.duration_estimate_value.setText(
            f"{word_len}음절 단어 평균  {avg_word_ms / 1000.0:.2f}초"
        )
        self.duration_estimate_note.setText(
            f"평균 음절 물리 duration {avg_syllable_ms / 1000.0:.2f}초 · "
            f"단어 onset 주기 {avg_cycle_ms / 1000.0:.2f}초 · 약 {words_per_min:.1f}단어/분\n"
            f"내부 SOA + 경계 ISI 반영 · 기준: {source} · 컴파일 성공 {len(valid)}/{len(labels)}개"
        )

    def update_duration_rule_summary(self) -> None:
        if hasattr(self, "duration_rule_summary"):
            self.duration_rule_summary.setText(
                f"현재 분기 기준 · 자음 {int(self.setup.cv_duration_split_ms)} ms · "
                f"모션 {int(self.setup.motion_duration_split_ms)} ms "
                "(기준 이하 = 짧음)"
            )

    def open_timing_rules(self) -> None:
        self.sync_model_from_setup_controls()
        dialog = TimingRulesDialog(self)
        dialog.exec()
        self.update_duration_rule_summary()

    def apply_hardware_settings(self) -> None:
        try:
            vals = [int(x.strip()) for x in self.motor_map_edit.text().split(",")]
            if len(vals) != 9 or any(v < 1 or v > 9 for v in vals):
                raise ValueError("motor mapping은 1~9 숫자 9개여야 합니다.")
            lm, rm = self.left_marker_edit.text().strip(), self.right_marker_edit.text().strip()
            if lm not in ("@", "#") or rm not in ("@", "#") or lm == rm:
                raise ValueError("marker는 @와 #를 서로 다르게 지정해야 합니다.")
            self.setup.left_marker = lm; self.setup.right_marker = rm
            self.setup.baudrate = self.baud_spin.value()
            self.setup.logical_to_motor = {str(i + 1): vals[i] for i in range(9)}
            self.mark_dirty(); self.mapping_editor.preview_current(show_error=False)
            self.toast("하드웨어 mapping 적용됨")
        except Exception as exc:
            QMessageBox.warning(self, "Mapping 오류", str(exc))

    def refresh_jamo_lists(self) -> None:
        if not hasattr(self, "consonant_list"):
            return
        def fill(widget: QListWidget, labels: Sequence[str]) -> None:
            current = widget.currentItem().data(Qt.UserRole) if widget.currentItem() else None
            widget.clear()
            for lab in labels:
                spec = self.setup.get_spec(lab)
                if spec.mode == "atomic":
                    detail = f"{('L' if spec.arm == 'left' else 'R')}{spec.position} · {spec.temporal}"
                elif spec.mode == "composite":
                    detail = " + ".join(str(x.get("ref", "?")) for x in spec.steps) or "empty"
                elif spec.mode == "raw": detail = "RAW"
                else: detail = "미매핑"
                item = QListWidgetItem(f"{lab}     {detail}")
                item.setData(Qt.UserRole, lab)
                widget.addItem(item)
                if lab == current: widget.setCurrentItem(item)
        fill(self.consonant_list, CONSONANTS)
        fill(self.vowel_list, VOWELS)

    def validate_design(self) -> None:
        compiler = HangulCompiler(self.setup)
        errors: List[str] = []
        for lab in CONSONANTS + VOWELS:
            try:
                compiler.compile_jamo(lab)
            except Exception as exc:
                errors.append(f"{lab}: {exc}")
        if errors:
            QMessageBox.warning(self, "검증 결과", f"오류 {len(errors)}개\n\n" + "\n".join(errors[:30]))
        else:
            QMessageBox.information(self, "검증 결과", "모든 자음과 모음이 정상적으로 컴파일됩니다.")

    # --------- serial ---------
    def refresh_ports(self) -> None:
        if not hasattr(self, "port_combo"):
            return
        self.port_combo.clear()
        ports = self.serial_ctl.list_ports()
        for dev, desc in ports:
            self.port_combo.addItem(f"{dev} · {desc}", dev)
        if not ports:
            self.port_combo.addItem("포트 없음 · DRY RUN", "")

    def toggle_serial(self) -> None:
        if self.serial_ctl.is_connected():
            self.serial_ctl.close(); self.connect_btn.setText("연결"); self.sidebar_status.setText("DRY RUN"); return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "COM", "COM 포트를 선택하세요."); return
        try:
            self.apply_hardware_settings()
            self.serial_ctl.connect(port, self.setup.baudrate)
            self.connect_btn.setText("연결 해제")
            self.sidebar_status.setText(f"CONNECTED · {port}")
            self.toast("Arduino 연결됨")
        except Exception as exc:
            QMessageBox.critical(self, "연결 실패", str(exc))

    def send_command(self, command: str) -> str:
        if len(command) > 560:
            raise RuntimeError(f"Command가 Arduino 수신 buffer에 비해 너무 깁니다 ({len(command)} chars). 입력을 줄여주세요.")
        wait_ack = self.ack_check.isChecked() if hasattr(self, "ack_check") else True
        ack = self.serial_ctl.send(command, wait_ack=wait_ack)
        self.toast(f"자극 전송 · {ack}")
        return ack

    def emergency_off(self) -> None:
        self.serial_ctl.emergency_off(); self.toast("모든 모터 OFF")

    def test_hardware_position(self, position: int) -> None:
        spec = JamoSpec(mode="atomic", arm=self.hw_arm.currentData(), position=position, temporal=self.hw_temporal.currentData())
        try:
            self.send_command(HangulCompiler.serialize_timeline(HangulCompiler(self.setup).atomic_timeline(spec)))
        except Exception as exc:
            QMessageBox.critical(self, "Hardware test", str(exc))

    # --------- simple test ---------
    def compile_simple(self) -> Optional[str]:
        self.sync_model_from_setup_controls()
        try:
            command, trace = HangulCompiler(self.setup).compile_text(self.simple_input.text())
            duration = HangulCompiler.estimate_duration_ms(command)
            self.simple_command.setPlainText(
                command + "\n\n" +
                "\n".join(f"t={x['onset_ms']} ms · {x['char']}  →  {x['command']}" for x in trace)
            )
            self.simple_summary.setText(f"{len(trace)}글자 · 예상 {duration} ms · command {len(command)} chars")
            return command
        except Exception as exc:
            self.simple_command.setPlainText(f"컴파일 오류: {exc}")
            self.simple_summary.setText("컴파일 실패")
            self.toast(str(exc), error=True)
            return None

    def play_simple(self) -> None:
        command = self.compile_simple()
        if command:
            try: self.send_command(command)
            except Exception as exc: QMessageBox.critical(self, "자극 오류", str(exc))

    # --------- voice backend ---------
    def choose_backend(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Voice backend 선택", str(APP_DIR), "Python (*.py)")
        if path: self.backend_edit.setText(path)

    def choose_syllable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Syllable XLSX 선택", str(APP_DIR), "Excel (*.xlsx)")
        if path:
            self.syllable_edit.setText(path)
            self.update_duration_estimate()

    def choose_voice_profiles(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "voice_profiles 폴더 선택", str(APP_DIR))
        if path: self.voice_profiles_edit.setText(path)

    def get_voice_backend(self):
        path = Path(self.backend_edit.text().strip())
        if not path.exists():
            raise RuntimeError(f"Voice backend 파일이 없습니다: {path}")
        if self.voice_backend is not None and Path(getattr(self.voice_backend, "__file__", "")) == path:
            return self.voice_backend
        spec = importlib.util.spec_from_file_location("hangul_voice_backend_dynamic", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Voice backend를 load할 수 없습니다.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # The legacy backend uses a module-global BASE_DIR. Redirect it to the
        # folder selected in this designer so existing profiles can be reused
        # without moving files.
        profile_dir = Path(self.voice_profiles_edit.text().strip()) if hasattr(self, "voice_profiles_edit") else APP_DIR / "voice_profiles"
        profile_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(module, "BASE_DIR"):
            module.BASE_DIR = profile_dir
        self.voice_backend = module
        self.voice_backend_path = path
        return module

    def check_voice_model(self) -> None:
        subject = self.subject_edit.text().strip()
        if not subject:
            QMessageBox.warning(self, "Subject", "Subject ID를 입력하세요."); return
        try:
            b = self.get_voice_backend()
            model = b.load_hangul_jamo_model(subject)
            profile_root = Path(self.voice_profiles_edit.text().strip()) if self.voice_profiles_edit.text().strip() else APP_DIR / "voice_profiles"
            possible = [
                profile_root / subject / "jamo_voice_model.joblib",
                profile_root / subject / "hangul_jamo_model.joblib",
                profile_root / subject / "learned_voice_model.joblib",
            ]
            msg = "사용 가능한 모델이 있습니다." if model is not None else "모델이 없습니다. 자모 퀴즈 전 calibration 또는 pooled 모델 생성이 필요합니다."
            msg += "\n\n" + "\n".join(str(p) for p in possible)
            QMessageBox.information(self, "Voice model", msg)
        except Exception as exc:
            QMessageBox.critical(self, "Voice backend 오류", str(exc))

    def build_pooled_model(self) -> None:
        subject = self.subject_edit.text().strip()
        if not subject:
            QMessageBox.warning(self, "Subject", "Subject ID를 입력하세요."); return
        try:
            b = self.get_voice_backend()
            bundle, path = b.train_hangul_jamo_model(subject, labels=b.ALL_JAMO_LABELS, include_pooled=True)
            QMessageBox.information(self, "Pooled model", f"생성 완료\n{path}\nSamples: {bundle.get('n_samples')}")
        except Exception as exc:
            QMessageBox.critical(self, "Pooled model 실패", str(exc))

    # --------- quiz ---------
    def build_quiz_labels(self) -> List[str]:
        qtype = self.quiz_type.currentData()
        compiler = HangulCompiler(self.setup)
        if qtype == "consonant": source = CONSONANTS
        elif qtype == "vowel": source = VOWELS
        elif qtype == "jamo_all": source = CONSONANTS + VOWELS
        else:
            source = load_syllables(Path(self.syllable_edit.text().strip()), self.syllable_limit.value())
        valid: List[str] = []
        for lab in source:
            try:
                if qtype == "syllable": compiler.compile_syllable(lab)
                else: compiler.compile_jamo(lab)
                valid.append(lab)
            except Exception:
                pass
        return valid

    def make_balanced_plan(self, labels: Sequence[str], n: int) -> List[str]:
        if not labels: return []
        plan: List[str] = []
        rng = random.Random(time.time_ns())
        while len(plan) < n:
            batch = list(labels); rng.shuffle(batch); plan.extend(batch)
        return plan[:n]

    def start_quiz(self) -> None:
        subject = self.subject_edit.text().strip()
        if not subject:
            QMessageBox.warning(self, "Subject", "Subject ID를 입력하세요."); return
        try:
            backend = self.get_voice_backend()
            labels = self.build_quiz_labels()
            if len(labels) < 2:
                raise RuntimeError("퀴즈에 사용할 수 있는 label이 2개 미만입니다. 디자인 매핑과 syllable 파일을 확인하세요.")
            if self.quiz_type.currentData() != "syllable" and backend.load_hangul_jamo_model(subject) is None:
                raise RuntimeError("이 subject의 자모 음성 모델이 없습니다. 모델 확인/pooled 모델 생성을 먼저 하세요.")
            self.quiz_labels = labels
            self.quiz_plan = self.make_balanced_plan(labels, self.quiz_trials.value())
            self.quiz_index = -1
            self.quiz_rows = []
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.quiz_csv_path = DATA_DIR / f"quiz_{subject}_{stamp}.csv"
            self.quiz_action.setEnabled(True)
            self.quiz_action.setText("첫 자극 시작 + 음성 듣기")
            self.quiz_instruction.setText("준비되었습니다. 버튼을 누르면 tactile stimulus와 음성 녹음이 시작됩니다.")
            self.quiz_feedback.setText(f"Labels: {len(labels)} · Trials: {len(self.quiz_plan)}")
            self.clear_candidates()
            self.next_quiz_trial()
        except Exception as exc:
            QMessageBox.critical(self, "퀴즈 시작 실패", str(exc))

    def next_quiz_trial(self) -> None:
        self.quiz_index += 1
        if self.quiz_index >= len(self.quiz_plan):
            self.quiz_action.setEnabled(False)
            acc = sum(int(r["correct"]) for r in self.quiz_rows) / max(1, len(self.quiz_rows))
            self.quiz_instruction.setText("퀴즈 완료")
            self.quiz_feedback.setText(f"Accuracy {acc*100:.1f}% · {self.quiz_csv_path}")
            return
        self.quiz_target = self.quiz_plan[self.quiz_index]
        compiler = HangulCompiler(self.setup)
        self.quiz_command = compiler.compile_syllable(self.quiz_target) if self.quiz_type.currentData() == "syllable" else compiler.compile_jamo(self.quiz_target)
        self.quiz_progress.setText(f"TRIAL {self.quiz_index + 1} / {len(self.quiz_plan)}")
        self.quiz_instruction.setText("자극을 느끼고 소리 내어 답해주세요.")
        self.quiz_feedback.setText("")
        self.quiz_action.setText("자극 시작 + 음성 듣기")
        self.quiz_action.setEnabled(True)
        self.quiz_manual.clear(); self.clear_candidates()

    def quiz_action_clicked(self) -> None:
        if self.quiz_index < 0 or self.quiz_index >= len(self.quiz_plan): return
        self.quiz_action.setEnabled(False)
        self.quiz_feedback.setText("자극 전송 중…")
        try:
            self.send_command(self.quiz_command)
            self.quiz_started_perf = time.perf_counter()
            self.start_voice_worker()
        except Exception as exc:
            self.quiz_feedback.setText(f"자극 실패: {exc}")
            self.quiz_action.setEnabled(True)

    def start_voice_worker(self) -> None:
        try:
            b = self.get_voice_backend()
            session_type = "syllable" if self.quiz_type.currentData() == "syllable" else "jamo"
            recorder_settings = dict(
                vad_level=2,
                speech_frames_required=2,
                pre_buffer_frames=20,
                max_wait_sec=8.0,
                max_record_sec=3.0,
                end_silence_sec=0.45,
                noise_calibration_sec=0.25,
                energy_multiplier=2.0,
                min_energy_rms=100.0,
                min_record_sec=0.15,
            )
            self.quiz_worker = b.TrialVoiceWorker(
                self.subject_edit.text().strip(),
                session_type,
                self.quiz_labels,
                recorder_settings,
                syllable_xlsx=self.syllable_edit.text().strip(),
                stt_model="small",
                wav_dir=DATA_DIR / "voice_wav" / self.subject_edit.text().strip(),
            )
            self.quiz_worker.status.connect(self.quiz_feedback.setText)
            self.quiz_worker.result_ready.connect(self.handle_voice_result)
            self.quiz_worker.start()
        except Exception as exc:
            self.quiz_feedback.setText(f"음성 시작 실패: {exc}")
            self.quiz_action.setEnabled(True)

    def extract_candidates(self, result: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        def add(x):
            if x is None: return
            if isinstance(x, dict): lab = x.get("label") or x.get("predicted_label")
            else: lab = x
            if lab is not None and str(lab).strip() and str(lab).strip() not in out: out.append(str(lab).strip())
        add(result.get("predicted_label")); add(result.get("second_label"))
        for key in ("top", "top_candidates", "candidates", "scores"):
            vals = result.get(key) or []
            for x in vals: add(x)
        if self.quiz_type.currentData() == "syllable":
            allowed = set(self.quiz_labels); out = [x for x in out if x in allowed]
        return out[:5]

    def handle_voice_result(self, result: Dict[str, Any]) -> None:
        if "error" in result:
            self.quiz_feedback.setText(f"음성 인식 실패: {result.get('message', result['error'])}")
            self.quiz_action.setText("다시 듣기")
            self.quiz_action.setEnabled(True)
            return
        self.current_voice_result = result
        candidates = self.extract_candidates(result)
        self.quiz_feedback.setText("음성 후보를 확인하고 실제 응답을 선택하세요.")
        self.show_candidates(candidates)

    def clear_candidates(self) -> None:
        clear_layout(self.candidate_layout)

    def show_candidates(self, labels: Sequence[str]) -> None:
        self.clear_candidates()
        for i, lab in enumerate(labels):
            b = QPushButton(f"{i+1}.  {lab}")
            b.setObjectName("HardwareButton")
            b.setMinimumHeight(70)
            b.clicked.connect(lambda _=False, x=lab: self.finalize_quiz_answer(x, manual=False))
            self.candidate_layout.addWidget(b, 0, i)

    def submit_manual_quiz(self) -> None:
        ans = self.quiz_manual.text().strip()
        if ans: self.finalize_quiz_answer(ans, manual=True)

    def finalize_quiz_answer(self, answer: str, manual: bool) -> None:
        correct = int(answer == self.quiz_target)
        elapsed_ms = (time.perf_counter() - self.quiz_started_perf) * 1000 if self.quiz_started_perf else ""
        result = getattr(self, "current_voice_result", {}) or {}
        row = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "app_version": APP_VERSION,
            "subject": self.subject_edit.text().strip(),
            "setup_name": self.setup.setup_name,
            "setup_hash": self.setup.stable_hash(),
            "setup_path": str(self.setup_path or ""),
            "quiz_type": self.quiz_type.currentData(),
            "trial_index": self.quiz_index + 1,
            "target": self.quiz_target,
            "response": answer,
            "manual_response": int(manual),
            "correct": correct,
            "command": self.quiz_command,
            "elapsed_ms": elapsed_ms,
            "voice_engine": result.get("engine", ""),
            "voice_wav_path": result.get("wav_path", ""),
            "voice_stt_raw": result.get("stt_raw", ""),
            "voice_stt_norm": result.get("stt_norm", ""),
            "voice_onset_rt_sec": result.get("voice_onset_rt_sec", ""),
            "top_candidates_json": json.dumps(result.get("top", result.get("top_candidates", [])), ensure_ascii=False),
        }
        self.quiz_rows.append(row)
        self.append_quiz_csv(row)
        self.clear_candidates()
        if correct:
            self.quiz_feedback.setText(f"정답  {self.quiz_target}")
            self.quiz_feedback.setStyleSheet("background:#EAF8EF;color:#147A3D;border-radius:16px;padding:12px;font-weight:700;")
        else:
            self.quiz_feedback.setText(f"오답 · 응답 {answer}  →  정답 {self.quiz_target}")
            self.quiz_feedback.setStyleSheet("background:#FFF0F0;color:#B3261E;border-radius:16px;padding:12px;font-weight:700;")
        self.quiz_action.setText("다음")
        self.quiz_action.setEnabled(True)
        try: self.quiz_action.clicked.disconnect()
        except Exception: pass
        self.quiz_action.clicked.connect(self.quiz_next_clicked)

    def quiz_next_clicked(self) -> None:
        try: self.quiz_action.clicked.disconnect()
        except Exception: pass
        self.quiz_action.clicked.connect(self.quiz_action_clicked)
        self.quiz_feedback.setStyleSheet("")
        self.next_quiz_trial()

    def append_quiz_csv(self, row: Dict[str, Any]) -> None:
        assert self.quiz_csv_path is not None
        exists = self.quiz_csv_path.exists()
        with open(self.quiz_csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists: w.writeheader()
            w.writerow(row)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.serial_ctl.emergency_off(); self.serial_ctl.close()
        if self.dirty:
            reply = QMessageBox.question(self, "종료", "저장하지 않은 디자인 변경사항이 있습니다. 종료할까요?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore(); return
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Hangul Tactile Designer")
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
