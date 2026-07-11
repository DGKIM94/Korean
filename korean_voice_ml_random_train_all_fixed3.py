"""Full-feature Korean voice classifier: MFCC-DTW + duration/RMS/ZCR/spectral/pitch features + STT alias.
Generated for testing short Korean consonant/vowel responses.
"""

import sys
import time
import queue
import wave
import pickle
import re
import json
import random
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np
import sounddevice as sd
import webrtcvad

from scipy.spatial.distance import cdist
from scipy.signal import get_window
from python_speech_features import mfcc, delta
from faster_whisper import WhisperModel

try:
    from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
    import joblib
    HAS_SKLEARN = True
except Exception:
    HAS_SKLEARN = False
    RandomForestClassifier = None
    ExtraTreesClassifier = None
    joblib = None

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QMessageBox,
    QGroupBox,
    QGridLayout,
)

# ============================================================
# Label Sets
# ============================================================

BASIC_CONSONANTS = [
    "기역", "니은", "디귿", "리을", "미음", "비읍", "시옷",
    "이응", "지읒", "치읓", "키읔", "티읕", "피읖", "히읗",
]

DOUBLE_CONSONANTS = [
    "쌍기역", "쌍디귿", "쌍비읍", "쌍시옷", "쌍지읒",
]

CONSONANTS_WITH_DOUBLE = [
    "기역", "쌍기역", "니은", "디귿", "쌍디귿", "리을", "미음",
    "비읍", "쌍비읍", "시옷", "쌍시옷", "이응", "지읒", "쌍지읒",
    "치읓", "키읔", "티읕", "피읖", "히읗",
]

BASIC_VOWELS = [
    "아", "야", "어", "여", "오", "요", "우", "유", "으", "이",
]

COMPLEX_VOWELS = [
    "애", "얘", "에", "예", "와", "왜", "외", "워", "웨", "위", "의",
]

VOWELS_WITH_COMPLEX = BASIC_VOWELS + COMPLEX_VOWELS
ALL_LABELS = CONSONANTS_WITH_DOUBLE + VOWELS_WITH_COMPLEX

LABEL_SETS = {
    "All": ALL_LABELS,
    "Consonants only": BASIC_CONSONANTS,
    "Consonants + double": CONSONANTS_WITH_DOUBLE,
    "Double consonants only": DOUBLE_CONSONANTS,
    "Basic vowels only": BASIC_VOWELS,
    "Vowels + complex": VOWELS_WITH_COMPLEX,
    "Complex vowels only": COMPLEX_VOWELS,
}

CONFUSION_GROUPS = [
    {"애", "에", "얘", "예"},
    {"왜", "웨", "외"},
    {"우", "유", "요"},
    {"아", "야"},
    {"어", "여"},
]

# ============================================================
# Audio Settings
# ============================================================

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)
CHANNELS = 1
BASE_DIR = Path("voice_profiles")
BASE_DIR.mkdir(exist_ok=True)

# ============================================================
# Text Normalization / Alias Utility
# ============================================================

def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = text.strip().lower()
    text = re.sub(r"[\s\.,!?~·…\-_'\"`]+", "", text)
    text = text.replace("쌍 기억", "쌍기역")
    text = text.replace("쌍 디귿", "쌍디귿")
    text = text.replace("쌍 비읍", "쌍비읍")
    text = text.replace("쌍 시옷", "쌍시옷")
    text = text.replace("쌍 지읒", "쌍지읒")
    return text


def read_wav_int16(path):
    """Read a WAV file and return mono int16 audio for feedback learning."""
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    if sampwidth != 2:
        raise ValueError("Only 16-bit PCM WAV files are supported for feedback learning.")
    audio = np.frombuffer(raw, dtype=np.int16)
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1).astype(np.int16)
    return audio

MANUAL_ALIASES = {
    "기역": ["기역", "기억", "기어", "기역이"],
    "쌍기역": ["쌍기역", "쌍기억", "쌍 기억", "상기역"],
    "니은": ["니은", "니언", "니은이"],
    "디귿": ["디귿", "디귿이", "디긋", "디귿"],
    "쌍디귿": ["쌍디귿", "쌍디긋", "쌍 디귿", "상디귿"],
    "리을": ["리을", "리울", "리을이"],
    "미음": ["미음", "미움", "미음이"],
    "비읍": ["비읍", "비업", "비음", "비읍이"],
    "쌍비읍": ["쌍비읍", "쌍비업", "쌍 비읍", "상비읍"],
    "시옷": ["시옷", "시옷이", "시옷"],
    "쌍시옷": ["쌍시옷", "쌍 시옷", "상시옷"],
    "이응": ["이응", "이응이"],
    "지읒": ["지읒", "지읏", "지읒이"],
    "쌍지읒": ["쌍지읒", "쌍지읏", "쌍 지읒", "상지읒"],
    "치읓": ["치읓", "치읏", "치읓이"],
    "키읔": ["키읔", "키윽", "키읔이"],
    "티읕": ["티읕", "티읏", "티읕이"],
    "피읖": ["피읖", "피읍", "피읖이"],
    "히읗": ["히읗", "히읏", "이읗", "히읗이"],
}

def text_similarity(a: str, b: str) -> float:
    """Simple character bigram similarity in [0, 1]."""
    a = normalize_text(a)
    b = normalize_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    def grams(s):
        if len(s) == 1:
            return {s}
        return {s[i:i+2] for i in range(len(s) - 1)}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))

# ============================================================
# Tunable Audio Recorder with VAD + RMS Gate
# ============================================================

class AudioRecorder:
    def __init__(
        self,
        sample_rate=16000,
        frame_ms=30,
        vad_level=3,
        speech_frames_required=4,
        pre_buffer_frames=15,
        max_wait_sec=8.0,
        max_record_sec=4.0,
        end_silence_sec=0.8,
        noise_calibration_sec=0.45,
        energy_multiplier=2.5,
        min_energy_rms=120.0,
        min_record_sec=0.25,
    ):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_size = int(sample_rate * frame_ms / 1000)
        self.vad_level = int(vad_level)
        self.vad = webrtcvad.Vad(self.vad_level)

        self.speech_frames_required = int(speech_frames_required)
        self.pre_buffer_frames = int(pre_buffer_frames)
        self.max_wait_sec = float(max_wait_sec)
        self.max_record_sec = float(max_record_sec)
        self.end_silence_frames = int(float(end_silence_sec) * 1000 / frame_ms)
        self.noise_calibration_sec = float(noise_calibration_sec)
        self.energy_multiplier = float(energy_multiplier)
        self.min_energy_rms = float(min_energy_rms)
        self.min_record_sec = float(min_record_sec)

        self.last_noise_rms = None
        self.last_energy_threshold = None
        self.last_duration_sec = None

    @staticmethod
    def _rms(frame):
        x = frame.astype(np.float32).flatten()
        return float(np.sqrt(np.mean(x * x) + 1e-8))

    def record_until_silence(self):
        q_audio = queue.Queue()

        def callback(indata, frames, time_info, status):
            q_audio.put(indata.copy())

        pre_speech_frames = []
        speech_frames = []
        noise_rms_values = []

        triggered = False
        speech_count = 0
        silence_count = 0

        record_start_time = time.perf_counter()
        voice_start_time = None
        noise_end_time = record_start_time + self.noise_calibration_sec

        # Noise gate is initialized after the short background-noise measurement.
        energy_threshold = None

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.frame_size,
            callback=callback,
        ):
            while True:
                now = time.perf_counter()

                if not triggered and now - record_start_time > self.max_wait_sec:
                    return None, None

                if triggered and now - voice_start_time > self.max_record_sec:
                    break

                try:
                    frame = q_audio.get(timeout=0.1)
                except queue.Empty:
                    continue

                frame_rms = self._rms(frame)

                # 1) Measure background noise first.
                if not triggered and now < noise_end_time:
                    noise_rms_values.append(frame_rms)
                    pre_speech_frames.append(frame)
                    if len(pre_speech_frames) > self.pre_buffer_frames:
                        pre_speech_frames.pop(0)
                    continue

                if energy_threshold is None:
                    noise_rms = float(np.median(noise_rms_values)) if noise_rms_values else 0.0
                    energy_threshold = max(self.min_energy_rms, noise_rms * self.energy_multiplier)
                    self.last_noise_rms = noise_rms
                    self.last_energy_threshold = energy_threshold

                vad_speech = self.vad.is_speech(frame.tobytes(), self.sample_rate)
                energy_speech = frame_rms >= energy_threshold
                is_speech = vad_speech and energy_speech

                if not triggered:
                    pre_speech_frames.append(frame)
                    if len(pre_speech_frames) > self.pre_buffer_frames:
                        pre_speech_frames.pop(0)

                    if is_speech:
                        speech_count += 1
                    else:
                        speech_count = 0

                    if speech_count >= self.speech_frames_required:
                        triggered = True
                        voice_start_time = time.perf_counter()
                        speech_frames.extend(pre_speech_frames)
                        speech_frames.append(frame)
                else:
                    speech_frames.append(frame)
                    # Ending can be a bit more permissive: VAD OR energy keeps recording.
                    keep_speech = vad_speech or energy_speech
                    if keep_speech:
                        silence_count = 0
                    else:
                        silence_count += 1

                    current_duration = (len(speech_frames) * self.frame_ms) / 1000.0
                    if current_duration >= self.min_record_sec and silence_count >= self.end_silence_frames:
                        break

        if not speech_frames or voice_start_time is None:
            return None, None

        audio = np.concatenate(speech_frames, axis=0).flatten()
        self.last_duration_sec = len(audio) / self.sample_rate
        voice_rt = voice_start_time - record_start_time
        return audio, voice_rt

    @staticmethod
    def save_wav(path, audio, sample_rate=16000):
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())

# ============================================================
# MFCC Feature Extraction
# ============================================================

def extract_mfcc_features(audio_int16, sample_rate=16000):
    """
    Output: frames x 39
      - 13 MFCC: spectral/timbre envelope of the voice
      - 13 delta: temporal change of MFCC
      - 13 delta-delta: acceleration of the MFCC change
    """
    audio = audio_int16.astype(np.float32)
    if np.max(np.abs(audio)) > 0:
        audio = audio / np.max(np.abs(audio))

    mfcc_feat = mfcc(
        audio,
        samplerate=sample_rate,
        numcep=13,
        nfilt=26,
        nfft=512,
        winlen=0.025,
        winstep=0.010,
        preemph=0.97,
        appendEnergy=True,
    )
    delta_feat = delta(mfcc_feat, 2)
    delta_delta_feat = delta(delta_feat, 2)
    feat = np.concatenate([mfcc_feat, delta_feat, delta_delta_feat], axis=1)
    return cmvn(feat)



# ============================================================
# Additional Sound Feature Extraction
# ============================================================

GLOBAL_FEATURE_KEYS = [
    "duration", "rms_mean", "rms_std", "rms_max", "rms_range",
    "onset_sharpness", "zcr_mean", "zcr_std",
    "spectral_centroid_mean", "spectral_centroid_std",
    "spectral_bandwidth_mean", "spectral_rolloff_mean",
    "f0_mean", "f0_std", "voiced_ratio",
]

def _normalize_audio(audio_int16):
    x = audio_int16.astype(np.float32)
    m = np.max(np.abs(x)) if len(x) else 0
    if m > 0:
        x = x / m
    return x

def _frame_signal(x, frame_length, hop_length):
    if len(x) < frame_length:
        x = np.pad(x, (0, frame_length-len(x)))
    frames = []
    for st in range(0, len(x)-frame_length+1, hop_length):
        frames.append(x[st:st+frame_length])
    if not frames:
        frames = [np.pad(x, (0, max(0, frame_length-len(x))))[:frame_length]]
    return np.stack(frames, axis=0)

