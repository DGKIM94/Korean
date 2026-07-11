"""
Tactile Consonant Learning Experiment App (prototype)
----------------------------------------------------
- 9-symbol direct spatial mapping learning task using Korean consonant-name responses
- 6 mapping layouts with balanced Latin square order
- Voice response classifier from pre-recorded training samples (20 per label recommended)
- Top-5 candidate buttons + manual text entry fallback
- Trial-and-error learning with feedback
- Stop criterion: recent 27 trials >= 25 correct OR 8 minutes elapsed
- Retention test: 18 trials without feedback

Dependencies:
    pip install PySide6 sounddevice soundfile numpy scipy scikit-learn joblib

Optional serial stimulation:
    pip install pyserial

Author: generated prototype for tactile Korean/forearm learning study
"""

from __future__ import annotations

import os
import sys
import csv
import json
import time
import math
import random
import queue
import wave
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import soundfile as sf
except Exception:
    sf = None

try:
    from scipy.io import wavfile
    from scipy.fftpack import dct
except Exception:
    wavfile = None
    dct = None

try:
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    import joblib
except Exception:
    Pipeline = None
    StandardScaler = None
    SVC = None
    train_test_split = None
    classification_report = None
    joblib = None

try:
    from PySide6.QtCore import Qt, QTimer, QThread, Signal
    from PySide6.QtWidgets import (
        QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QLineEdit, QFileDialog, QMessageBox, QComboBox,
        QSpinBox, QTextEdit, QGroupBox, QCheckBox, QScrollArea
    )
except Exception as e:
    print("PySide6 is required. Install with: pip install PySide6")
    raise

# -----------------------------------------------------------------------------
# Basic symbols and layouts
# -----------------------------------------------------------------------------

# Response labels shown to participants and used for voice-model training.
# The experiment now uses Korean consonant names rather than CV syllables.
SYMBOLS = ["기역", "니은", "디귿", "리을", "미음", "비읍", "시옷", "이응", "지읒"]
SYMBOL_TO_CONSONANT = {
    "기역": "ㄱ", "니은": "ㄴ", "디귿": "ㄷ", "리을": "ㄹ", "미음": "ㅁ",
    "비읍": "ㅂ", "시옷": "ㅅ", "이응": "ㅇ", "지읒": "ㅈ",
}
CONSONANT_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_CONSONANT.items()}
# Accept previous CV syllable labels as manual aliases, but store responses as consonant names.
SYLLABLE_TO_SYMBOL = {
    "가": "기역", "나": "니은", "다": "디귿", "라": "리을", "마": "미음",
    "바": "비읍", "사": "시옷", "아": "이응", "자": "지읒",
}
# Training-folder aliases. The current experiment uses consonant names
# (기역, 니은, ...), but older recordings may be stored in folders named
# by CV syllables (가, 나, ...) or jamo (ㄱ, ㄴ, ...). During model training
# all of them are converted to the consonant-name label.
LABEL_ALIASES = {label: [label] for label in SYMBOLS}
for syll, label in SYLLABLE_TO_SYMBOL.items():
    LABEL_ALIASES.setdefault(label, [label]).append(syll)
for cons, label in CONSONANT_TO_SYMBOL.items():
    LABEL_ALIASES.setdefault(label, [label]).append(cons)

# Logical visual position -> physical motor number on the hardware.
# Visual/logical grid:       Physical motor grid:
#   1 2 3                       3 2 1
#   4 5 6                       6 5 4
#   7 8 9                       9 8 7
LOGICAL_POS_TO_MOTOR_ID: Dict[int, int] = {
    1: 3, 2: 2, 3: 1,
    4: 6, 5: 5, 6: 4,
    7: 9, 8: 8, 9: 7,
}


# Logical grid positions are 1..9, interpreted as:
# Wrist:  1 2 3
#         4 5 6
# Elbow:  7 8 9
#
# IMPORTANT: The physical motor IDs on the current forearm array are reversed
# left-to-right within each row:
# Wrist:  3 2 1
#         6 5 4
# Elbow:  9 8 7
#
# Therefore, layouts below are defined in logical/visual position coordinates,
# and Stimulator.send_position() converts logical position -> physical motor ID.
# Each layout maps logical position -> response symbol.
LAYOUTS: Dict[str, Dict[int, str]] = {
    # C1: phone-like / wrist-origin canonical
    "C1_PhoneLike": {
        1: "기역", 2: "니은", 3: "디귿",
        4: "리을", 5: "미음", 6: "비읍",
        7: "시옷", 8: "이응", 9: "지읒",
    },
    # C2: keyboard-like / elbow-origin canonical
    "C2_KeyboardLike": {
        1: "시옷", 2: "이응", 3: "지읒",
        4: "리을", 5: "미음", 6: "비읍",
        7: "기역", 8: "니은", 9: "디귿",
    },
    # C3: medium-order A, preserved pairs: ㄱ-ㄴ, ㄷ-ㄹ, ㅁ-ㅂ, ㅅ-ㅇ
    # Revised to reduce repeated symbol-position overlaps across C3-C6.
    "C3_MediumA": {
        1: "니은", 2: "기역", 3: "지읒",
        4: "미음", 5: "비읍", 6: "이응",
        7: "시옷", 8: "리을", 9: "디귿",
    },
    # C4: medium-order B, preserved pairs: ㄴ-ㄷ, ㄹ-ㅁ, ㅂ-ㅅ, ㅇ-ㅈ
    # Preserved pair set remains non-overlapping with C3.
    "C4_MediumB": {
        1: "시옷", 2: "비읍", 3: "니은",
        4: "디귿", 5: "기역", 6: "리을",
        7: "미음", 8: "이응", 9: "지읒",
    },
    # C5: low-order A, preserved pair: ㄴ-ㄷ
    "C5_LowA": {
        1: "리을", 2: "이응", 3: "비읍",
        4: "기역", 5: "지읒", 6: "시옷",
        7: "니은", 8: "디귿", 9: "미음",
    },
    # C6: low-order B, preserved pair: ㄱ-ㄴ
    "C6_LowB": {
        1: "미음", 2: "디귿", 3: "이응",
        4: "비읍", 5: "리을", 6: "니은",
        7: "기역", 8: "지읒", 9: "시옷",
    },
}

ORDER_SCORE = {
    "C1_PhoneLike": 8,
    "C2_KeyboardLike": 8,
    "C3_MediumA": 4,
    "C4_MediumB": 4,
    "C5_LowA": 1,
    "C6_LowB": 1,
}

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

@dataclass
class ExperimentConfig:
    sample_rate: int = 16000
    record_seconds_training: float = 1.2
    record_seconds_response: float = 1.5
    stimulus_duration_ms: int = 150
    feedback_ms: int = 800
    iti_ms: int = 700
    learning_time_cap_sec: int = 8 * 60
    criterion_window: int = 27
    criterion_correct: int = 25
    retention_trials: int = 18
    training_samples_per_label: int = 20
    data_dir: str = "data"
    model_path: str = "model/consonant_name_svm.joblib"
    use_serial: bool = False
    serial_port: str = "COM3"
    serial_baud: int = 115200
    # Serial command format used by the previous forearm hardware app.
    # "at_slash": @<motor>/<duration_ms>  e.g., @3/300
    # "slash":    <motor>/<duration_ms>   e.g., 3/300
    # "equals":   <motor>=<intensity>     e.g., 3=255  (duration handled by firmware if supported)
    serial_command_mode: str = "at_slash"
    intensity: int = 255