def _estimate_pitch_autocorr(x, sample_rate=SAMPLE_RATE, fmin=70, fmax=400):
    frame_length = int(0.04 * sample_rate)
    hop_length = int(0.01 * sample_rate)
    frames = _frame_signal(x, frame_length, hop_length)
    min_lag = int(sample_rate / fmax)
    max_lag = int(sample_rate / fmin)
    f0s = []
    for fr in frames:
        fr = fr - np.mean(fr)
        if np.sqrt(np.mean(fr*fr)+1e-8) < 0.02:
            continue
        corr = np.correlate(fr, fr, mode='full')[len(fr)-1:]
        if len(corr) <= max_lag:
            continue
        corr[:min_lag] = 0
        lag = int(np.argmax(corr[min_lag:max_lag]) + min_lag)
        peak = corr[lag] / (corr[0] + 1e-8)
        if peak > 0.25:
            f0s.append(sample_rate / lag)
    if not f0s:
        return 0.0, 0.0, 0.0
    f0s = np.asarray(f0s, dtype=np.float32)
    return float(np.mean(f0s)), float(np.std(f0s)), float(len(f0s)/max(1, len(frames)))

def extract_global_sound_features(audio_int16, sample_rate=SAMPLE_RATE):
    """Extract scalar sound features useful for short consonant/vowel recognition.

    Features include duration, RMS envelope, onset sharpness, zero crossing rate,
    spectral centroid/bandwidth/rolloff, and simple pitch statistics.
    """
    x = _normalize_audio(audio_int16)
    duration = len(x) / sample_rate if len(x) else 0.0
    frame_length = int(0.025 * sample_rate)
    hop_length = int(0.010 * sample_rate)
    frames = _frame_signal(x, frame_length, hop_length)
    rms = np.sqrt(np.mean(frames*frames, axis=1) + 1e-8)
    rms_mean = float(np.mean(rms)); rms_std=float(np.std(rms)); rms_max=float(np.max(rms))
    rms_range = float(np.max(rms)-np.min(rms))
    drms = np.diff(rms)
    onset_sharpness = float(np.max(drms)) if len(drms) else 0.0
    signs = np.sign(frames)
    zcr = np.mean(np.abs(np.diff(signs, axis=1)) > 0, axis=1)
    zcr_mean=float(np.mean(zcr)); zcr_std=float(np.std(zcr))
    fft_size=512
    win = get_window('hann', frame_length)
    freqs = np.fft.rfftfreq(fft_size, d=1/sample_rate)
    mags = np.abs(np.fft.rfft(frames*win, n=fft_size, axis=1)) + 1e-8
    power = mags*mags
    psum = np.sum(power, axis=1, keepdims=True) + 1e-8
    centroid = np.sum(power*freqs[None,:], axis=1)/psum.flatten()
    bandwidth = np.sqrt(np.sum(power*(freqs[None,:]-centroid[:,None])**2, axis=1)/psum.flatten())
    cumulative = np.cumsum(power, axis=1)
    roll=[]
    for i in range(power.shape[0]):
        idx = np.searchsorted(cumulative[i], 0.85*cumulative[i,-1])
        roll.append(freqs[min(idx, len(freqs)-1)])
    roll=np.asarray(roll)
    f0_mean, f0_std, voiced_ratio = _estimate_pitch_autocorr(x, sample_rate)
    d = {
        'duration': float(duration),
        'rms_mean': rms_mean,
        'rms_std': rms_std,
        'rms_max': rms_max,
        'rms_range': rms_range,
        'onset_sharpness': onset_sharpness,
        'zcr_mean': zcr_mean,
        'zcr_std': zcr_std,
        'spectral_centroid_mean': float(np.mean(centroid)),
        'spectral_centroid_std': float(np.std(centroid)),
        'spectral_bandwidth_mean': float(np.mean(bandwidth)),
        'spectral_rolloff_mean': float(np.mean(roll)),
        'f0_mean': f0_mean,
        'f0_std': f0_std,
        'voiced_ratio': voiced_ratio,
    }
    v = np.array([d[k] for k in GLOBAL_FEATURE_KEYS], dtype=np.float32)
    return d, v

def _global_stats_from_templates(templates, candidate_labels):
    vecs=[]
    for lab in candidate_labels:
        for t in templates.get(lab, []):
            if isinstance(t, dict) and 'global_vec' in t:
                vecs.append(t['global_vec'])
    if not vecs:
        return np.zeros(len(GLOBAL_FEATURE_KEYS), dtype=np.float32), np.ones(len(GLOBAL_FEATURE_KEYS), dtype=np.float32)
    arr=np.stack(vecs, axis=0)
    return np.mean(arr, axis=0), np.std(arr, axis=0)+1e-6

def cmvn(feat):
    return (feat - np.mean(feat, axis=0, keepdims=True)) / (np.std(feat, axis=0, keepdims=True) + 1e-8)

# ============================================================
# DTW Distance
# ============================================================

def dtw_distance(x, y):
    if x is None or y is None or len(x) == 0 or len(y) == 0:
        return np.inf
    dist = cdist(x, y, metric="euclidean")
    n, m = dist.shape
    dp = np.full((n + 1, m + 1), np.inf)
    dp[0, 0] = 0.0
    for i in range(1, n + 1):
        # simple DP; enough for short utterances
        for j in range(1, m + 1):
            dp[i, j] = dist[i - 1, j - 1] + min(dp[i - 1, j], dp[i, j - 1], dp[i - 1, j - 1])
    return float(dp[n, m] / (n + m))

# ============================================================
# Whisper STT helper
# ============================================================

class STTEngine:
    def __init__(self, device="cuda", compute_type="float16", fallback_to_cpu=True):
        self.model = None
        self.model_name = "tiny"
        self.device = device
        self.compute_type = compute_type
        self.fallback_to_cpu = fallback_to_cpu
        self.active_device = device
        self.active_compute_type = compute_type

    def load(self, model_name="tiny"):
        reload_needed = (
            self.model is None
            or self.model_name != model_name
            or self.active_device != self.device
            or self.active_compute_type != self.compute_type
        )
        if reload_needed:
            self.model_name = model_name
            try:
                self.model = WhisperModel(
                    model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                self.active_device = self.device
                self.active_compute_type = self.compute_type
            except Exception as e:
                if not self.fallback_to_cpu:
                    raise
                print(f"[STT] CUDA load failed: {e}")
                print("[STT] Falling back to CPU/int8.")
                self.model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                )
                self.active_device = "cpu"
                self.active_compute_type = "int8"
        return self.model

    def transcribe(self, wav_path, model_name="tiny"):
        model = self.load(model_name)
        t0 = time.perf_counter()
        segments, info = model.transcribe(
            str(wav_path),
            language="ko",
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        elapsed = time.perf_counter() - t0
        # Return elapsed only; device info is available as self.active_device.
        return text, normalize_text(text), elapsed

# ============================================================
# Voice Profile
# ============================================================

class VoiceProfile:
    def __init__(self, subject_id, gender_group="Unspecified"):
        self.subject_id = subject_id
        self.gender_group = gender_group or "Unspecified"
        self.subject_dir = BASE_DIR / subject_id
        self.wav_dir = self.subject_dir / "calibration_wav"
        self.rejected_dir = self.subject_dir / "rejected_wav"
        self.trial_dir = self.subject_dir / "trial_wav"
        self.profile_path = self.subject_dir / "profile_alias_hybrid_sets_tunable.pkl"
        self.meta_path = self.subject_dir / "profile_metadata.json"
        self.templates = defaultdict(list)
        self.alias_counts = defaultdict(Counter)
        self.subject_dir.mkdir(parents=True, exist_ok=True)
        self.wav_dir.mkdir(parents=True, exist_ok=True)
        self.rejected_dir.mkdir(parents=True, exist_ok=True)
        self.trial_dir.mkdir(parents=True, exist_ok=True)

    def add_template(self, label, audio, stt_text=""):
        mfcc_feat = extract_mfcc_features(audio, SAMPLE_RATE)
        global_dict, global_vec = extract_global_sound_features(audio, SAMPLE_RATE)
        self.templates[label].append({
            'mfcc': mfcc_feat,
            'global_dict': global_dict,
            'global_vec': global_vec,
        })
        norm = normalize_text(stt_text)
        if norm:
            self.alias_counts[label][norm] += 1
        # Manual aliases are weak priors.
        for alias in MANUAL_ALIASES.get(label, []):
            self.alias_counts[label][normalize_text(alias)] += 1

    def save_metadata(self):
        self.subject_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "subject_id": self.subject_id,
            "gender_group": self.gender_group,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def load_metadata(self):
        if self.meta_path.exists():
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self.gender_group = meta.get("gender_group", "Unspecified")
            except Exception:
                self.gender_group = "Unspecified"
        return self.gender_group

    def save(self):
        with open(self.profile_path, "wb") as f:
            pickle.dump({
                "templates": dict(self.templates),
                "alias_counts": {k: dict(v) for k, v in self.alias_counts.items()},
                "gender_group": self.gender_group,
            }, f)
        self.save_metadata()

    def load(self):
        if not self.profile_path.exists():
            return False
        with open(self.profile_path, "rb") as f:
            data = pickle.load(f)
        self.gender_group = data.get("gender_group", self.load_metadata())
        self.templates = defaultdict(list, data.get("templates", {}))
        self.alias_counts = defaultdict(Counter)
        for k, v in data.get("alias_counts", {}).items():
            self.alias_counts[k] = Counter(v)
        return True

    def merge_pooled_profile(self, other_profile, candidate_labels, source_name="pooled", distance_penalty=0.40, alias_boost=False):
        """Merge another subject profile as a weak pooled reference.

        Pooled templates receive a positive distance_penalty, so they can help when
        the personal profile is sparse but do not dominate the personal profile.
        """
        for label in candidate_labels:
            for item in other_profile.templates.get(label, []):
                if not isinstance(item, dict):
                    item = {"mfcc": item, "global_vec": None, "global_dict": {}}
                copied = dict(item)
                copied["source"] = source_name
                copied["distance_penalty"] = float(distance_penalty)
                self.templates[label].append(copied)
            if alias_boost:
                for alias, count in other_profile.alias_counts.get(label, Counter()).items():
                    self.alias_counts[label][alias] += max(1, int(count * 0.25))

    def acoustic_scores(self, audio, candidate_labels):
        input_feat = extract_mfcc_features(audio, SAMPLE_RATE)
        input_global_dict, input_global_vec = extract_global_sound_features(audio, SAMPLE_RATE)
        global_mean, global_std = _global_stats_from_templates(self.templates, candidate_labels)
        input_global_z = (input_global_vec - global_mean) / global_std
        scores = []
        for label in candidate_labels:
            if label not in self.templates:
                continue
            mfcc_distances = []
            global_distances = []
            for t in self.templates[label]:
                if isinstance(t, dict):
                    template_mfcc = t.get('mfcc')
                    template_global_vec = t.get('global_vec')
                else:
                    # Backward compatibility with old profiles
                    template_mfcc = t
                    template_global_vec = None
                penalty = float(t.get("distance_penalty", 0.0)) if isinstance(t, dict) else 0.0
                mfcc_distances.append(dtw_distance(input_feat, template_mfcc) + penalty)
                if template_global_vec is not None:
                    template_global_z = (template_global_vec - global_mean) / global_std
                    global_distances.append(float(np.linalg.norm(input_global_z-template_global_z)/np.sqrt(len(GLOBAL_FEATURE_KEYS))) + penalty)
            if mfcc_distances:
                mfcc_best = float(min(mfcc_distances))
                global_best = float(min(global_distances)) if global_distances else 0.0
                # Combined acoustic score: MFCC-DTW remains dominant; global features help with duration, energy, ZCR, pitch, spectral cues.
                combined = mfcc_best + 0.25 * global_best
                scores.append({
                    "label": label,
                    "best_distance": combined,
                    "mfcc_distance": mfcc_best,
                    "global_distance": global_best,
                    "avg_distance": float(np.mean(sorted(mfcc_distances)[:min(2, len(mfcc_distances))])),
                    "template_count": len(mfcc_distances),
                })
        return sorted(scores, key=lambda x: x["best_distance"])

    def alias_bonus(self, label, stt_norm):
        if not stt_norm:
            return 0.0
        aliases = self.alias_counts.get(label, Counter())
        if not aliases:
            return 0.0

        best = 0.0
        total = max(1, sum(aliases.values()))
        for alias, count in aliases.items():
            sim = text_similarity(stt_norm, alias)
            freq_weight = min(1.0, count / total + 0.25)
            best = max(best, sim * freq_weight)
        return best

    def predict_hybrid(self, audio, candidate_labels, wav_path, stt_engine=None, stt_model="tiny", force_stt=False,
                       uncertain_ratio=0.90, uncertain_margin=0.45, alias_weight=0.65):
        t0 = time.perf_counter()
        acoustic = self.acoustic_scores(audio, candidate_labels)
        acoustic_time = time.perf_counter() - t0
        if not acoustic:
            return {"error": "No acoustic templates for selected set."}

        best = acoustic[0]
        second = acoustic[1] if len(acoustic) > 1 else None
        margin = (second["best_distance"] - best["best_distance"]) if second else 999.0
        ratio = best["best_distance"] / (second["best_distance"] + 1e-8) if second else 0.0
        uncertain = ratio >= uncertain_ratio or margin <= uncertain_margin

        stt_raw = ""
        stt_norm = ""
        stt_time = 0.0
        used_stt = False
        if stt_engine is not None and (force_stt or uncertain):
            stt_raw, stt_norm, stt_time = stt_engine.transcribe(wav_path, stt_model)
            used_stt = True

        hybrid_scores = []
        for item in acoustic:
            bonus = self.alias_bonus(item["label"], stt_norm)
            # Lower score is better. Alias bonus lowers distance.
            adjusted = item["best_distance"] - alias_weight * bonus
            hybrid_scores.append({**item, "alias_bonus": bonus, "adjusted_distance": adjusted})
        hybrid_scores = sorted(hybrid_scores, key=lambda x: x["adjusted_distance"])

        final = hybrid_scores[0]
        final_second = hybrid_scores[1] if len(hybrid_scores) > 1 else None
        final_margin = final_second["adjusted_distance"] - final["adjusted_distance"] if final_second else 999.0

        warning = ""
        if final_second:
            for group in CONFUSION_GROUPS:
                if final["label"] in group and final_second["label"] in group:
                    warning = "Warning: top candidates are in a known vowel-confusion group."
                    break

        return {
            "predicted_label": final["label"],
            "second_label": final_second["label"] if final_second else "",
            "best_distance": best["best_distance"],
            "second_distance": second["best_distance"] if second else 0.0,
            "margin": margin,
            "ratio": ratio,
            "uncertain": uncertain,
            "used_stt": used_stt,
            "stt_raw": stt_raw,
            "stt_norm": stt_norm,
            "stt_time": stt_time,
            "acoustic_time": acoustic_time,
            "final_adjusted_distance": final["adjusted_distance"],
            "final_margin": final_margin,
            "scores": hybrid_scores,
            "warning": warning,
        }


# ============================================================
# Machine-Learning Classifier Utilities
# ============================================================

def _mfcc_stats_vector(mfcc_seq):
    """
    Convert frame-wise MFCC sequence into a fixed-length vector.
    This is much faster at recognition time than DTW over all templates.
    """
    if mfcc_seq is None or len(mfcc_seq) == 0:
        return np.zeros(39 * 6, dtype=np.float32)

    arr = np.asarray(mfcc_seq, dtype=np.float32)
    stats = [
        np.mean(arr, axis=0),
        np.std(arr, axis=0),
        np.min(arr, axis=0),
        np.max(arr, axis=0),
        np.percentile(arr, 10, axis=0),
        np.percentile(arr, 90, axis=0),
    ]
    return np.concatenate(stats).astype(np.float32)


def make_ml_feature_from_audio(audio_int16):
    """
    Feature vector for the learned model.

    Components:
    - MFCC/Delta/Delta-Delta summary statistics
    - Duration, RMS, ZCR, spectral, pitch/formant-like global sound features
    """
    mfcc_seq = extract_mfcc_features(audio_int16, SAMPLE_RATE)
    _, global_vec = extract_global_sound_features(audio_int16, SAMPLE_RATE)
    return np.concatenate([
        _mfcc_stats_vector(mfcc_seq),
        np.asarray(global_vec, dtype=np.float32),
    ]).astype(np.float32)


def make_ml_feature_from_template(template_item):
    """
    Build a model feature vector from stored calibration/feedback templates.
    Compatible with older profile formats.
    """
    if isinstance(template_item, dict):
        mfcc_seq = template_item.get("mfcc")
        global_vec = template_item.get("global_vec")
    else:
        mfcc_seq = template_item
        global_vec = None

    mfcc_vec = _mfcc_stats_vector(mfcc_seq)

    if global_vec is None:
        global_vec = np.zeros(len(GLOBAL_FEATURE_KEYS), dtype=np.float32)
    else:
        global_vec = np.asarray(global_vec, dtype=np.float32)

    return np.concatenate([mfcc_vec, global_vec]).astype(np.float32)


def ml_model_path_for_subject(subject_id):
    return BASE_DIR / subject_id / "learned_voice_model.joblib"


def collect_ml_training_data(
    subject_id,
    candidate_labels,
    gender_group="Unspecified",
    include_pooled=True,
    same_gender_only=True,
):
    """
    Collect feature vectors from the current subject and, optionally,
    other subjects as pooled training data.

    Current subject samples are weighted more strongly. Pooled samples are
    used as population-level reference data, not as a replacement for the
    subject-specific profile.
    """
    X = []
    y = []
    sample_weight = []

    subject_id_lower = subject_id.lower()
    target_group = gender_group or "Unspecified"

    for subject_dir in BASE_DIR.iterdir():
        if not subject_dir.is_dir():
            continue

        is_current = subject_dir.name.lower() == subject_id_lower

        if not is_current and not include_pooled:
            continue

        profile = VoiceProfile(subject_dir.name)
        if not profile.load():
            continue

        other_group = profile.gender_group or profile.load_metadata()
        if not is_current and same_gender_only and other_group != target_group:
            continue

        weight = 1.0 if is_current else 0.35

        for label in candidate_labels:
            for item in profile.templates.get(label, []):
                X.append(make_ml_feature_from_template(item))
                y.append(label)
                sample_weight.append(weight)

    if not X:
        return None, None, None

    return (
        np.stack(X, axis=0).astype(np.float32),
        np.asarray(y),
        np.asarray(sample_weight, dtype=np.float32),
    )


def train_learned_voice_model(
    subject_id,
    candidate_labels,
    gender_group="Unspecified",
    include_pooled=True,
    same_gender_only=True,
):
    """
    Train a small ensemble model from calibration/feedback data.

    We use RandomForest + ExtraTrees because they:
    - train quickly on small-to-medium calibration datasets
    - support nonlinear combinations of sound features
    - output class probabilities for Top-K candidate display
    - are extremely fast at prediction time
    """
    if not HAS_SKLEARN:
        raise RuntimeError("scikit-learn/joblib not installed. Run: pip install scikit-learn joblib")

    X, y, w = collect_ml_training_data(
        subject_id=subject_id,
        candidate_labels=candidate_labels,
        gender_group=gender_group,
        include_pooled=include_pooled,
        same_gender_only=same_gender_only,
    )

    if X is None or len(np.unique(y)) < 2:
        raise RuntimeError("Not enough training data. Need at least 2 labels with samples.")

    rf = RandomForestClassifier(
        n_estimators=260,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
    )
    et = ExtraTreesClassifier(
        n_estimators=260,
        max_features="sqrt",
        class_weight="balanced",
        random_state=43,
        n_jobs=-1,
    )

    rf.fit(X, y, sample_weight=w)
    et.fit(X, y, sample_weight=w)

    model_bundle = {
        "rf": rf,
        "et": et,
        "labels": sorted(list(set(y))),
        "candidate_labels": list(candidate_labels),
        "feature_dim": int(X.shape[1]),
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "subject_id": subject_id,
        "gender_group": gender_group,
        "include_pooled": include_pooled,
        "same_gender_only": same_gender_only,
        "n_samples": int(X.shape[0]),
        "n_classes": int(len(np.unique(y))),
    }

    path = ml_model_path_for_subject(subject_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_bundle, path)

    return model_bundle, path


def load_learned_voice_model(subject_id):
    if not HAS_SKLEARN:
        return None
    path = ml_model_path_for_subject(subject_id)
    if not path.exists():
        return None
    return joblib.load(path)


def predict_with_learned_voice_model(model_bundle, audio_int16, candidate_labels=None):
    """
    Return probability-ranked candidate labels.
    """
    t0 = time.perf_counter()
    x = make_ml_feature_from_audio(audio_int16).reshape(1, -1)

    rf = model_bundle["rf"]
    et = model_bundle["et"]

    rf_classes = list(rf.classes_)
    et_classes = list(et.classes_)

    prob_map = defaultdict(float)

    rf_prob = rf.predict_proba(x)[0]
    et_prob = et.predict_proba(x)[0]

    for label, p in zip(rf_classes, rf_prob):
        prob_map[label] += 0.5 * float(p)

    for label, p in zip(et_classes, et_prob):
        prob_map[label] += 0.5 * float(p)

    if candidate_labels is not None:
        allowed = set(candidate_labels)
        prob_map = {k: v for k, v in prob_map.items() if k in allowed}

    if not prob_map:
        return None

    total = sum(prob_map.values()) + 1e-12
    ranked = sorted(
        [{"label": k, "probability": v / total} for k, v in prob_map.items()],
        key=lambda d: d["probability"],
        reverse=True,
    )

    elapsed = time.perf_counter() - t0
    return ranked, elapsed



def rerank_ml_with_stt_alias(profile, ranked, stt_norm, alias_weight=0.35):
    """
    Adjust learned-model probabilities using subject-specific STT alias statistics.
    This replaces the old DTW fallback: no template DTW is performed.
    """
    if not stt_norm:
        return ranked

    adjusted = []
    for item in ranked:
        label = item["label"]
        p = float(item["probability"])
        alias = float(profile.alias_bonus(label, stt_norm))
        # Probability-space bonus. Keep it conservative so acoustic ML remains primary.
        p2 = p + alias_weight * alias
        adjusted.append({
            "label": label,
            "probability": p2,
            "raw_ml_probability": p,
            "stt_alias_score": alias,
        })

    total = sum(x["probability"] for x in adjusted) + 1e-12
    for x in adjusted:
        x["probability"] = x["probability"] / total

    adjusted = sorted(adjusted, key=lambda d: d["probability"], reverse=True)
    return adjusted


def learned_model_result_dict(
    ranked,
    ml_time,
    voice_rt,
    wav_path,
    noise_rms,
    energy_threshold,
    recorded_duration,
    gender_group,
    use_pooled,
    same_gender_only,
    pooled_penalty,
):
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else {"label": "", "probability": 0.0}

    top_prob = float(best["probability"])
    second_prob = float(second["probability"])

    scores = []
    for item in ranked:
        p = float(item["probability"])
        scores.append({
            "label": item["label"],
            "best_distance": 1.0 - p,
            "mfcc_distance": 0.0,
            "global_distance": 0.0,
            "avg_distance": 1.0 - p,
            "template_count": 0,
            "alias_bonus": 0.0,
            "adjusted_distance": 1.0 - p,
            "ml_probability": p,
        })

    return {
        "predicted_label": best["label"],
        "second_label": second["label"],
        "best_distance": 1.0 - top_prob,
        "second_distance": 1.0 - second_prob,
        "margin": top_prob - second_prob,
        "ratio": (1.0 - top_prob) / ((1.0 - second_prob) + 1e-8),
        "uncertain": False,
        "used_stt": False,
        "stt_raw": "",
        "stt_norm": "",
        "stt_time": 0.0,
        "used_dtw": False,
        "acoustic_time": ml_time,
        "final_adjusted_distance": 1.0 - top_prob,
        "final_margin": top_prob - second_prob,
        "scores": scores,
        "warning": "",
        "used_ml_model": True,
        "ml_confidence": top_prob,
        "ml_time": ml_time,
        "voice_rt": voice_rt,
        "wav_path": str(wav_path),
        "noise_rms": noise_rms,
        "energy_threshold": energy_threshold,
        "recorded_duration": recorded_duration,
        "gender_group": gender_group,
        "use_pooled": use_pooled,
        "same_gender_only": same_gender_only,
        "pooled_penalty": pooled_penalty,
        "pooled_subjects": [],
    }


# ============================================================
# Worker Classes
# ============================================================

class CalibrationWorker(QThread):
    status = Signal(str)
    finished_one = Signal(str, int, str)
    finished_all = Signal()

    def __init__(self, subject_id, labels, reps, recorder_settings, use_stt_alias=True, stt_model="tiny", gender_group="Unspecified"):
        super().__init__()
        self.subject_id = subject_id
        self.labels = labels
        self.reps = reps
        self.recorder_settings = recorder_settings
        self.use_stt_alias = use_stt_alias
        self.stt_model = stt_model
        self.gender_group = gender_group or "Unspecified"
        self.profile = VoiceProfile(subject_id, gender_group=self.gender_group)
        self.recorder = AudioRecorder(**recorder_settings)
        self.stt_engine = STTEngine() if use_stt_alias else None

    def run(self):
        self.status.emit(f"Calibration started. Gender/Group: {self.gender_group}")
        if self.profile.load():
            self.profile.gender_group = self.gender_group
            self.profile.save_metadata()
            self.status.emit("Existing profile loaded. New samples will be added.")

        if self.use_stt_alias:
            self.status.emit("Loading STT model for alias logging...")
            self.stt_engine.load(self.stt_model)

        for label in self.labels:
            for rep in range(1, self.reps + 1):
                self.status.emit(f"'{label}' 를 말해주세요. ({rep}/{self.reps})")
                time.sleep(0.5)
                audio, rt = self.recorder.record_until_silence()
                if audio is None:
                    self.status.emit(f"No speech detected: {label}. Skipped.")
                    continue

                wav_path = self.profile.wav_dir / f"calib_{label}_{rep}_{int(time.time())}.wav"
                self.recorder.save_wav(wav_path, audio, SAMPLE_RATE)

                stt_text = ""
                if self.use_stt_alias:
                    try:
                        raw, norm, stt_time = self.stt_engine.transcribe(wav_path, self.stt_model)
                        stt_text = raw
                        self.status.emit(f"STT alias for {label}: '{raw}' ({stt_time:.2f}s)")
                    except Exception as e:
                        self.status.emit(f"STT alias failed for {label}: {e}")

                self.profile.add_template(label, audio, stt_text=stt_text)
                self.finished_one.emit(label, rep, stt_text)

                noise = self.recorder.last_noise_rms
                thr = self.recorder.last_energy_threshold
                dur = self.recorder.last_duration_sec
                self.status.emit(f"Saved {label}: duration={dur:.2f}s, noise_rms={noise:.1f}, threshold={thr:.1f}")
                time.sleep(0.2)

        self.profile.save()
        self.status.emit("Calibration finished and profile saved.")
        self.finished_all.emit()


class TrainMLWorker(QThread):
    status = Signal(str)
    finished_training = Signal(bool, str)

    def __init__(
        self,
        subject_id,
        labels,
        gender_group="Unspecified",
        include_pooled=True,
        same_gender_only=True,
    ):
        super().__init__()
        self.subject_id = subject_id
        self.labels = labels
        self.gender_group = gender_group or "Unspecified"
        self.include_pooled = include_pooled
        self.same_gender_only = same_gender_only

    def run(self):
        try:
            self.status.emit("Training learned voice model...")
            model_bundle, path = train_learned_voice_model(
                subject_id=self.subject_id,
                candidate_labels=self.labels,
                gender_group=self.gender_group,
                include_pooled=self.include_pooled,
                same_gender_only=self.same_gender_only,
            )
            msg = (
                f"Model trained and saved:\n{path}\n"
                f"Samples: {model_bundle['n_samples']}, "
                f"Classes: {model_bundle['n_classes']}, "
                f"Pooled: {model_bundle['include_pooled']}, "
                f"Same group only: {model_bundle['same_gender_only']}"
            )
            self.status.emit("Learned model training finished.")
            self.finished_training.emit(True, msg)
        except Exception as e:
            self.finished_training.emit(False, str(e))


class RecognitionWorker(QThread):
    status = Signal(str)
    result_ready = Signal(dict)

    def __init__(self, subject_id, labels, recorder_settings, use_stt=True, force_stt=False, stt_model="tiny",
                 uncertain_ratio=0.90, uncertain_margin=0.45, alias_weight=0.65,
                 gender_group="Unspecified", use_pooled=False, same_gender_only=True, pooled_penalty=0.40,
                 use_ml_model=False, ml_conf_threshold=0.72, force_ml_only=False):
        super().__init__()
        self.subject_id = subject_id
        self.labels = labels
        self.recorder_settings = recorder_settings
        self.use_stt = use_stt
        self.force_stt = force_stt
        self.stt_model = stt_model
        self.uncertain_ratio = uncertain_ratio
        self.uncertain_margin = uncertain_margin
        self.alias_weight = alias_weight
        self.gender_group = gender_group or "Unspecified"
        self.use_pooled = use_pooled
        self.same_gender_only = same_gender_only
        self.pooled_penalty = pooled_penalty
        self.pooled_subjects = []
        self.profile = VoiceProfile(subject_id, gender_group=self.gender_group)
        self.recorder = AudioRecorder(**recorder_settings)
        self.stt_engine = STTEngine() if use_stt else None
        self.use_ml_model = use_ml_model
        self.ml_conf_threshold = ml_conf_threshold
        self.force_ml_only = force_ml_only

    def merge_pooled_profiles(self):
        if not self.use_pooled:
            return
        current = self.subject_id.lower()
        target_group = self.gender_group
        for subject_dir in BASE_DIR.iterdir():
            if not subject_dir.is_dir():
                continue
            if subject_dir.name.lower() == current:
                continue
            other = VoiceProfile(subject_dir.name)
            if not other.load():
                continue
            other_group = other.gender_group or other.load_metadata()
            if self.same_gender_only and other_group != target_group:
                continue
            self.profile.merge_pooled_profile(
                other_profile=other,
                candidate_labels=self.labels,
                source_name=f"pooled:{subject_dir.name}",
                distance_penalty=self.pooled_penalty,
                alias_boost=False,
            )
            self.pooled_subjects.append(f"{subject_dir.name}({other_group})")

    def run(self):
        if not self.profile.load():
            self.result_ready.emit({"error": "No profile found. Please run calibration first."})
            return

        self.profile.gender_group = self.gender_group

        # NOTE: DTW fallback is intentionally removed in this version.
        # The learned model is the primary recognizer for speed.
        if self.use_pooled:
            self.status.emit("Pooled data was used during model training, not during real-time DTW comparison.")

        model_bundle = load_learned_voice_model(self.subject_id)
        if model_bundle is None:
            self.result_ready.emit({
                "error": "No learned model found. Please click 'Train Learned Model' first."
            })
            return

        if self.use_stt:
            self.status.emit("STT will be used only when ML confidence is low or Force STT is ON.")
            self.stt_engine.load(self.stt_model)

        self.status.emit("Listening... 말하세요.")
        audio, voice_rt = self.recorder.record_until_silence()
        if audio is None:
            self.result_ready.emit({"error": "No speech detected."})
            return

        wav_path = self.profile.trial_dir / f"trial_{int(time.time())}.wav"
        self.recorder.save_wav(wav_path, audio, SAMPLE_RATE)

        self.status.emit("Predicting with learned model...")
        ml_out = predict_with_learned_voice_model(
            model_bundle=model_bundle,
            audio_int16=audio,
            candidate_labels=self.labels,
        )

        if ml_out is None:
            self.result_ready.emit({"error": "Learned model prediction failed."})
            return

        ranked, ml_time = ml_out
        ml_conf = float(ranked[0]["probability"])

        stt_raw = ""
        stt_norm = ""
        stt_time = 0.0
        used_stt = False

        # STT is optional and only used for uncertain cases.
        if self.use_stt and (self.force_stt or ml_conf < self.ml_conf_threshold):
            try:
                self.status.emit("ML confidence low; running STT alias rerank...")
                stt_raw, stt_norm, stt_time = self.stt_engine.transcribe(wav_path, self.stt_model)
                used_stt = True
                ranked = rerank_ml_with_stt_alias(
                    profile=self.profile,
                    ranked=ranked,
                    stt_norm=stt_norm,
                    alias_weight=self.alias_weight,
                )
                ml_conf = float(ranked[0]["probability"])
            except Exception as e:
                self.status.emit(f"STT rerank failed: {e}")

        result = learned_model_result_dict(
            ranked=ranked,
            ml_time=ml_time,
            voice_rt=voice_rt,
            wav_path=wav_path,
            noise_rms=self.recorder.last_noise_rms,
            energy_threshold=self.recorder.last_energy_threshold,
            recorded_duration=self.recorder.last_duration_sec,
            gender_group=self.gender_group,
            use_pooled=self.use_pooled,
            same_gender_only=self.same_gender_only,
            pooled_penalty=self.pooled_penalty,
        )

        result["used_stt"] = used_stt
        result["stt_raw"] = stt_raw
        result["stt_norm"] = stt_norm
        result["stt_time"] = stt_time
        result["used_ml_model"] = True
        result["used_dtw"] = False
        result["ml_confidence"] = ml_conf
        result["ml_conf_threshold"] = self.ml_conf_threshold
        result["force_ml_only"] = True
        result["pooled_subjects"] = []
        result["warning"] = "DTW fallback disabled. Prediction is learned-model based."

        self.result_ready.emit(result)


class ModelTestWorker(QThread):
    status = Signal(str)
    result_ready = Signal(dict)
    finished_training = Signal(str)

    def __init__(
        self,
        subject_id,
        labels,
        recorder_settings,
        gender_group="Unspecified",
        use_pooled=True,
        same_gender_only=True,
        use_stt=True,
        force_stt=False,
        stt_model="tiny",
        confidence_threshold=0.72,
        low_conf_repeats=1,
        alias_weight=0.35,
    ):
        super().__init__()
        self.subject_id = subject_id
        self.labels = list(labels)
        self.recorder_settings = recorder_settings
        self.gender_group = gender_group or "Unspecified"
        self.use_pooled = use_pooled
        self.same_gender_only = same_gender_only
        self.use_stt = use_stt
        self.force_stt = force_stt
        self.stt_model = stt_model
        self.confidence_threshold = confidence_threshold
        self.low_conf_repeats = max(1, int(low_conf_repeats))
        self.alias_weight = alias_weight

    def _record_one_for_target(self, profile, model_bundle, target_label, recorder, stt_engine=None):
        self.status.emit(f"[Model Test] Target: '{target_label}' 를 읽어주세요.")
        time.sleep(0.8)

        audio, voice_rt = recorder.record_until_silence()
        if audio is None:
            return {"error": "No speech detected.", "target_label": target_label}

        wav_path = profile.trial_dir / f"modeltest_{target_label}_{int(time.time())}.wav"
        recorder.save_wav(wav_path, audio, SAMPLE_RATE)

        ml_out = predict_with_learned_voice_model(
            model_bundle=model_bundle,
            audio_int16=audio,
            candidate_labels=self.labels,
        )
        if ml_out is None:
            return {"error": "Model prediction failed.", "target_label": target_label}

        ranked, ml_time = ml_out
        stt_raw = ""
        stt_norm = ""
        stt_time = 0.0
        used_stt = False

        conf = float(ranked[0]["probability"])
        if self.use_stt and (self.force_stt or conf < self.confidence_threshold):
            try:
                self.status.emit("[Model Test] Low confidence; running STT alias rerank...")
                stt_raw, stt_norm, stt_time = stt_engine.transcribe(wav_path, self.stt_model)
                used_stt = True
                ranked = rerank_ml_with_stt_alias(
                    profile=profile,
                    ranked=ranked,
                    stt_norm=stt_norm,
                    alias_weight=self.alias_weight,
                )
            except Exception as e:
                self.status.emit(f"[Model Test] STT failed: {e}")

        pred = ranked[0]["label"]
        conf = float(ranked[0]["probability"])
        correct = pred == target_label
        low_conf = conf < self.confidence_threshold

        # Save model-test audio as feedback if wrong or low-confidence.
        updated = False
        feedback_path = None
        if (not correct) or low_conf:
            feedback_dir = profile.subject_dir / "modeltest_feedback_wav"
            feedback_dir.mkdir(parents=True, exist_ok=True)
            feedback_path = feedback_dir / f"modeltest_{target_label}_{int(time.time())}.wav"
            recorder.save_wav(feedback_path, audio, SAMPLE_RATE)
            profile.add_template(target_label, audio, stt_text=stt_raw)
            profile.save()
            updated = True

        result = learned_model_result_dict(
            ranked=ranked,
            ml_time=ml_time,
            voice_rt=voice_rt,
            wav_path=wav_path,
            noise_rms=recorder.last_noise_rms,
            energy_threshold=recorder.last_energy_threshold,
            recorded_duration=recorder.last_duration_sec,
            gender_group=self.gender_group,
            use_pooled=self.use_pooled,
            same_gender_only=self.same_gender_only,
            pooled_penalty=0.0,
        )
        result.update({
            "target_label": target_label,
            "correct": correct,
            "low_confidence": low_conf,
            "updated_profile": updated,
            "feedback_path": str(feedback_path) if feedback_path else "",
            "used_stt": used_stt,
            "stt_raw": stt_raw,
            "stt_norm": stt_norm,
            "stt_time": stt_time,
            "ml_confidence": conf,
            "used_dtw": False,
            "used_ml_model": True,
        })
        return result

    def run(self):
        if not self.labels:
            self.result_ready.emit({"error": "No labels selected."})
            return

        profile = VoiceProfile(self.subject_id, gender_group=self.gender_group)
        if not profile.load():
            self.result_ready.emit({"error": "No profile found. Run calibration first."})
            return

        model_bundle = load_learned_voice_model(self.subject_id)
        if model_bundle is None:
            self.result_ready.emit({"error": "No learned model found. Train model first."})
            return

        stt_engine = STTEngine() if self.use_stt else None
        if stt_engine is not None:
            self.status.emit("[Model Test] Loading STT model if needed...")
            stt_engine.load(self.stt_model)

        recorder = AudioRecorder(**self.recorder_settings)
        target_label = random.choice(self.labels)

        results = []
        # First attempt
        result = self._record_one_for_target(profile, model_bundle, target_label, recorder, stt_engine)
        results.append(result)
        self.result_ready.emit(result)

        # If wrong or low confidence, the first attempt has been added to profile.
        # Retrain and optionally ask for more repeats if still low-confidence.
        needs_update = result.get("updated_profile", False)

        if needs_update:
            try:
                self.status.emit("[Model Test] Updating learned model from feedback...")
                model_bundle, path = train_learned_voice_model(
                    subject_id=self.subject_id,
                    candidate_labels=self.labels,
                    gender_group=self.gender_group,
                    include_pooled=self.use_pooled,
                    same_gender_only=self.same_gender_only,
                )
                self.finished_training.emit(f"[Model Test] Model retrained after feedback: {path}")
            except Exception as e:
                self.finished_training.emit(f"[Model Test] Retraining failed: {e}")
                return

        # If correct but low confidence, collect extra samples.
        extra_count = 0
        while result.get("low_confidence", False) and extra_count < self.low_conf_repeats:
            extra_count += 1
            self.status.emit(
                f"[Model Test] Correct but confidence is low. Extra sample {extra_count}/{self.low_conf_repeats} for '{target_label}'."
            )
            result = self._record_one_for_target(profile, model_bundle, target_label, recorder, stt_engine)
            results.append(result)
            self.result_ready.emit(result)
            try:
                model_bundle, path = train_learned_voice_model(
                    subject_id=self.subject_id,
                    candidate_labels=self.labels,
                    gender_group=self.gender_group,
                    include_pooled=self.use_pooled,
                    same_gender_only=self.same_gender_only,
                )
                self.finished_training.emit(f"[Model Test] Model retrained after extra sample: {path}")
            except Exception as e:
                self.finished_training.emit(f"[Model Test] Retraining failed: {e}")
                break


# ============================================================
# GUI
# ============================================================

class KoreanVoiceTunableApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Korean Voice Hybrid Classifier - CUDA STT + Feedback")
        self.resize(980, 760)

        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Subject ID 예: S01")

        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["Unspecified", "Female", "Male", "Other/Custom"] )
        self.gender_custom_input = QLineEdit()
        self.gender_custom_input.setPlaceholderText("Custom group name")

        self.calib_set_combo = QComboBox()
        self.recog_set_combo = QComboBox()
        for name in LABEL_SETS.keys():
            self.calib_set_combo.addItem(name)
            self.recog_set_combo.addItem(name)
        self.calib_set_combo.setCurrentText("Consonants only")
        self.recog_set_combo.setCurrentText("Consonants only")

        self.rep_spin = QSpinBox()
        self.rep_spin.setRange(1, 20)
        self.rep_spin.setValue(3)

        self.stt_model_combo = QComboBox()
        self.stt_model_combo.addItems(["tiny", "base", "small"])
        self.stt_model_combo.setCurrentText("tiny")

        self.use_stt_alias_check = QCheckBox("Use STT alias during calibration")
        self.use_stt_alias_check.setChecked(True)
        self.use_stt_recog_check = QCheckBox("Use STT alias during recognition if uncertain")
        self.use_stt_recog_check.setChecked(True)
        self.force_stt_check = QCheckBox("Force STT every recognition")
        self.force_stt_check.setChecked(False)

        self.use_pooled_check = QCheckBox("Use pooled references from other subjects")
        self.use_pooled_check.setChecked(True)
        self.same_gender_check = QCheckBox("Same gender/group only")
        self.same_gender_check.setChecked(True)
        self.pooled_penalty_spin = QDoubleSpinBox()
        self.pooled_penalty_spin.setRange(0.0, 3.0)
        self.pooled_penalty_spin.setSingleStep(0.05)
        self.pooled_penalty_spin.setValue(0.40)

        # Onset controls
        self.vad_level_spin = QSpinBox(); self.vad_level_spin.setRange(0, 3); self.vad_level_spin.setValue(3)
        self.speech_frames_spin = QSpinBox(); self.speech_frames_spin.setRange(1, 10); self.speech_frames_spin.setValue(4)
        self.pre_buffer_spin = QSpinBox(); self.pre_buffer_spin.setRange(1, 40); self.pre_buffer_spin.setValue(15)
        self.end_silence_spin = QDoubleSpinBox(); self.end_silence_spin.setRange(0.2, 2.0); self.end_silence_spin.setSingleStep(0.1); self.end_silence_spin.setValue(0.8)
        self.noise_sec_spin = QDoubleSpinBox(); self.noise_sec_spin.setRange(0.0, 2.0); self.noise_sec_spin.setSingleStep(0.05); self.noise_sec_spin.setValue(0.45)
        self.energy_mult_spin = QDoubleSpinBox(); self.energy_mult_spin.setRange(1.0, 8.0); self.energy_mult_spin.setSingleStep(0.1); self.energy_mult_spin.setValue(2.5)
        self.min_rms_spin = QDoubleSpinBox(); self.min_rms_spin.setRange(0, 3000); self.min_rms_spin.setSingleStep(10); self.min_rms_spin.setValue(120)
        self.min_record_spin = QDoubleSpinBox(); self.min_record_spin.setRange(0.05, 2.0); self.min_record_spin.setSingleStep(0.05); self.min_record_spin.setValue(0.25)
        self.max_record_spin = QDoubleSpinBox(); self.max_record_spin.setRange(1.0, 10.0); self.max_record_spin.setSingleStep(0.5); self.max_record_spin.setValue(4.0)

        # Hybrid controls
        self.ratio_spin = QDoubleSpinBox(); self.ratio_spin.setRange(0.5, 1.0); self.ratio_spin.setSingleStep(0.01); self.ratio_spin.setValue(0.90)
        self.margin_spin = QDoubleSpinBox(); self.margin_spin.setRange(0.0, 3.0); self.margin_spin.setSingleStep(0.05); self.margin_spin.setValue(0.45)
        self.alias_weight_spin = QDoubleSpinBox(); self.alias_weight_spin.setRange(0.0, 3.0); self.alias_weight_spin.setSingleStep(0.05); self.alias_weight_spin.setValue(0.65)

        self.use_ml_model_check = QCheckBox("Use learned ML model first")
        self.use_ml_model_check.setChecked(True)
        self.force_ml_only_check = QCheckBox("Force ML only (fastest, no DTW fallback)")
        self.force_ml_only_check.setChecked(False)
        self.ml_conf_spin = QDoubleSpinBox(); self.ml_conf_spin.setRange(0.0, 1.0); self.ml_conf_spin.setSingleStep(0.01); self.ml_conf_spin.setValue(0.72)
        self.model_train_reps_spin = QSpinBox(); self.model_train_reps_spin.setRange(1, 20); self.model_train_reps_spin.setValue(3)
        self.model_train_retrain_spin = QSpinBox(); self.model_train_retrain_spin.setRange(1, 20); self.model_train_retrain_spin.setValue(3)
        self.model_train_lowconf_spin = QDoubleSpinBox(); self.model_train_lowconf_spin.setRange(0.0, 1.0); self.model_train_lowconf_spin.setSingleStep(0.01); self.model_train_lowconf_spin.setValue(0.75)
        self.model_train_auto_retrain_check = QCheckBox("Auto-retrain during randomized training"); self.model_train_auto_retrain_check.setChecked(True)
        self.random_train_button = QPushButton("Random Train All Labels")
        self.train_ml_button = QPushButton("Train Learned Model")
        self.model_test_button = QPushButton("Model Test: Random Prompt")
        self.low_conf_repeats_spin = QSpinBox(); self.low_conf_repeats_spin.setRange(0, 5); self.low_conf_repeats_spin.setValue(1)

        self.start_calib_button = QPushButton("Start Calibration")
        self.load_profile_button = QPushButton("Load Profile")
        self.recognize_button = QPushButton("Recognize Voice")
        self.quick_tip_button = QPushButton("Recommended Onset Settings")

        self.status_label = QLabel("Ready")
        self.text_box = QTextEdit(); self.text_box.setReadOnly(True)

        # Layouts
        top = QGridLayout()
        top.addWidget(QLabel("Subject ID"), 0, 0); top.addWidget(self.subject_input, 0, 1)
        top.addWidget(QLabel("Gender/Group"), 2, 0); top.addWidget(self.gender_combo, 2, 1)
        top.addWidget(QLabel("Custom Group"), 2, 2); top.addWidget(self.gender_custom_input, 2, 3)
        top.addWidget(QLabel("Calibration Set"), 1, 0); top.addWidget(self.calib_set_combo, 1, 1)
        top.addWidget(QLabel("Recognition Set"), 1, 2); top.addWidget(self.recog_set_combo, 1, 3)
        top.addWidget(QLabel("Reps/label"), 0, 2); top.addWidget(self.rep_spin, 0, 3)
        top.addWidget(QLabel("STT Model"), 0, 4); top.addWidget(self.stt_model_combo, 0, 5)

        onset_group = QGroupBox("Onset / Recording Controls")
        onset = QGridLayout()
        onset.addWidget(QLabel("VAD level (0 sensitive, 3 strict)"), 0, 0); onset.addWidget(self.vad_level_spin, 0, 1)
        onset.addWidget(QLabel("Speech frames required"), 0, 2); onset.addWidget(self.speech_frames_spin, 0, 3)
        onset.addWidget(QLabel("Pre-buffer frames"), 1, 0); onset.addWidget(self.pre_buffer_spin, 1, 1)
        onset.addWidget(QLabel("End silence sec"), 1, 2); onset.addWidget(self.end_silence_spin, 1, 3)
        onset.addWidget(QLabel("Noise calibration sec"), 2, 0); onset.addWidget(self.noise_sec_spin, 2, 1)
        onset.addWidget(QLabel("Energy multiplier"), 2, 2); onset.addWidget(self.energy_mult_spin, 2, 3)
        onset.addWidget(QLabel("Min RMS threshold"), 3, 0); onset.addWidget(self.min_rms_spin, 3, 1)
        onset.addWidget(QLabel("Min record sec"), 3, 2); onset.addWidget(self.min_record_spin, 3, 3)
        onset.addWidget(QLabel("Max record sec"), 4, 0); onset.addWidget(self.max_record_spin, 4, 1)
        onset_group.setLayout(onset)

        hybrid_group = QGroupBox("Hybrid Decision Controls")
        hybrid = QGridLayout()
        hybrid.addWidget(self.use_stt_alias_check, 0, 0, 1, 2)
        hybrid.addWidget(self.use_stt_recog_check, 1, 0, 1, 2)
        hybrid.addWidget(self.force_stt_check, 2, 0, 1, 2)
        hybrid.addWidget(self.use_pooled_check, 3, 0, 1, 2)
        hybrid.addWidget(self.same_gender_check, 4, 0, 1, 2)
        hybrid.addWidget(QLabel("Pooled distance penalty"), 4, 2); hybrid.addWidget(self.pooled_penalty_spin, 4, 3)
        hybrid.addWidget(QLabel("Uncertain ratio threshold"), 0, 2); hybrid.addWidget(self.ratio_spin, 0, 3)
        hybrid.addWidget(QLabel("Uncertain margin threshold"), 1, 2); hybrid.addWidget(self.margin_spin, 1, 3)
        hybrid.addWidget(QLabel("Alias weight"), 2, 2); hybrid.addWidget(self.alias_weight_spin, 2, 3)
        hybrid.addWidget(self.use_ml_model_check, 5, 0, 1, 2)
        hybrid.addWidget(self.force_ml_only_check, 6, 0, 1, 2)
        hybrid.addWidget(QLabel("ML confidence threshold"), 5, 2); hybrid.addWidget(self.ml_conf_spin, 5, 3)
        hybrid.addWidget(QLabel("Random train reps/label"), 7, 0); hybrid.addWidget(self.model_train_reps_spin, 7, 1)
        hybrid.addWidget(QLabel("Retrain every N feedbacks"), 7, 2); hybrid.addWidget(self.model_train_retrain_spin, 7, 3)
        hybrid.addWidget(QLabel("Low-confidence threshold"), 8, 0); hybrid.addWidget(self.model_train_lowconf_spin, 8, 1)
        hybrid.addWidget(self.model_train_auto_retrain_check, 8, 2, 1, 2)
        hybrid.addWidget(QLabel("Extra samples if low confidence"), 6, 2); hybrid.addWidget(self.low_conf_repeats_spin, 6, 3)
        hybrid_group.setLayout(hybrid)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_calib_button)
        buttons.addWidget(self.load_profile_button)
        buttons.addWidget(self.recognize_button)
        buttons.addWidget(self.train_ml_button)
        buttons.addWidget(self.random_train_button)
        buttons.addWidget(self.model_test_button)
        buttons.addWidget(self.quick_tip_button)

        feedback_group = QGroupBox("Top-5 Feedback / Online Adaptation")
        feedback_layout = QVBoxLayout()
        feedback_layout.addWidget(QLabel("인식 후 Top 후보 버튼 중 실제 정답을 누르면, 해당 발화가 그 label의 추가 calibration sample로 저장됩니다."))
        feedback_button_row = QHBoxLayout()
        self.feedback_status_label = QLabel("Feedback: recognition 후 Top 후보 중 실제 정답을 선택하세요.")
        self.manual_feedback_input = QLineEdit()
        self.manual_feedback_input.setPlaceholderText("Top 후보에 정답이 없으면 직접 입력하세요. 예: 기역, 아, 학교")
        self.manual_feedback_button = QPushButton("Apply Manual Correction")
        self.manual_feedback_button.clicked.connect(self.apply_manual_feedback)
        self.manual_feedback_input.returnPressed.connect(self.apply_manual_feedback)
        self.feedback_buttons = []
        for i in range(5):
            btn = QPushButton(f"Candidate {i+1}")
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked=False, idx=i: self.apply_feedback(idx))
            self.feedback_buttons.append(btn)
            feedback_button_row.addWidget(btn)
        feedback_layout.addLayout(feedback_button_row)
        feedback_layout.addWidget(self.feedback_status_label)
        feedback_layout.addWidget(self.manual_feedback_input)
        feedback_layout.addWidget(self.manual_feedback_button)
        feedback_group.setLayout(feedback_layout)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(onset_group)
        layout.addWidget(hybrid_group)
        layout.addLayout(buttons)
        layout.addWidget(feedback_group)
        layout.addWidget(self.status_label)
        layout.addWidget(self.text_box)
        self.setLayout(layout)

        self.start_calib_button.clicked.connect(self.start_calibration)
        self.load_profile_button.clicked.connect(self.load_profile)
        self.recognize_button.clicked.connect(self.recognize_voice)
        self.train_ml_button.clicked.connect(self.train_learned_model)
        self.random_train_button.clicked.connect(self.start_random_label_training)
        self.model_test_button.clicked.connect(self.start_model_test)
        self.quick_tip_button.clicked.connect(self.show_recommended_settings)
        self.last_trial_audio_path = None
        self.last_trial_stt_text = ""
        self.last_trial_stt_norm = ""
        self.last_trial_result = None
        self.random_train_queue = []
        self.random_train_total = 0
        self.random_train_done = 0
        self.random_train_feedback_count = 0
        self.current_random_train_label = None
        self.random_train_active = False
        self.pending_next_random_train = False

    def get_subject_id(self):
        sid = self.subject_input.text().strip()
        if not sid:
            QMessageBox.warning(self, "Missing Subject ID", "Subject ID를 입력해주세요.")
            return None
        return sid

    def get_gender_group(self):
        group = self.gender_combo.currentText()
        if group == "Other/Custom":
            custom = self.gender_custom_input.text().strip()
            return custom if custom else "Other/Custom"
        return group

    def get_recorder_settings(self):
        return {
            "sample_rate": SAMPLE_RATE,
            "frame_ms": FRAME_MS,
            "vad_level": self.vad_level_spin.value(),
            "speech_frames_required": self.speech_frames_spin.value(),
            "pre_buffer_frames": self.pre_buffer_spin.value(),
            "max_wait_sec": 8.0,
            "max_record_sec": self.max_record_spin.value(),
            "end_silence_sec": self.end_silence_spin.value(),
            "noise_calibration_sec": self.noise_sec_spin.value(),
            "energy_multiplier": self.energy_mult_spin.value(),
            "min_energy_rms": self.min_rms_spin.value(),
            "min_record_sec": self.min_record_spin.value(),
        }

    def selected_calib_labels(self):
        return LABEL_SETS[self.calib_set_combo.currentText()]

    def selected_recog_labels(self):
        return LABEL_SETS[self.recog_set_combo.currentText()]

    def _save_feedback_wav_copy(self, src_wav_path, dst_wav_path):
        dst_wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(src_wav_path), "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
        with wave.open(str(dst_wav_path), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(frames)

    def _load_wav_int16(self, wav_path):
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
        return audio

    def _add_feedback_template_compatible(
        self,
        profile,
        label,
        audio,
        feedback_path,
        stt_text="",
        stt_norm="",
    ):
        try:
            profile.add_template(
                label,
                audio,
                str(feedback_path),
                stt_text,
                stt_norm,
            )
            return
        except TypeError:
            pass

        try:
            profile.add_template(
                label,
                audio,
                stt_text,
                stt_norm,
            )
            return
        except TypeError:
            pass

        try:
            profile.add_template(
                label,
                audio,
            )
            if stt_norm and hasattr(profile, "alias_counts"):
                profile.alias_counts[label][stt_norm] += 1
            return
        except TypeError as e:
            raise e

    def apply_manual_feedback(self):
        if not hasattr(self, "manual_feedback_input"):
            return

        label = self.manual_feedback_input.text().strip()

        if not label:
            QMessageBox.warning(
                self,
                "Missing correction label",
                "직접 입력할 정답 label을 입력해주세요.",
            )
            return

        if not getattr(self, "last_trial_audio_path", None):
            QMessageBox.warning(
                self,
                "No trial audio",
                "먼저 Recognize Voice를 실행한 뒤 correction을 적용해주세요.",
            )
            return

        try:
            trial_wav_path = Path(self.last_trial_audio_path)
            if not trial_wav_path.exists():
                QMessageBox.warning(
                    self,
                    "Missing WAV file",
                    f"저장된 trial wav 파일을 찾을 수 없습니다:\n{trial_wav_path}",
                )
                return

            subject_id = self.get_subject_id()
            if subject_id is None:
                return

            gender_group = "Unspecified"
            if hasattr(self, "gender_combo"):
                gender_group = self.gender_combo.currentText()

            try:
                profile = VoiceProfile(subject_id, gender_group=gender_group)
            except TypeError:
                profile = VoiceProfile(subject_id)

            if not profile.load():
                QMessageBox.warning(
                    self,
                    "No profile",
                    "프로필을 불러올 수 없습니다. 먼저 calibration을 진행해주세요.",
                )
                return

            feedback_dir = profile.subject_dir / "feedback_wav"
            feedback_dir.mkdir(parents=True, exist_ok=True)
            safe_label = label.replace("/", "_").replace("\\", "_").replace(" ", "")
            feedback_path = feedback_dir / f"manual_{safe_label}_{int(time.time())}.wav"

            self._save_feedback_wav_copy(trial_wav_path, feedback_path)
            audio = self._load_wav_int16(feedback_path)

            stt_text = getattr(self, "last_trial_stt_text", "")
            stt_norm = getattr(self, "last_trial_stt_norm", "")

            self._add_feedback_template_compatible(
                profile=profile,
                label=label,
                audio=audio,
                feedback_path=feedback_path,
                stt_text=stt_text,
                stt_norm=stt_norm,
            )

            profile.save()

            if hasattr(self, "feedback_status_label"):
                self.feedback_status_label.setText(f"Manual feedback saved: {label}")

            self.text_box.append("\n[Manual Correction]")
            self.text_box.append(f"Manual feedback saved: {label}")
            self.text_box.append(f"WAV: {feedback_path}")
            self.text_box.append(f"STT alias: {stt_text if stt_text else '-'}")

            self.manual_feedback_input.clear()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Manual feedback error",
                str(e),
            )



    def set_buttons_enabled(self, enabled):
        self.start_calib_button.setEnabled(enabled)
        self.load_profile_button.setEnabled(enabled)
        self.recognize_button.setEnabled(enabled)
        self.random_train_button.setEnabled(enabled)
        self.train_ml_button.setEnabled(enabled)
        self.model_test_button.setEnabled(enabled)
        self.quick_tip_button.setEnabled(enabled)

    def reset_feedback_buttons(self):
        for i, btn in enumerate(self.feedback_buttons):
            btn.setText(f"Candidate {i+1}")
            btn.setEnabled(False)
            btn.setProperty("label", "")
        self.feedback_status_label.setText("Feedback: recognition을 먼저 실행하세요.")

    def update_feedback_buttons(self, scores):
        for i, btn in enumerate(self.feedback_buttons):
            if i < len(scores):
                label = scores[i].get("label", "")
                adjusted = scores[i].get("adjusted_distance", scores[i].get("best_distance", 0.0))
                btn.setText(f"{i+1}. {label}\n{adjusted:.3f}")
                btn.setProperty("label", label)
                btn.setEnabled(True)
            else:
                btn.setText(f"Candidate {i+1}")
                btn.setProperty("label", "")
                btn.setEnabled(False)
        self.feedback_status_label.setText("실제 정답에 해당하는 Top 후보 버튼을 누르면 profile에 즉시 반영됩니다.")

    def apply_feedback(self, idx):
        if not self.last_result:
            self.feedback_status_label.setText("Feedback 실패: recognition 결과가 없습니다.")
            return
        if idx >= len(self.feedback_buttons):
            return
        label = self.feedback_buttons[idx].property("label")
        if not label:
            self.feedback_status_label.setText("Feedback 실패: 선택된 label이 없습니다.")
            return
        sid = self.get_subject_id()
        if sid is None:
            return
        wav_path = self.last_result.get("wav_path", "")
        if not wav_path or not Path(wav_path).exists():
            self.feedback_status_label.setText("Feedback 실패: 저장된 trial wav를 찾을 수 없습니다.")
            return
        try:
            audio = read_wav_int16(wav_path)
            profile = VoiceProfile(sid, gender_group=self.get_gender_group())
            if not profile.load():
                self.feedback_status_label.setText("Feedback 실패: profile을 먼저 calibration 해주세요.")
                return
            profile.gender_group = self.get_gender_group()
            stt_text = self.last_result.get("stt_raw", "") or ""
            profile.add_template(label, audio, stt_text=stt_text)

            feedback_dir = profile.subject_dir / "feedback_wav"
            feedback_dir.mkdir(parents=True, exist_ok=True)
            feedback_wav = feedback_dir / f"feedback_{label}_{int(time.time())}.wav"
            AudioRecorder.save_wav(feedback_wav, audio, SAMPLE_RATE)
            profile.save()

            self.feedback_status_label.setText(f"Feedback saved: '{label}' sample 추가 완료")
            self.text_box.append(f"\n[Feedback] Trial wav를 '{label}'의 추가 calibration sample로 저장했습니다: {feedback_wav}")
            self.text_box.append("[Feedback] 다음 recognition부터 해당 sample이 반영됩니다.")
        except Exception as e:
            self.feedback_status_label.setText(f"Feedback error: {e}")
            self.text_box.append(f"\n[Feedback Error] {e}")



    def start_model_test(self):
        self.last_result = None
        self.reset_feedback_buttons()

        sid = self.get_subject_id()
        if sid is None:
            return

        labels = self.selected_recog_labels()

        if len(labels) < 2:
            QMessageBox.warning(self, "Need labels", "모델 테스트에는 최소 2개 이상의 label이 필요합니다.")
            return

        self.text_box.append("\n[Model Test]")
        self.text_box.append("랜덤으로 제시되는 label을 읽어주세요.")
        self.text_box.append("틀리거나 confidence가 낮으면 해당 발화를 정답 label로 저장하고 모델을 재학습합니다.")

        self.set_buttons_enabled(False)

        self.model_test_worker = ModelTestWorker(
            subject_id=sid,
            labels=labels,
            recorder_settings=self.get_recorder_settings(),
            gender_group=self.get_gender_group(),
            use_pooled=self.use_pooled_check.isChecked(),
            same_gender_only=self.same_gender_check.isChecked(),
            use_stt=self.use_stt_recog_check.isChecked(),
            force_stt=self.force_stt_check.isChecked(),
            stt_model=self.stt_model_combo.currentText(),
            confidence_threshold=self.ml_conf_spin.value(),
            low_conf_repeats=self.low_conf_repeats_spin.value(),
            alias_weight=self.alias_weight_spin.value(),
        )

        self.model_test_worker.status.connect(self.status_label.setText)
        self.model_test_worker.status.connect(self.text_box.append)
        self.model_test_worker.result_ready.connect(self.show_model_test_result)
        self.model_test_worker.finished_training.connect(self.text_box.append)
        self.model_test_worker.finished.connect(lambda: self.set_buttons_enabled(True))
        self.model_test_worker.start()

    def show_model_test_result(self, result):
        if "error" in result:
            self.status_label.setText("Model test error")
            self.text_box.append(f"\n[Model Test Error] {result['error']}")
            return

        self.last_result = result
        self.last_trial_result = result
        self.last_trial_audio_path = result.get("wav_path")
        self.last_trial_stt_text = result.get("stt_raw", "")
        self.last_trial_stt_norm = result.get("stt_norm", "")
        self.update_feedback_buttons(result.get("scores", [])[:5])

        target = result.get("target_label", "")
        pred = result.get("predicted_label", "")
        conf = result.get("ml_confidence", 0.0)
        correct = result.get("correct", False)
        low_conf = result.get("low_confidence", False)

        self.text_box.append("\n==============================")
        self.text_box.append("Model Test Result")
        self.text_box.append("==============================")
        self.text_box.append(f"Target prompt: {target}")
        self.text_box.append(f"Predicted: {pred}")
        self.text_box.append(f"Correct: {correct}")
        self.text_box.append(f"ML confidence: {conf:.3f}")
        self.text_box.append(f"Low confidence: {low_conf}")
        self.text_box.append(f"Updated profile: {result.get('updated_profile', False)}")
        if result.get("feedback_path"):
            self.text_box.append(f"Feedback saved: {result.get('feedback_path')}")
        self.text_box.append(f"Used STT: {result.get('used_stt', False)}")
        if result.get("used_stt", False):
            self.text_box.append(f"STT raw: {result.get('stt_raw', '')}")
            self.text_box.append(f"STT time: {result.get('stt_time', 0.0):.3f} s")
        self.text_box.append(f"Voice onset RT: {result.get('voice_rt', 0.0):.3f} s")
        self.text_box.append(f"Prediction time: {result.get('ml_time', 0.0):.3f} s")
        self.text_box.append("Top candidates:")
        for i, s in enumerate(result.get("scores", [])[:8], start=1):
            self.text_box.append(
                f"{i}. {s.get('label', '')} - prob={s.get('ml_probability', 0.0):.3f}, "
                f"distance={s.get('adjusted_distance', 0.0):.3f}"
            )



    def start_random_label_training(self):
        sid = self.get_subject_id()
        if sid is None:
            return

        labels = list(self.selected_recog_labels())
        if not labels:
            QMessageBox.warning(self, "No labels", "Recognition set에 label이 없습니다.")
            return

        reps = self.model_train_reps_spin.value() if hasattr(self, "model_train_reps_spin") else 3

        self.random_train_queue = []
        for _ in range(reps):
            shuffled = labels[:]
            random.shuffle(shuffled)
            self.random_train_queue.extend(shuffled)

        random.shuffle(self.random_train_queue)

        self.random_train_total = len(self.random_train_queue)
        self.random_train_done = 0
        self.random_train_feedback_count = 0
        self.random_train_active = True

        self.text_box.append("\n[Randomized Model Training]")
        self.text_box.append(f"Set: {self.recog_set_combo.currentText()}")
        self.text_box.append(f"Labels: {len(labels)}")
        self.text_box.append(f"Reps/label: {reps}")
        self.text_box.append(f"Total trials: {self.random_train_total}")
        self.text_box.append("각 trial에서 제시된 label을 읽으면 모델이 예측하고, 틀리거나 confidence가 낮으면 자동으로 feedback 저장합니다.")

        self.run_next_random_train_trial()

    def run_next_random_train_trial(self):
        if not self.random_train_queue:
            self.random_train_active = False
            self.current_random_train_label = None
            self.text_box.append("\n[Randomized Model Training Complete]")
            self.status_label.setText("Randomized training complete.")
            # final retrain
            try:
                self.train_learned_model()
            except Exception as e:
                self.text_box.append(f"Final retrain skipped/failed: {e}")
            return

        self.current_random_train_label = self.random_train_queue.pop(0)
        self.random_train_done += 1

        QMessageBox.information(
            self,
            "Random Training Trial",
            f"[{self.random_train_done}/{self.random_train_total}]\n\n"
            f"다음 label을 읽어주세요:\n\n"
            f"{self.current_random_train_label}"
        )

        self.run_random_train_recognition()


    def after_random_train_worker_finished(self):
        self.set_buttons_enabled(True)

        if getattr(self, "random_train_active", False) and getattr(self, "pending_next_random_train", False):
            self.pending_next_random_train = False
            self.run_next_random_train_trial()

    def run_random_train_recognition(self):
        sid = self.get_subject_id()
        if sid is None:
            return

        labels = self.selected_recog_labels()

        self.set_buttons_enabled(False)

        # In model training mode, force ML first if possible, but no DTW fallback is needed
        # unless ML model is absent. Existing RecognitionWorker handles fallback internally.
        self.recog_worker = RecognitionWorker(
            subject_id=sid,
            labels=labels,
            recorder_settings=self.get_recorder_settings(),
            use_stt=(getattr(self, 'use_stt_check', None).isChecked() if hasattr(self, 'use_stt_check') else (getattr(self, 'force_stt_check', None).isChecked() if hasattr(self, 'force_stt_check') else False)),
            force_stt=False,
            stt_model=self.stt_model_combo.currentText() if hasattr(self, "stt_model_combo") else "tiny",
            uncertain_ratio=self.uncertain_ratio_spin.value() if hasattr(self, "uncertain_ratio_spin") else 0.90,
            uncertain_margin=self.uncertain_margin_spin.value() if hasattr(self, "uncertain_margin_spin") else 0.45,
            alias_weight=self.alias_weight_spin.value() if hasattr(self, "alias_weight_spin") else 0.65,
            gender_group=self.get_gender_group(),
            use_pooled=self.use_pooled_check.isChecked() if hasattr(self, "use_pooled_check") else False,
            same_gender_only=self.same_gender_check.isChecked() if hasattr(self, "same_gender_check") else True,
            pooled_penalty=self.pooled_penalty_spin.value() if hasattr(self, "pooled_penalty_spin") else 0.40,
            use_ml_model=True,
            ml_conf_threshold=0.0,
            force_ml_only=True,
        )

        self.recog_worker.status.connect(self.status_label.setText)
        self.recog_worker.result_ready.connect(self.on_random_train_result)
        self.recog_worker.finished.connect(self.after_random_train_worker_finished)
        self.recog_worker.start()

    def on_random_train_result(self, result):
        self.set_buttons_enabled(True)

        if "error" in result:
            self.text_box.append(f"\n[Random Train Error] {result['error']}")
            # Requeue target once if recognition failed
            if self.current_random_train_label is not None:
                self.random_train_queue.append(self.current_random_train_label)
            self.pending_next_random_train = True
            return

        target = self.current_random_train_label
        pred = result.get("predicted_label", "")
        conf = float(result.get("ml_confidence", 0.0))
        low_conf_th = self.model_train_lowconf_spin.value() if hasattr(self, "model_train_lowconf_spin") else 0.75

        correct = (pred == target)
        low_conf = conf < low_conf_th

        self.text_box.append("\n[Random Train Result]")
        self.text_box.append(f"Target: {target}")
        self.text_box.append(f"Predicted: {pred}")
        self.text_box.append(f"Confidence: {conf:.3f}")
        self.text_box.append(f"Correct: {correct}")
        self.text_box.append(f"Low confidence: {low_conf}")

        # Store last trial info for possible manual debugging/feedback
        self.last_trial_result = result
        self.last_trial_audio_path = result.get("wav_path")
        self.last_trial_stt_text = result.get("stt_text", result.get("stt_raw", ""))
        self.last_trial_stt_norm = result.get("stt_norm", "")

        if (not correct) or low_conf:
            self._save_random_train_feedback(target, result)
            self.random_train_feedback_count += 1

            retrain_every = self.model_train_retrain_spin.value() if hasattr(self, "model_train_retrain_spin") else 3
            auto_retrain = self.model_train_auto_retrain_check.isChecked() if hasattr(self, "model_train_auto_retrain_check") else True

            if auto_retrain and self.random_train_feedback_count >= retrain_every:
                self.random_train_feedback_count = 0
                self.text_box.append("Retraining model after accumulated feedback...")
                try:
                    # Synchronous retrain is acceptable here; data size is small.
                    train_learned_voice_model(
                        subject_id=self.get_subject_id(),
                        candidate_labels=self.selected_recog_labels(),
                        gender_group=self.get_gender_group(),
                        include_pooled=self.use_pooled_check.isChecked() if hasattr(self, "use_pooled_check") else False,
                        same_gender_only=self.same_gender_check.isChecked() if hasattr(self, "same_gender_check") else True,
                    )
                    self.text_box.append("Retraining done.")
                except Exception as e:
                    self.text_box.append(f"Retraining failed: {e}")

            # If it was wrong, schedule same label again later for reinforcement.
            if not correct:
                self.random_train_queue.append(target)

        self.pending_next_random_train = True

    def _save_random_train_feedback(self, target_label, result):
        wav_path = result.get("wav_path")
        if not wav_path:
            self.text_box.append("No WAV path; feedback not saved.")
            return

        wav_path = Path(wav_path)
        if not wav_path.exists():
            self.text_box.append(f"WAV missing; feedback not saved: {wav_path}")
            return

        subject_id = self.get_subject_id()
        if subject_id is None:
            return

        try:
            profile = VoiceProfile(subject_id, gender_group=self.get_gender_group())
        except TypeError:
            profile = VoiceProfile(subject_id)

        if not profile.load():
            self.text_box.append("Profile load failed; feedback not saved.")
            return

        feedback_dir = profile.subject_dir / "modeltest_feedback_wav"
        feedback_dir.mkdir(parents=True, exist_ok=True)
        safe_label = target_label.replace("/", "_").replace("\\", "_").replace(" ", "")
        dst = feedback_dir / f"modeltest_{safe_label}_{int(time.time())}.wav"

        # copy wav and load audio
        with wave.open(str(wav_path), "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())

        with wave.open(str(dst), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(frames)

        audio = np.frombuffer(frames, dtype=np.int16)
        stt_text = result.get("stt_text", result.get("stt_raw", ""))
        stt_norm = result.get("stt_norm", "")

        # compatible add_template
        try:
            profile.add_template(target_label, audio, str(dst), stt_text, stt_norm)
        except TypeError:
            try:
                profile.add_template(target_label, audio, stt_text, stt_norm)
            except TypeError:
                profile.add_template(target_label, audio)
                if stt_norm and hasattr(profile, "alias_counts"):
                    profile.alias_counts[target_label][stt_norm] += 1

        profile.save()
        self.text_box.append(f"Feedback saved for target '{target_label}': {dst}")


    def train_learned_model(self):
        sid = self.get_subject_id()
        if sid is None:
            return

        labels = self.selected_recog_labels()

        if len(labels) < 2:
            QMessageBox.warning(self, "Need labels", "모델 학습에는 최소 2개 이상의 label이 필요합니다.")
            return

        self.text_box.append("\n[Learned Model Training]")
        self.text_box.append(f"Subject: {sid}")
        self.text_box.append(f"Training label set: {self.recog_set_combo.currentText()} ({len(labels)} labels)")
        self.text_box.append(f"Use pooled references: {self.use_pooled_check.isChecked()}")
        self.text_box.append(f"Same gender/group only: {self.same_gender_check.isChecked()}")

        self.set_buttons_enabled(False)

        self.train_ml_worker = TrainMLWorker(
            subject_id=sid,
            labels=labels,
            gender_group=self.get_gender_group(),
            include_pooled=self.use_pooled_check.isChecked(),
            same_gender_only=self.same_gender_check.isChecked(),
        )

        self.train_ml_worker.status.connect(self.status_label.setText)
        self.train_ml_worker.status.connect(self.text_box.append)
        self.train_ml_worker.finished_training.connect(self.on_train_ml_finished)
        self.train_ml_worker.start()

    def on_train_ml_finished(self, ok, message):
        self.set_buttons_enabled(True)
        if ok:
            self.status_label.setText("Learned model trained.")
            self.text_box.append(message)
        else:
            self.status_label.setText("Learned model training failed.")
            self.text_box.append(f"Model training failed: {message}")
            QMessageBox.warning(self, "Model training failed", message)


    def start_calibration(self):
        self.last_result = None
        self.reset_feedback_buttons()
        sid = self.get_subject_id()
        if sid is None:
            return
        labels = self.selected_calib_labels()
        reps = self.rep_spin.value()
        self.text_box.clear()
        self.text_box.append(f"Gender/Group: {self.get_gender_group()}")
        self.text_box.append(f"Calibration set: {self.calib_set_combo.currentText()} ({len(labels)} labels)")
        self.text_box.append(f"Reps/label: {reps} / Total: {len(labels) * reps}")
        self.text_box.append(f"Recorder settings: {self.get_recorder_settings()}\n")
        self.set_buttons_enabled(False)
        self.calib_worker = CalibrationWorker(
            subject_id=sid,
            labels=labels,
            reps=reps,
            recorder_settings=self.get_recorder_settings(),
            use_stt_alias=self.use_stt_alias_check.isChecked(),
            stt_model=self.stt_model_combo.currentText(),
            gender_group=self.get_gender_group(),
        )
        self.calib_worker.status.connect(self.status_label.setText)
        self.calib_worker.status.connect(self.text_box.append)
        self.calib_worker.finished_one.connect(self.on_calib_one)
        self.calib_worker.finished_all.connect(self.on_calib_finished)
        self.calib_worker.start()

    def on_calib_one(self, label, rep, stt_text):
        self.text_box.append(f"Saved: {label} rep {rep} | STT alias: {stt_text}")

    def on_calib_finished(self):
        self.text_box.append("\nCalibration complete.")
        self.set_buttons_enabled(True)

    def load_profile(self):
        sid = self.get_subject_id()
        if sid is None:
            return
        profile = VoiceProfile(sid)
        if profile.load():
            profile.load_metadata()
            label_count = len(profile.templates)
            sample_count = sum(len(v) for v in profile.templates.values())
            self.status_label.setText("Profile loaded.")
            self.text_box.append(f"Loaded profile for {sid}: gender/group={profile.gender_group}, labels={label_count}, samples={sample_count}")
            self.text_box.append("Alias examples:")
            for label in list(profile.alias_counts.keys())[:10]:
                self.text_box.append(f"  {label}: {dict(profile.alias_counts[label].most_common(5))}")
        else:
            self.status_label.setText("No profile found.")
            self.text_box.append(f"No profile found for {sid}. Run calibration first.")

    def recognize_voice(self):
        self.last_result = None
        self.reset_feedback_buttons()
        sid = self.get_subject_id()
        if sid is None:
            return
        labels = self.selected_recog_labels()
        self.set_buttons_enabled(False)
        self.recog_worker = RecognitionWorker(
            subject_id=sid,
            labels=labels,
            recorder_settings=self.get_recorder_settings(),
            use_stt=self.use_stt_recog_check.isChecked(),
            force_stt=self.force_stt_check.isChecked(),
            stt_model=self.stt_model_combo.currentText(),
            uncertain_ratio=self.ratio_spin.value(),
            uncertain_margin=self.margin_spin.value(),
            alias_weight=self.alias_weight_spin.value(),
            gender_group=self.get_gender_group(),
            use_pooled=self.use_pooled_check.isChecked(),
            same_gender_only=self.same_gender_check.isChecked(),
            pooled_penalty=self.pooled_penalty_spin.value(),
            use_ml_model=self.use_ml_model_check.isChecked(),
            ml_conf_threshold=self.ml_conf_spin.value(),
            force_ml_only=self.force_ml_only_check.isChecked(),
        )
        self.recog_worker.status.connect(self.status_label.setText)
        self.recog_worker.result_ready.connect(self.show_result)
        self.recog_worker.finished.connect(lambda: self.set_buttons_enabled(True))
        self.recog_worker.start()

    def show_result(self, result):
        if "error" in result:
            self.status_label.setText("Error")
            self.text_box.append(f"\nError: {result['error']}\n")
            return
        self.last_trial_result = result
        self.last_trial_audio_path = result.get("wav_path")
        self.last_trial_stt_text = result.get("stt_text", "")
        self.last_trial_stt_norm = result.get("stt_norm", "")
        if hasattr(self, "manual_feedback_input"):
            self.manual_feedback_input.clear()
        self.status_label.setText("Recognition finished.")
        self.last_result = result
        self.update_feedback_buttons(result.get("scores", [])[:5])
        self.text_box.append("\n==============================")
        self.text_box.append("Recognition Result")
        self.text_box.append("==============================")
        self.text_box.append(f"Recognition set: {self.recog_set_combo.currentText()}")
        self.text_box.append(f"Gender/Group: {result.get('gender_group', '')}")
        self.text_box.append(f"Use pooled references: {result.get('use_pooled', False)}")
        if result.get('use_pooled', False):
            self.text_box.append(f"Same gender/group only: {result.get('same_gender_only', True)}")
            self.text_box.append(f"Pooled penalty: {result.get('pooled_penalty', 0):.2f}")
            self.text_box.append(f"Pooled subjects: {', '.join(result.get('pooled_subjects', [])) if result.get('pooled_subjects') else 'None'}")
        self.text_box.append(f"Predicted label: {result['predicted_label']}")
        self.text_box.append(f"Second label: {result['second_label']}")
        self.text_box.append(f"Used learned ML model: {result.get('used_ml_model', False)}")
        if result.get('used_ml_model', False):
            self.text_box.append(f"ML confidence: {result.get('ml_confidence', 0.0):.3f}")
            self.text_box.append(f"ML prediction time: {result.get('ml_time', 0.0):.3f} s")
        self.text_box.append(f"Acoustic best distance: {result['best_distance']:.4f}")
        self.text_box.append(f"Acoustic second distance: {result['second_distance']:.4f}")
        self.text_box.append(f"Acoustic margin: {result['margin']:.4f}")
        self.text_box.append(f"Acoustic ratio: {result['ratio']:.4f}")
        self.text_box.append(f"Uncertain: {result['uncertain']}")
        self.text_box.append(f"Used STT: {result['used_stt']}")
        if result['used_stt']:
            self.text_box.append(f"STT raw: {result['stt_raw']}")
            self.text_box.append(f"STT norm: {result['stt_norm']}")
            self.text_box.append(f"STT time: {result['stt_time']:.3f} s")
        self.text_box.append(f"Final adjusted distance: {result['final_adjusted_distance']:.4f}")
        self.text_box.append(f"Final adjusted margin: {result['final_margin']:.4f}")
        self.text_box.append(f"Voice onset RT: {result['voice_rt']:.3f} s")
        self.text_box.append(f"Recorded duration: {result['recorded_duration']:.3f} s")
        self.text_box.append(f"Noise RMS: {result['noise_rms']:.1f}")
        self.text_box.append(f"Energy threshold: {result['energy_threshold']:.1f}")
        self.text_box.append(f"ML/acoustic prediction time: {result['acoustic_time']:.3f} s")
        self.text_box.append(f"WAV saved: {result['wav_path']}")
        if result.get("warning"):
            self.text_box.append(result["warning"])
        self.text_box.append("\nTop candidates shown as feedback buttons. Top 8 details:")
        for i, s in enumerate(result["scores"][:8], start=1):
            self.text_box.append(
                f"{i}. {s['label']} - acoustic={s.get('best_distance', 0):.4f}, "
                f"alias_bonus={s.get('alias_bonus', 0):.3f}, adjusted={s.get('adjusted_distance', 0):.4f}, "
                f"ml_prob={s.get('ml_probability', 0):.3f}, "
                f"templates={s.get('template_count', 0)}"
            )

    def show_recommended_settings(self):
        self.vad_level_spin.setValue(3)
        self.speech_frames_spin.setValue(4)
        self.pre_buffer_spin.setValue(15)
        self.end_silence_spin.setValue(0.8)
        self.noise_sec_spin.setValue(0.45)
        self.energy_mult_spin.setValue(2.5)
        self.min_rms_spin.setValue(120)
        self.min_record_spin.setValue(0.25)
        self.max_record_spin.setValue(4.0)
        self.text_box.append(
            "\nRecommended onset settings applied:\n"
            "- VAD level 3: stricter speech detection\n"
            "- Speech frames 4: requires ~120 ms continuous speech\n"
            "- Pre-buffer 15: keeps ~450 ms before onset, reducing clipped starts\n"
            "- End silence 0.8 s: preserves weak final sounds such as 히읗/키읔\n"
            "- Noise calibration 0.45 s + RMS gate: prevents background noise onset\n"
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KoreanVoiceTunableApp()
    window.show()
    sys.exit(app.exec())