# -----------------------------------------------------------------------------
# Balanced Latin square
# -----------------------------------------------------------------------------

def balanced_latin_square(items: List[str]) -> List[List[str]]:
    """Generate a balanced Latin square order.

    For even n, this returns n sequences. For odd n, it returns 2n sequences.
    Here n=6, so it is appropriate for six mapping conditions.
    """
    n = len(items)
    rows = []
    base = []
    for i in range(n):
        if i % 2 == 0:
            base.append(i // 2)
        else:
            base.append(n - 1 - i // 2)
    for r in range(n):
        row = [items[(idx + r) % n] for idx in base]
        rows.append(row)
    if n % 2 == 1:
        rows += [list(reversed(row)) for row in rows]
    return rows


def condition_order_for_subject(subject_id: int, layout_names: List[str]) -> List[str]:
    squares = balanced_latin_square(layout_names)
    return squares[(subject_id - 1) % len(squares)]

# -----------------------------------------------------------------------------
# Audio feature extraction and classifier
# -----------------------------------------------------------------------------

def _pre_emphasis(signal: np.ndarray, coeff: float = 0.97) -> np.ndarray:
    if len(signal) == 0:
        return signal
    return np.append(signal[0], signal[1:] - coeff * signal[:-1])


def _framesig(sig: np.ndarray, frame_len: int, frame_step: int) -> np.ndarray:
    slen = len(sig)
    if slen <= frame_len:
        num_frames = 1
    else:
        num_frames = 1 + int(np.ceil((slen - frame_len) / frame_step))
    pad_len = int((num_frames - 1) * frame_step + frame_len)
    zeros = np.zeros((pad_len - slen,))
    pad_sig = np.concatenate((sig, zeros))
    indices = np.tile(np.arange(0, frame_len), (num_frames, 1)) + \
        np.tile(np.arange(0, num_frames * frame_step, frame_step), (frame_len, 1)).T
    return pad_sig[indices.astype(np.int32, copy=False)]


def _mel_filterbank(nfilt: int, nfft: int, samplerate: int, lowfreq: int = 0, highfreq: Optional[int] = None) -> np.ndarray:
    highfreq = highfreq or samplerate // 2
    lowmel = 2595 * np.log10(1 + lowfreq / 700)
    highmel = 2595 * np.log10(1 + highfreq / 700)
    melpoints = np.linspace(lowmel, highmel, nfilt + 2)
    bin_hz = 700 * (10 ** (melpoints / 2595) - 1)
    bins = np.floor((nfft + 1) * bin_hz / samplerate).astype(int)
    fbank = np.zeros((nfilt, nfft // 2 + 1))
    for j in range(nfilt):
        for i in range(bins[j], bins[j + 1]):
            if bins[j + 1] != bins[j]:
                fbank[j, i] = (i - bins[j]) / (bins[j + 1] - bins[j])
        for i in range(bins[j + 1], bins[j + 2]):
            if bins[j + 2] != bins[j + 1]:
                fbank[j, i] = (bins[j + 2] - i) / (bins[j + 2] - bins[j + 1])
    return fbank


def mfcc_features(signal: np.ndarray, samplerate: int = 16000, numcep: int = 13, nfilt: int = 26, nfft: int = 512) -> np.ndarray:
    """Small self-contained MFCC summary: mean/std/min/max over frames."""
    if dct is None:
        raise RuntimeError("scipy is required for MFCC extraction")
    sig = signal.astype(np.float32)
    if sig.ndim > 1:
        sig = sig.mean(axis=1)
    if np.max(np.abs(sig)) > 0:
        sig = sig / np.max(np.abs(sig))
    sig = trim_silence(sig, samplerate)
    sig = _pre_emphasis(sig)
    frame_len = int(0.025 * samplerate)
    frame_step = int(0.010 * samplerate)
    frames = _framesig(sig, frame_len, frame_step)
    frames *= np.hamming(frame_len)
    mag_frames = np.absolute(np.fft.rfft(frames, nfft))
    pow_frames = ((1.0 / nfft) * (mag_frames ** 2))
    fbank = _mel_filterbank(nfilt, nfft, samplerate)
    feat = np.dot(pow_frames, fbank.T)
    feat = np.where(feat == 0, np.finfo(float).eps, feat)
    feat = np.log(feat)
    cep = dct(feat, type=2, axis=1, norm='ortho')[:, :numcep]
    # Add simple deltas
    if len(cep) >= 3:
        delta = np.gradient(cep, axis=0)
    else:
        delta = np.zeros_like(cep)
    allcep = np.concatenate([cep, delta], axis=1)
    summary = np.concatenate([
        np.mean(allcep, axis=0),
        np.std(allcep, axis=0),
        np.min(allcep, axis=0),
        np.max(allcep, axis=0),
    ])
    return summary.astype(np.float32)


def trim_silence(sig: np.ndarray, samplerate: int, threshold_ratio: float = 0.08, pad_ms: int = 80) -> np.ndarray:
    if len(sig) == 0:
        return sig
    abs_sig = np.abs(sig)
    maxv = np.max(abs_sig)
    if maxv <= 1e-8:
        return sig
    thresh = maxv * threshold_ratio
    idx = np.where(abs_sig > thresh)[0]
    if len(idx) == 0:
        return sig
    pad = int(samplerate * pad_ms / 1000)
    start = max(0, idx[0] - pad)
    end = min(len(sig), idx[-1] + pad)
    return sig[start:end]


def voice_onset_time(sig: np.ndarray, samplerate: int, threshold_ratio: float = 0.12, min_ms: int = 20) -> Optional[float]:
    """Return onset time in seconds within response recording, based on energy threshold."""
    if len(sig) == 0:
        return None
    if sig.ndim > 1:
        sig = sig.mean(axis=1)
    abs_sig = np.abs(sig.astype(np.float32))
    maxv = np.max(abs_sig)
    if maxv <= 1e-8:
        return None
    thresh = maxv * threshold_ratio
    win = max(1, int(samplerate * min_ms / 1000))
    above = abs_sig > thresh
    # require a small consecutive run
    count = 0
    for i, v in enumerate(above):
        count = count + 1 if v else 0
        if count >= win:
            return max(0, i - win + 1) / samplerate
    return None


class ConsonantClassifier:
    def __init__(self, cfg: ExperimentConfig):
        self.cfg = cfg
        self.model = None
        self.labels: List[str] = []

    def train_from_folder(self, train_dir: Path) -> str:
        if Pipeline is None:
            raise RuntimeError("scikit-learn/joblib are required. pip install scikit-learn joblib")

        # Accept several folder names for backward compatibility.
        # Priority: selected train_dir -> training_wav -> training_wave -> data/training_wav.
        candidate_roots = []
        for root in [Path(train_dir), Path("training_wav"), Path("training_wave"), Path("data") / "training_wav"]:
            if root not in candidate_roots and root.exists():
                candidate_roots.append(root)
        if not candidate_roots:
            candidate_roots = [Path(train_dir)]

        X, y = [], []
        counts = {label: 0 for label in SYMBOLS}

        for label in SYMBOLS:
            aliases = LABEL_ALIASES.get(label, [label])
            seen_files = set()
            for root in candidate_roots:
                for alias in aliases:
                    lab_dir = root / alias
                    if not lab_dir.exists():
                        continue
                    for wav in sorted(lab_dir.glob("*.wav")):
                        if wav.resolve() in seen_files:
                            continue
                        seen_files.add(wav.resolve())
                        sr, sig = wavfile.read(str(wav))
                        X.append(mfcc_features(sig, sr))
                        y.append(label)
                        counts[label] += 1

        missing = [f"{lab}:{counts[lab]}" for lab in SYMBOLS if counts[lab] == 0]
        if len(X) < len(SYMBOLS) * 3:
            raise RuntimeError(
                "Not enough training files. "
                f"Found {len(X)} wav files. Counts: {counts}. "
                "Expected folders can be named 기역/니은/... or legacy 가/나/... under "
                "training_wav, training_wave, or data/training_wav."
            )
        if any(counts[lab] == 0 for lab in SYMBOLS):
            raise RuntimeError(f"Some labels have no training samples: {missing}")

        self.labels = sorted(set(y), key=SYMBOLS.index)
        clf = Pipeline([
            ("scaler", StandardScaler()),
            ("svc", SVC(kernel="rbf", C=10, gamma="scale", probability=True, class_weight="balanced")),
        ])
        X = np.vstack(X)
        y_arr = np.array(y)
        report = ""
        if len(set(y)) >= 2 and len(y) >= 30:
            try:
                Xtr, Xte, ytr, yte = train_test_split(X, y_arr, test_size=0.2, random_state=42, stratify=y_arr)
                clf.fit(Xtr, ytr)
                pred = clf.predict(Xte)
                report = classification_report(yte, pred, labels=self.labels, zero_division=0)
            except Exception as e:
                report = f"Validation skipped: {e}"
                clf.fit(X, y_arr)
        else:
            clf.fit(X, y_arr)
        # Fit final on all data
        clf.fit(X, y_arr)
        self.model = clf
        Path(self.cfg.model_path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "labels": self.labels, "cfg": asdict(self.cfg)}, self.cfg.model_path)
        # Also write a compatibility copy under data/model if the main path is model/.
        compat_path = Path("data/model/consonant_name_svm.joblib")
        if compat_path != Path(self.cfg.model_path):
            compat_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump({"model": self.model, "labels": self.labels, "cfg": asdict(self.cfg)}, compat_path)
        report = (report or "") + "\nTraining sample counts: " + str(counts)
        return report

    def load(self) -> bool:
        if joblib is None:
            return False
        # Accept both the current model path and older/generated locations.
        candidates = [
            Path(self.cfg.model_path),
            Path("data/model/consonant_name_svm.joblib"),
            Path("model/consonant_name_svm.joblib"),
        ]
        for p in candidates:
            if not p.exists():
                continue
            obj = joblib.load(str(p))
            if isinstance(obj, dict) and "model" in obj:
                self.model = obj["model"]
                self.labels = obj.get("labels", SYMBOLS)
                return True
        return False

    def predict_topk(self, sig: np.ndarray, sr: int, k: int = 5) -> List[Tuple[str, float]]:
        if self.model is None:
            return []
        feat = mfcc_features(sig, sr).reshape(1, -1)
        if hasattr(self.model, "predict_proba"):
            probs = self.model.predict_proba(feat)[0]
            classes = list(self.model.classes_)
            pairs = sorted(zip(classes, probs), key=lambda x: x[1], reverse=True)[:k]
            return [(str(a), float(b)) for a, b in pairs]
        pred = self.model.predict(feat)[0]
        return [(str(pred), 1.0)]

# -----------------------------------------------------------------------------
# Simple stimulation backend placeholder
# -----------------------------------------------------------------------------

class Stimulator:
    """Serial stimulation backend for the forearm motor array.

    The experiment uses logical/visual grid positions 1..9, but the physical
    motor numbering is:
        3 2 1
        6 5 4
        9 8 7

    send_position(pos) converts logical position to physical motor ID before
    sending a serial command. Default command mode is '@<motor>/<duration_ms>',
    matching the previous forearm app convention noted in the voice-RT project.
    """
    def __init__(self, cfg: ExperimentConfig):
        self.cfg = cfg
        self.ser = None
        if cfg.use_serial:
            try:
                import serial
                self.ser = serial.Serial(cfg.serial_port, cfg.serial_baud, timeout=1)
            except Exception as e:
                print(f"Serial open failed: {e}")
                self.ser = None

    def _make_command(self, motor_id: int) -> str:
        mode = self.cfg.serial_command_mode
        dur = self.cfg.stimulus_duration_ms
        if mode == "at_slash":
            return f"@{motor_id}/{dur}\n"
        if mode == "slash":
            return f"{motor_id}/{dur}\n"
        if mode == "equals":
            return f"{motor_id}={self.cfg.intensity}\n"
        # fallback: previous simple slash command
        return f"{motor_id}/{dur}\n"

    def send_position(self, pos: int):
        motor_id = LOGICAL_POS_TO_MOTOR_ID.get(pos, pos)
        cmd = self._make_command(motor_id)
        # Motor/logical mapping is intentionally hidden from the participant UI.
        # print(f"STIM logical_pos={pos} -> motor={motor_id}: {cmd.strip()}")
        if self.ser:
            self.ser.write(cmd.encode("utf-8"))

    def close(self):
        if self.ser:
            self.ser.close()

# -----------------------------------------------------------------------------
# Experiment state and logging
# -----------------------------------------------------------------------------

@dataclass
class TrialRecord:
    subject_id: int
    session_id: str
    condition_index: int
    condition_name: str
    condition_score: int
    phase: str  # learning or retention
    trial_global: int
    trial_in_condition: int
    mini_block: int
    position: int
    motor_id: int
    correct_symbol: str
    correct_consonant: str
    response_symbol: str
    response_source: str
    is_correct: int
    voice_onset_rt_sec: Optional[float]
    response_confirm_rt_sec: Optional[float]
    top5_json: str
    timestamp: float


# -----------------------------------------------------------------------------
# Voice worker: starts listening immediately after tactile stimulus is sent
# -----------------------------------------------------------------------------

class VoiceResponseWorker(QThread):
    result = Signal(dict)
    status = Signal(str)

    def __init__(self, cfg: ExperimentConfig, classifier: ConsonantClassifier, wav_dir: Path, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.classifier = classifier
        self.wav_dir = wav_dir
        self.wav_dir.mkdir(parents=True, exist_ok=True)

    def run(self):
        try:
            if sd is None:
                self.result.emit({"error": "sounddevice is not installed"})
                return
            sr = self.cfg.sample_rate
            block_ms = 30
            block_size = int(sr * block_ms / 1000)
            max_wait_sec = 8.0
            max_record_sec = 3.0
            noise_sec = 0.25
            end_silence_sec = 0.45
            min_record_sec = 0.15
            energy_multiplier = 2.0
            min_energy_rms = 100.0

            q = queue.Queue()
            def callback(indata, frames, time_info, status):
                q.put(indata.copy())

            frames = []
            prebuf = []
            noise_vals = []
            triggered = False
            speech_count = 0
            silence_count = 0
            start_t = time.perf_counter()
            noise_end = start_t + noise_sec
            voice_t = None
            threshold = None
            self.status.emit("Listening...")
            with sd.InputStream(samplerate=sr, channels=1, dtype='float32', blocksize=block_size, callback=callback):
                while True:
                    now = time.perf_counter()
                    if not triggered and now - start_t > max_wait_sec:
                        self.result.emit({"error": "no_voice", "message": "No voice detected"})
                        return
                    if triggered and now - voice_t > max_record_sec:
                        break
                    try:
                        frame = q.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    x = frame[:,0].astype(np.float32)
                    rms = float(np.sqrt(np.mean(x*x) + 1e-8))
                    if not triggered and now < noise_end:
                        noise_vals.append(rms)
                        prebuf.append(x)
                        if len(prebuf) > 20:
                            prebuf.pop(0)
                        continue
                    if threshold is None:
                        noise = float(np.median(noise_vals)) if noise_vals else 0.0
                        threshold = max(min_energy_rms / 32768.0, noise * energy_multiplier)
                    is_speech = rms >= threshold
                    if not triggered:
                        prebuf.append(x)
                        if len(prebuf) > 20:
                            prebuf.pop(0)
                        if is_speech:
                            speech_count += 1
                        else:
                            speech_count = 0
                        if speech_count >= 2:
                            triggered = True
                            voice_t = time.perf_counter()
                            frames.extend(prebuf)
                            frames.append(x)
                    else:
                        frames.append(x)
                        if is_speech:
                            silence_count = 0
                        else:
                            silence_count += 1
                        dur = len(frames) * block_ms / 1000.0
                        if dur >= min_record_sec and silence_count >= int(end_silence_sec*1000/block_ms):
                            break
            if not frames or voice_t is None:
                self.result.emit({"error": "no_voice", "message": "No voice detected"})
                return
            sig = np.concatenate(frames).astype(np.float32)
            voice_rt = voice_t - start_t
            wav_path = self.wav_dir / f"trial_voice_{int(time.time()*1000)}.wav"
            if sf is not None:
                sf.write(str(wav_path), sig, sr)
            top5 = self.classifier.predict_topk(sig, sr, k=5)
            self.result.emit({
                "top5": top5,
                "voice_onset_rt_sec": voice_rt,
                "wav_path": str(wav_path),
                "recorded_duration_sec": len(sig)/sr,
                "noise_threshold": threshold,
            })
        except Exception as e:
            self.result.emit({"error": "exception", "message": str(e)})

# -----------------------------------------------------------------------------
# GUI
# -----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = ExperimentConfig()
        self.classifier = ConsonantClassifier(self.cfg)
        self.stimulator = None
        self.session_id = time.strftime("%Y%m%d_%H%M%S")
        self.subject_id = 1
        self.condition_order: List[str] = []
        self.current_condition_idx = -1
        self.current_condition_name = ""
        self.current_layout: Dict[int, str] = {}
        self.learning_start_time = 0.0
        self.phase = "idle"  # idle, learning, retention
        self.ui_state = "idle"  # ready, listening, answer, feedback
        self.trial_in_condition = 0
        self.trial_global = 0
        self.current_position = None
        self.current_correct = None
        self.current_motor_id = None
        self.current_top5: List[Tuple[str, float]] = []
        self.current_voice_result = None
        self.pending_trial_start = 0.0
        self.records: List[TrialRecord] = []
        self.recent_correct: List[int] = []
        self.retention_queue: List[int] = []
        self.learning_positions_queue: List[int] = []
        self.retention_started_at_trial = 0
        self.voice_worker = None

        self.data_dir = Path(self.cfg.data_dir)
        self.data_dir.mkdir(exist_ok=True)
        # Prefer existing training folders for backward compatibility.
        if Path("training_wav").exists():
            self.train_dir = Path("training_wav")
        elif Path("training_wave").exists():
            self.train_dir = Path("training_wave")
        else:
            self.train_dir = self.data_dir / "training_wav"
        self.train_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.voice_dir = self.data_dir / "trial_voice_wav" / self.session_id
        self.voice_dir.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        if self.classifier.load():
            self.log("Loaded existing classifier model.")
        else:
            self.log("No trained model loaded. Record samples and train first.")

    # ---------------- UI setup ----------------
    def _build_ui(self):
        """Compact participant-facing UI.

        The Latin-square order and mapping names are generated internally and
        written to the log/CSV, but are not displayed prominently to the participant.
        This avoids layout clipping and prevents map/condition hints.
        """
        self.setWindowTitle("Tactile Consonant Learning Experiment - Voice RT UI")
        self.resize(1100, 780)
        self.setMinimumSize(900, 650)
        self.setStyleSheet("""
            QLabel { font-size: 14px; }
            QGroupBox { font-size: 15px; font-weight: bold; margin-top: 6px; }
            QPushButton { font-size: 15px; padding: 7px 10px; min-height: 32px; }
            QLineEdit, QComboBox, QSpinBox { font-size: 14px; min-height: 28px; }
            QTextEdit { font-size: 12px; }
        """)

        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(outer)
        self.setCentralWidget(scroll)

        # Subject row. Latin-square order is internal only.
        top = QHBoxLayout()
        top.setSpacing(8)
        outer_layout.addLayout(top)
        top.addWidget(QLabel("Subject ID:"))
        self.subject_spin = QSpinBox()
        self.subject_spin.setRange(1, 999)
        self.subject_spin.setValue(1)
        self.subject_spin.setMaximumWidth(90)
        self.subject_spin.valueChanged.connect(lambda _v: self.make_order(silent=True))
        top.addWidget(self.subject_spin)
        self.subject_order_note = QLabel("Resume supported: saved CSV will be detected")
        self.subject_order_note.setStyleSheet("color:#555;")
        top.addWidget(self.subject_order_note)
        top.addStretch(1)

        # Hardware controls in two compact rows.
        serial_box = QGroupBox("Hardware / Serial")
        outer_layout.addWidget(serial_box)
        sgrid = QGridLayout(serial_box)
        sgrid.setContentsMargins(8, 8, 8, 8)
        sgrid.setHorizontalSpacing(8)
        sgrid.setVerticalSpacing(5)
        self.use_serial_check = QCheckBox("Use serial")
        sgrid.addWidget(self.use_serial_check, 0, 0)
        self.port_combo = QComboBox()
        sgrid.addWidget(self.port_combo, 0, 1, 1, 2)
        self.btn_refresh_ports = QPushButton("Refresh")
        self.btn_refresh_ports.clicked.connect(self.refresh_ports)
        sgrid.addWidget(self.btn_refresh_ports, 0, 3)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_serial)
        sgrid.addWidget(self.btn_connect, 0, 4)
        sgrid.addWidget(QLabel("Mode:"), 0, 5)
        self.serial_mode_combo = QComboBox()
        self.serial_mode_combo.addItems(["at_slash", "slash", "equals"])
        self.serial_mode_combo.setCurrentText("at_slash")
        self.serial_mode_combo.setMaximumWidth(130)
        sgrid.addWidget(self.serial_mode_combo, 0, 6)
        self.refresh_ports()

        # Voice model training.
        train_box = QGroupBox("Voice model training")
        outer_layout.addWidget(train_box)
        train_layout = QHBoxLayout(train_box)
        train_layout.setContentsMargins(8, 8, 8, 8)
        train_layout.setSpacing(8)
        train_layout.addWidget(QLabel("Label:"))
        self.train_label_combo = QComboBox()
        self.train_label_combo.addItems(SYMBOLS)
        self.train_label_combo.setMaximumWidth(120)
        train_layout.addWidget(self.train_label_combo)
        self.btn_record_sample = QPushButton("Record one")
        self.btn_record_sample.clicked.connect(self.record_training_sample)
        train_layout.addWidget(self.btn_record_sample)
        self.btn_record_batch = QPushButton("Record 20")
        self.btn_record_batch.clicked.connect(self.record_training_batch)
        train_layout.addWidget(self.btn_record_batch)
        self.btn_train = QPushButton("Train model")
        self.btn_train.clicked.connect(self.train_model)
        train_layout.addWidget(self.btn_train)
        train_layout.addStretch(1)

        # Experiment controls.
        exp_box = QGroupBox("Experiment")
        outer_layout.addWidget(exp_box)
        exp_layout = QHBoxLayout(exp_box)
        exp_layout.setContentsMargins(8, 8, 8, 8)
        exp_layout.setSpacing(8)
        self.btn_start_condition = QPushButton("Start experiment")
        self.btn_start_condition.setMinimumHeight(46)
        self.btn_start_condition.clicked.connect(self.start_next_condition)
        exp_layout.addWidget(self.btn_start_condition)
        self.stim_button = QPushButton("STIMULUS")
        self.stim_button.setMinimumHeight(58)
        self.stim_button.setStyleSheet(
            "font-size:20px; font-weight:bold; background-color:#3E3A7A; "
            "color:white; border-radius:12px; padding:12px;"
        )
        self.stim_button.clicked.connect(self.on_stimulus_or_next)
        self.stim_button.setEnabled(False)
        exp_layout.addWidget(self.stim_button, stretch=1)

        self.condition_label = QLabel("Condition: -")
        self.condition_label.setStyleSheet("font-size:17px; font-weight:bold; padding:4px;")
        outer_layout.addWidget(self.condition_label)
        self.status_label = QLabel("Status: idle")
        self.status_label.setStyleSheet("font-size:17px; font-weight:bold; padding:4px;")
        outer_layout.addWidget(self.status_label)
        self.feedback_label = QLabel("Start experiment, then press STIMULUS. Voice detection starts when the stimulus is sent.")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet(
            "font-size:15px; padding:8px; border-radius:8px; background:#F2F2F2; color:#222;"
        )
        outer_layout.addWidget(self.feedback_label)

        # Candidate buttons: no QGroupBox title to avoid clipping on small screens.
        cand_panel = QWidget()
        outer_layout.addWidget(cand_panel)
        cand_layout = QVBoxLayout(cand_panel)
        cand_layout.setContentsMargins(6, 4, 6, 4)
        cand_layout.setSpacing(5)
        cand_title = QLabel("Top-5 후보 선택 / 직접 입력")
        cand_title.setStyleSheet("font-size:15px; font-weight:bold; padding:2px;")
        cand_layout.addWidget(cand_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        cand_layout.addLayout(grid)
        self.candidate_buttons = []
        # 3 buttons on the first row and 2 buttons on the second row to avoid horizontal clipping.
        positions = [(0,0), (0,1), (0,2), (1,0), (1,1)]
        for i in range(5):
            b = QPushButton(f"{i+1}. -")
            b.setMinimumHeight(48)
            b.setStyleSheet(self.candidate_button_base_style())
            b.setEnabled(False)
            b.clicked.connect(lambda checked=False, idx=i: self.submit_candidate(idx))
            self.candidate_buttons.append(b)
            r, c = positions[i]
            grid.addWidget(b, r, c)
        manual_row = QHBoxLayout()
        manual_row.setSpacing(6)
        cand_layout.addLayout(manual_row)
        manual_label = QLabel("Manual")
        manual_label.setMaximumWidth(55)
        manual_row.addWidget(manual_label)
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText("후보에 없으면 입력: 기역/니은/디귿/리을/미음/비읍/시옷/이응/지읒 또는 ㄱ/ㄴ/...")
        self.manual_input.returnPressed.connect(self.submit_manual)
        manual_row.addWidget(self.manual_input, stretch=1)
        self.btn_submit_manual = QPushButton("Submit")
        self.btn_submit_manual.setMinimumHeight(42)
        self.btn_submit_manual.clicked.connect(self.submit_manual)
        manual_row.addWidget(self.btn_submit_manual)

        # Internal debug log is hidden by default. CSV is saved automatically after every trial.
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(60)
        self.log_text.hide()
        outer_layout.addWidget(self.log_text)

        self.make_order(silent=True)

    # ---------------- Utility ----------------
    def log(self, msg: str):
        t = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{t}] {msg}")
        print(msg)

    def update_status(self, msg: str):
        self.status_label.setText(f"Status: {msg}")
        self.log(msg)

    def refresh_ports(self):
        self.port_combo.clear()
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            for p in ports:
                self.port_combo.addItem(f"{p.device} - {p.description}", p.device)
            if not ports:
                self.port_combo.addItem("No ports", None)
        except Exception:
            self.port_combo.addItem("pyserial not installed", None)

    def toggle_serial(self):
        if self.stimulator and self.stimulator.ser:
            self.stimulator.close(); self.stimulator = None
            self.btn_connect.setText("Connect")
            self.update_status("Serial disconnected")
            return
        self.cfg.use_serial = self.use_serial_check.isChecked()
        self.cfg.serial_command_mode = self.serial_mode_combo.currentText()
        port = self.port_combo.currentData()
        if self.cfg.use_serial and port:
            self.cfg.serial_port = str(port)
        self.stimulator = Stimulator(self.cfg)
        if self.cfg.use_serial and self.stimulator.ser:
            self.btn_connect.setText("Disconnect")
            self.update_status(f"Serial connected: {self.cfg.serial_port}")
        else:
            self.update_status("Serial simulation mode")

    def ensure_stimulator(self):
        self.cfg.use_serial = self.use_serial_check.isChecked()
        self.cfg.serial_command_mode = self.serial_mode_combo.currentText()
        port = self.port_combo.currentData()
        if port:
            self.cfg.serial_port = str(port)
        if self.stimulator is None:
            self.stimulator = Stimulator(self.cfg)

    def make_order(self, silent: bool = False):
        """Generate the balanced Latin-square condition order internally.

        The order is intentionally not shown in the participant-facing UI; it is
        only logged and saved in trial records through condition_index/name.
        """
        self.subject_id = self.subject_spin.value()
        names = list(LAYOUTS.keys())
        self.condition_order = condition_order_for_subject(self.subject_id, names)
        self.current_condition_idx = -1
        if not silent:
            self.log(f"Subject {self.subject_id} internal condition order generated.")
        else:
            self.log(f"Subject {self.subject_id} internal condition order ready.")

    def candidate_button_base_style(self):
        return (
            "font-size:18px; font-weight:bold; border:2px solid #3E3A7A; "
            "border-radius:8px; background:white; color:#222; padding:4px;"
        )

    def candidate_button_selected_wrong_style(self):
        return (
            "font-size:18px; font-weight:bold; border:3px solid #B00020; "
            "border-radius:8px; background:#F8D7DA; color:#7A0014; padding:4px;"
        )

    def candidate_button_correct_style(self):
        return (
            "font-size:18px; font-weight:bold; border:3px solid #0B7A0B; "
            "border-radius:8px; background:#DFF5E1; color:#075C07; padding:4px;"
        )

    def set_feedback_neutral(self, text):
        self.feedback_label.setStyleSheet(
            "font-size:15px; padding:8px; border-radius:8px; "
            "background:#F2F2F2; color:#222;"
        )
        self.feedback_label.setText(str(text))

    def set_feedback_correct(self, text):
        self.feedback_label.setStyleSheet(
            "font-size:22px; font-weight:bold; padding:12px; border-radius:10px; "
            "background:#DFF5E1; color:#075C07; border:2px solid #1F9D45;"
        )
        self.feedback_label.setText("✅ " + str(text))

    def set_feedback_wrong(self, text):
        self.feedback_label.setStyleSheet(
            "font-size:22px; font-weight:bold; padding:12px; border-radius:10px; "
            "background:#F8D7DA; color:#7A0014; border:2px solid #D64545;"
        )
        self.feedback_label.setText("❌ " + str(text))

    def mark_candidate_buttons_after_answer(self, response):
        correct = self.current_correct
        for b in self.candidate_buttons:
            label_text = b.text()
            # Reset disabled buttons to a pale style first.
            b.setStyleSheet(self.candidate_button_base_style())
            # Candidate text format is usually "1. 기역 (0.84)".
            if correct and correct in label_text:
                b.setStyleSheet(self.candidate_button_correct_style())
            if response and response in label_text and response != correct:
                b.setStyleSheet(self.candidate_button_selected_wrong_style())

    def clear_candidates(self):
        for b in self.candidate_buttons:
            b.setText("-")
            b.setStyleSheet(self.candidate_button_base_style())
            b.setEnabled(False)
        self.manual_input.clear()

    # ---------------- Audio training ----------------
    def _record_audio_fixed(self, seconds: float) -> Tuple[np.ndarray, int]:
        if sd is None:
            raise RuntimeError("sounddevice is not installed")
        sr = self.cfg.sample_rate
        self.log(f"Recording {seconds:.1f}s...")
        audio = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="float32")
        sd.wait()
        return audio[:,0].copy(), sr

    def record_training_sample(self):
        label = self.train_label_combo.currentText()
        try:
            sig, sr = self._record_audio_fixed(self.cfg.record_seconds_training)
            lab_dir = self.train_dir / label; lab_dir.mkdir(parents=True, exist_ok=True)
            idx = len(list(lab_dir.glob("*.wav"))) + 1
            out = lab_dir / f"{label}_{idx:03d}.wav"
            if sf is None:
                raise RuntimeError("soundfile is required to save wav. pip install soundfile")
            sf.write(str(out), sig, sr)
            self.log(f"Saved: {out}")
        except Exception as e:
            QMessageBox.critical(self, "Record error", str(e))

    def record_training_batch(self):
        label = self.train_label_combo.currentText()
        n = self.cfg.training_samples_per_label
        QMessageBox.information(self, "Batch recording", f"{label}를 {n}번 녹음합니다. 각 녹음 전 버튼을 누른 뒤 바로 발화하세요.")
        for i in range(n):
            ok = QMessageBox.question(self, "Next sample", f"{label} sample {i+1}/{n} 녹음할까요?")
            if ok != QMessageBox.Yes:
                break
            self.record_training_sample()

    def train_model(self):
        try:
            report = self.classifier.train_from_folder(self.train_dir)
            self.log("Model trained.")
            self.log(report)
            QMessageBox.information(self, "Training complete", "Model trained. See log for validation report.")
        except Exception as e:
            QMessageBox.critical(self, "Training error", str(e))


    # ---------------- Resume helpers ----------------
    def _csv_to_record(self, row: dict) -> TrialRecord:
        """Convert a saved CSV row into TrialRecord, tolerating old files."""
        def _int(key, default=0):
            try:
                v = row.get(key, default)
                if v in [None, ""]:
                    return int(default)
                return int(float(v))
            except Exception:
                return int(default)
        def _float_or_none(key):
            try:
                v = row.get(key, "")
                if v in [None, ""]:
                    return None
                return float(v)
            except Exception:
                return None
        return TrialRecord(
            subject_id=_int("subject_id", self.subject_spin.value()),
            session_id=str(row.get("session_id", self.session_id)),
            condition_index=_int("condition_index", 0),
            condition_name=str(row.get("condition_name", "")),
            condition_score=_int("condition_score", -1),
            phase=str(row.get("phase", "learning")),
            trial_global=_int("trial_global", 0),
            trial_in_condition=_int("trial_in_condition", 0),
            mini_block=_int("mini_block", 0),
            position=_int("position", 0),
            motor_id=_int("motor_id", 0),
            correct_symbol=str(row.get("correct_symbol", "")),
            correct_consonant=str(row.get("correct_consonant", "")),
            response_symbol=str(row.get("response_symbol", "")),
            response_source=str(row.get("response_source", "")),
            is_correct=_int("is_correct", 0),
            voice_onset_rt_sec=_float_or_none("voice_onset_rt_sec"),
            response_confirm_rt_sec=_float_or_none("response_confirm_rt_sec"),
            top5_json=str(row.get("top5_json", "")),
            timestamp=float(row.get("timestamp", time.time()) or time.time()),
        )

    def latest_log_for_subject(self, subject_id: int) -> Optional[Path]:
        pattern = f"subject_{int(subject_id):03d}_*.csv"
        files = sorted(self.log_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def try_resume_from_saved_log(self) -> bool:
        """Load the latest CSV for the subject and restore progress.

        This uses only the CSV already saved after each trial, so it can resume
        even if the previous run ended unexpectedly and no separate state file exists.
        """
        if self.records:
            return False
        subject = self.subject_spin.value()
        latest = self.latest_log_for_subject(subject)
        if latest is None:
            return False
        reply = QMessageBox.question(
            self,
            "Resume saved experiment?",
            f"저장된 실험 파일을 찾았습니다.\n\n{latest}\n\n이 파일에서 이어서 진행할까요?\n\nNo를 누르면 새 세션으로 시작합니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        try:
            with open(latest, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                QMessageBox.warning(self, "Resume failed", "CSV 파일은 찾았지만 row가 없습니다.")
                return False
            loaded = [self._csv_to_record(r) for r in rows]
            loaded = [r for r in loaded if r.condition_index > 0 and r.condition_name]
            if not loaded:
                QMessageBox.warning(self, "Resume failed", "유효한 trial row를 찾지 못했습니다.")
                return False
            self.records = loaded
            self.session_id = loaded[0].session_id or latest.stem.replace(f"subject_{subject:03d}_", "")
            self.voice_dir = self.data_dir / "trial_voice_wav" / self.session_id
            self.voice_dir.mkdir(parents=True, exist_ok=True)
            self.make_order(silent=True)
            self.trial_global = max(r.trial_global for r in self.records)
            self.restore_progress_from_records()
            self.log(f"Resumed from saved CSV: {latest}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Resume error", str(e))
            return False

    def restore_progress_from_records(self):
        """Restore current block/phase from loaded TrialRecord rows."""
        if not self.records:
            return
        # Sort records by original global trial index just in case.
        self.records.sort(key=lambda r: (r.trial_global, r.timestamp))
        last = self.records[-1]
        last_cond_idx0 = max(0, int(last.condition_index) - 1)
        last_cond_recs = [r for r in self.records if int(r.condition_index) == int(last.condition_index)]
        retention_recs = [r for r in last_cond_recs if r.phase == "retention"]
        learning_recs = [r for r in last_cond_recs if r.phase == "learning"]
        retention_complete = len(retention_recs) >= self.cfg.retention_trials

        if retention_complete:
            # Last condition is already complete. Set idle so Start continues to the next block.
            self.current_condition_idx = last_cond_idx0
            self.phase = "idle"
            self.ui_state = "idle"
            self.current_condition_name = last.condition_name
            self.current_layout = LAYOUTS.get(self.current_condition_name, {})
            self.trial_in_condition = max(r.trial_in_condition for r in last_cond_recs)
            self.condition_label.setText(f"Block {self.current_condition_idx+1}/6 complete")
            self.btn_start_condition.setText("Continue experiment")
            self.btn_start_condition.setEnabled(True)
            self.stim_button.setText("STIMULUS")
            self.stim_button.setEnabled(False)
            self.set_feedback_neutral("저장된 파일에서 불러왔습니다. 현재 block은 완료되어 있습니다. Continue experiment를 누르면 다음 block으로 진행합니다.")
            self.update_status("Resumed: block complete")
            if self.current_condition_idx + 1 >= len(self.condition_order):
                self.btn_start_condition.setText("Finished")
                self.btn_start_condition.setEnabled(False)
                self.update_status("All conditions complete")
            return

        # Resume inside the last condition.
        self.current_condition_idx = last_cond_idx0
        self.current_condition_name = last.condition_name
        if not self.current_condition_name and self.condition_order:
            self.current_condition_name = self.condition_order[self.current_condition_idx]
        self.current_layout = LAYOUTS.get(self.current_condition_name, {})
        self.trial_in_condition = max(r.trial_in_condition for r in last_cond_recs)
        self.condition_label.setText(f"Block {self.current_condition_idx+1}/6")
        self.btn_start_condition.setText("Running")
        self.btn_start_condition.setEnabled(False)
        self.clear_candidates()
        self.current_correct = None
        self.ui_state = "ready"
        self.stim_button.setText("STIMULUS")
        self.stim_button.setEnabled(True)

        if retention_recs:
            self.phase = "retention"
            self.retention_started_at_trial = min(r.trial_in_condition for r in retention_recs) - 1
            counts = {p: 0 for p in range(1, 10)}
            for r in retention_recs:
                if 1 <= int(r.position) <= 9:
                    counts[int(r.position)] += 1
            remaining = []
            for p in range(1, 10):
                remaining.extend([p] * max(0, 2 - counts.get(p, 0)))
            random.shuffle(remaining)
            self.retention_queue = remaining
            self.set_feedback_neutral(f"저장된 retention에서 이어갑니다. 남은 retention trials: {len(self.retention_queue)}. STIMULUS를 누르세요.")
            self.update_status("Resumed: retention")
            return

        # Resume learning phase.
        self.phase = "learning"
        self.recent_correct = [int(r.is_correct) for r in learning_recs[-self.cfg.criterion_window:]]
        # Estimate elapsed learning time from saved timestamps, excluding the time since app was closed.
        if learning_recs:
            ts = [float(r.timestamp) for r in learning_recs if r.timestamp]
            elapsed_so_far = max(0.0, max(ts) - min(ts)) if len(ts) >= 2 else 0.0
        else:
            elapsed_so_far = 0.0
        self.learning_start_time = time.time() - min(elapsed_so_far, self.cfg.learning_time_cap_sec)
        # Continue the current 9-trial mini-block without repeating already sampled positions.
        pos_in_current_block = [int(r.position) for r in learning_recs[-(len(learning_recs) % 9):]] if learning_recs else []
        remaining = [p for p in range(1, 10) if p not in pos_in_current_block]
        if not remaining:
            remaining = list(range(1, 10))
        random.shuffle(remaining)
        self.learning_positions_queue = remaining
        recent_sum = sum(self.recent_correct)
        if len(self.recent_correct) >= self.cfg.criterion_window and recent_sum >= self.cfg.criterion_correct:
            self.ui_state = "feedback"
            self.stim_button.setText("Next (Retention)")
            self.stim_button.setEnabled(True)
            self.set_feedback_neutral("저장된 기록상 학습 기준에 도달했습니다. Next를 누르면 retention을 시작합니다.")
            self.update_status("Resumed: criterion already reached")
            return
        self.set_feedback_neutral("저장된 learning phase에서 이어갑니다. STIMULUS를 누르세요.")
        self.update_status(f"Resumed: learning | recent {recent_sum}/{len(self.recent_correct)}")

    # ---------------- Experiment logic ----------------
    def start_next_condition(self):
        if self.phase in ["learning", "retention"]:
            QMessageBox.information(self, "Running", "현재 block이 진행 중입니다. Retention까지 끝난 뒤 계속 진행하세요.")
            return
        # If this app just opened and a previous CSV exists, resume from it.
        if not self.records and self.try_resume_from_saved_log():
            return
        if not self.condition_order:
            self.make_order()
        self.current_condition_idx += 1
        if self.current_condition_idx >= len(self.condition_order):
            self.update_status("All conditions complete")
            self.save_logs()
            self.stim_button.setEnabled(False)
            self.btn_start_condition.setEnabled(False)
            self.btn_start_condition.setText("Finished")
            return
        self.current_condition_name = self.condition_order[self.current_condition_idx]
        self.current_layout = LAYOUTS[self.current_condition_name]
        self.learning_start_time = time.time()
        self.phase = "learning"
        self.ui_state = "ready"
        self.trial_in_condition = 0
        self.recent_correct = []
        self.learning_positions_queue = []
        self.retention_queue = []
        self.current_correct = None
        self.condition_label.setText(f"Block {self.current_condition_idx+1}/6")
        self.btn_start_condition.setText("Running")
        self.btn_start_condition.setEnabled(False)
        self.log(f"[Internal] condition={self.current_condition_name}, score={ORDER_SCORE.get(self.current_condition_name)}, layout={self.current_layout}")
        self.set_feedback_neutral("Map preview 없음. STIMULUS를 누르면 자극과 동시에 음성 감지가 시작됩니다.")
        self.clear_candidates()
        self.stim_button.setText("STIMULUS")
        self.stim_button.setEnabled(True)
        self.update_status("Condition started. Press STIMULUS.")

    def _make_next_position(self) -> int:
        if self.phase == "retention":
            if not self.retention_queue:
                self.retention_queue = list(range(1,10)) * 2
                random.shuffle(self.retention_queue)
            return self.retention_queue.pop(0)
        if not self.learning_positions_queue:
            self.learning_positions_queue = list(range(1,10))
            random.shuffle(self.learning_positions_queue)
        return self.learning_positions_queue.pop(0)

    def on_stimulus_or_next(self):
        if self.ui_state == "feedback":
            self.continue_after_feedback()
        else:
            self.start_trial()

    def start_trial(self):
        if self.phase not in ["learning", "retention"]:
            QMessageBox.warning(self, "No experiment", "Start experiment first.")
            return
        if self.ui_state in ["listening", "answer"]:
            return
        if self.phase == "learning" and (time.time() - self.learning_start_time) >= self.cfg.learning_time_cap_sec:
            self.update_status("8 min cap reached. Starting retention.")
            self.start_retention()
            return
        if self.phase == "retention" and not self.retention_queue and self.trial_in_condition >= self.retention_started_at_trial + self.cfg.retention_trials:
            self.finish_condition()
            return
        self.trial_global += 1
        self.trial_in_condition += 1
        self.current_position = self._make_next_position()
        self.current_motor_id = LOGICAL_POS_TO_MOTOR_ID[int(self.current_position)]
        self.current_correct = self.current_layout[self.current_position]
        self.current_top5 = []
        self.current_voice_result = None
        self.pending_trial_start = time.time()
        self.clear_candidates()
        self.stim_button.setEnabled(False)
        self.ui_state = "listening"
        self.set_feedback_neutral(f"Stimulus sent. Listening...  ({self.phase})")
        self.update_status(f"Trial {self.trial_in_condition} ({self.phase})")
        self.ensure_stimulator()
        self.stimulator.send_position(self.current_position)
        self.voice_worker = VoiceResponseWorker(self.cfg, self.classifier, self.voice_dir)
        self.voice_worker.status.connect(self.feedback_label.setText)
        self.voice_worker.result.connect(self.handle_voice_result)
        self.voice_worker.start()

    def handle_voice_result(self, result: dict):
        self.current_voice_result = result
        if result.get("error"):
            self.set_feedback_wrong(f"Voice failed: {result.get('message', result.get('error'))}. STIMULUS로 같은 trial 재시도")
            # Roll back trial count because no answer was recorded.
            self.trial_global -= 1
            self.trial_in_condition -= 1
            self.current_correct = None
            self.ui_state = "ready"
            self.stim_button.setText("STIMULUS")
            self.stim_button.setEnabled(True)
            return
        top5 = result.get("top5", [])
        self.current_top5 = top5
        for i, b in enumerate(self.candidate_buttons):
            if i < len(top5):
                lab, prob = top5[i]
                b.setText(f"{i+1}. {lab}  ({prob:.2f})")
                b.setEnabled(True)
            else:
                b.setText(f"{i+1}. -")
                b.setEnabled(False)
        rt = result.get("voice_onset_rt_sec")
        self.set_feedback_neutral(f"Voice detected. onset RT={rt:.3f}s. Top-5에서 선택하거나 직접 입력하세요.")
        self.ui_state = "answer"

    def submit_candidate(self, idx: int):
        if self.ui_state != "answer":
            return
        if idx < len(self.current_top5):
            self._submit_response(self.current_top5[idx][0], source=f"top{idx+1}")

    def submit_manual(self):
        if self.ui_state != "answer":
            return
        text = self.manual_input.text().strip()
        if text in CONSONANT_TO_SYMBOL:
            text = CONSONANT_TO_SYMBOL[text]
        elif text in SYLLABLE_TO_SYMBOL:
            text = SYLLABLE_TO_SYMBOL[text]
        if text not in SYMBOLS:
            QMessageBox.warning(self, "Invalid response", "기역/니은/디귿/리을/미음/비읍/시옷/이응/지읒 또는 ㄱ/ㄴ/... 중 하나를 입력하세요.")
            return
        self._submit_response(text, source="manual")

    def _submit_response(self, response: str, source: str):
        if self.current_correct is None:
            return
        confirm_rt = time.time() - self.pending_trial_start
        rt = None
        if self.current_voice_result:
            rt = self.current_voice_result.get("voice_onset_rt_sec")
        is_corr = int(response == self.current_correct)
        rec = TrialRecord(
            subject_id=self.subject_spin.value(),
            session_id=self.session_id,
            condition_index=self.current_condition_idx + 1,
            condition_name=self.current_condition_name,
            condition_score=ORDER_SCORE.get(self.current_condition_name, -1),
            phase=self.phase,
            trial_global=self.trial_global,
            trial_in_condition=self.trial_in_condition,
            mini_block=math.ceil(self.trial_in_condition / 9),
            position=int(self.current_position),
            motor_id=int(self.current_motor_id),
            correct_symbol=self.current_correct,
            correct_consonant=SYMBOL_TO_CONSONANT[self.current_correct],
            response_symbol=response,
            response_source=source,
            is_correct=is_corr,
            voice_onset_rt_sec=rt,
            response_confirm_rt_sec=confirm_rt,
            top5_json=json.dumps(self.current_top5, ensure_ascii=False),
            timestamp=time.time(),
        )
        self.records.append(rec)
        # Auto-save after every recorded trial.
        self.save_logs(silent=True)
        for b in self.candidate_buttons:
            b.setEnabled(False)
        self.mark_candidate_buttons_after_answer(response)
        self.manual_input.clear()
        if self.phase == "learning":
            self.recent_correct.append(is_corr)
            if len(self.recent_correct) > self.cfg.criterion_window:
                self.recent_correct = self.recent_correct[-self.cfg.criterion_window:]
            recent_sum = sum(self.recent_correct)
            elapsed = time.time() - self.learning_start_time
            correct_text = f"정답: {self.current_correct} ({SYMBOL_TO_CONSONANT.get(self.current_correct, '')})"
            response_text = f"내 응답: {response} ({SYMBOL_TO_CONSONANT.get(response, '')})"
            suffix = f" | recent {recent_sum}/{len(self.recent_correct)} | elapsed {elapsed/60:.1f} min"
            if is_corr:
                self.set_feedback_correct(f"정답입니다!  {correct_text}{suffix}")
            else:
                self.set_feedback_wrong(f"오답입니다.  {response_text}  →  {correct_text}{suffix}")
            reached = len(self.recent_correct) >= self.cfg.criterion_window and recent_sum >= self.cfg.criterion_correct
            timeout = elapsed >= self.cfg.learning_time_cap_sec
            if reached:
                self.ui_state = "feedback"
                self.stim_button.setText("Next (Retention)")
                self.stim_button.setEnabled(True)
                self.update_status("Criterion reached. Press Next to start retention.")
                return
            if timeout:
                self.ui_state = "feedback"
                self.stim_button.setText("Next (Retention)")
                self.stim_button.setEnabled(True)
                self.update_status("8 min cap reached. Press Next to start retention.")
                return
        else:
            # Retention is no-feedback: save correctness internally, but do not reveal answer.
            self.set_feedback_neutral("Retention 응답 저장 완료. Next를 눌러 계속하세요.")
            if self.trial_in_condition >= self.retention_started_at_trial + self.cfg.retention_trials:
                self.ui_state = "feedback"
                self.stim_button.setText("Next Condition")
                self.stim_button.setEnabled(True)
                self.update_status("Retention complete. Press Next Condition.")
                return
        self.ui_state = "feedback"
        self.stim_button.setText("Next")
        self.stim_button.setEnabled(True)
        self.current_correct = None

    def continue_after_feedback(self):
        if self.phase == "learning":
            elapsed = time.time() - self.learning_start_time
            if (len(self.recent_correct) >= self.cfg.criterion_window and sum(self.recent_correct) >= self.cfg.criterion_correct) or elapsed >= self.cfg.learning_time_cap_sec:
                self.start_retention()
                return
            self.ui_state = "ready"
            self.stim_button.setText("STIMULUS")
            self.stim_button.setEnabled(True)
            self.set_feedback_neutral("Press STIMULUS for the next trial.")
        elif self.phase == "retention":
            if self.trial_in_condition >= self.retention_started_at_trial + self.cfg.retention_trials:
                self.finish_condition()
                return
            self.ui_state = "ready"
            self.stim_button.setText("STIMULUS")
            self.stim_button.setEnabled(True)
            self.set_feedback_neutral("Retention: press STIMULUS for the next trial.")

    def start_retention(self):
        self.phase = "retention"
        self.ui_state = "ready"
        self.retention_queue = list(range(1,10)) * 2
        random.shuffle(self.retention_queue)
        self.retention_started_at_trial = self.trial_in_condition
        self.current_correct = None
        self.clear_candidates()
        self.stim_button.setText("STIMULUS")
        self.stim_button.setEnabled(True)
        self.set_feedback_neutral("Retention test: 18 trials, no feedback after response selection. Press STIMULUS.")
        self.update_status("Retention started.")

    def finish_condition(self):
        self.phase = "idle"
        self.ui_state = "idle"
        self.stim_button.setText("STIMULUS")
        self.stim_button.setEnabled(False)
        self.set_feedback_neutral("Current block complete. Press Continue experiment to continue.")
        self.update_status("Block complete.")
        self.save_logs()
        self.btn_start_condition.setEnabled(True)
        self.btn_start_condition.setText("Continue experiment")

    def save_logs(self, silent: bool = False):
        if not self.records:
            if not silent:
                self.log("No records to save.")
            return
        out = self.log_dir / f"subject_{self.subject_spin.value():03d}_{self.session_id}.csv"
        fields = list(asdict(self.records[0]).keys())
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in self.records:
                writer.writerow(asdict(r))
        if not silent:
            self.log(f"Saved logs: {out}")

    def closeEvent(self, event):
        self.save_logs()
        if self.stimulator:
            self.stimulator.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
