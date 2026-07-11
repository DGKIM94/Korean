"""
Analyze tactile consonant learning experiment logs
-------------------------------------------------
Reads all subject CSV logs and generates per-subject and group-level analysis.

Main outcomes
1) Trials/time to 90% criterion: recent 27 trials >= 25 correct
2) Retention accuracy by condition
3) Learning curves by condition
4) Symbol-wise and position-wise learning curves
5) Symbol-vs-position influence summary
6) Voice onset RT summaries and curves
7) Exposure counts until each consonant/position is learned
8) Voice reaction time by consonant and position

Expected CSV columns from tactile_consonant_learning_app_v11/v12:
subject_id, session_id, condition_index, condition_name, condition_score,
phase, trial_global, trial_in_condition, mini_block, position, motor_id,
correct_symbol, response_symbol, is_correct, voice_onset_rt_sec,
response_confirm_rt_sec, timestamp

Usage
-----
python analyze_tactile_consonant_learning_v7_rt_by_item.py --data-dir data/logs --out-dir analysis_results

If your CSV files are somewhere else:
python analyze_tactile_consonant_learning_v7_rt_by_item.py --data-dir C:\path\to\logs --out-dir C:\path\to\analysis_results
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm




def safe_mean_correct_rt(series: pd.Series, reference_df: pd.DataFrame) -> float:
    """Mean voice-onset RT for correct trials only, without empty-slice warnings."""
    if series is None or len(series) == 0:
        return np.nan
    try:
        correct_mask = reference_df.loc[series.index, "is_correct"] == 1
        vals = pd.to_numeric(series[correct_mask], errors="coerce").dropna()
        if vals.empty:
            return np.nan
        return float(vals.mean())
    except Exception:
        vals = pd.to_numeric(series, errors="coerce").dropna()
        if vals.empty:
            return np.nan
        return float(vals.mean())


def setup_korean_font():
    """Force a Korean-capable matplotlib font.

    Windows often has Malgun Gothic installed, but matplotlib may still fall
    back to DejaVu Sans if only the family name is provided. This function first
    tries explicit font-file paths, then falls back to installed font names.
    """
    import platform
    from pathlib import Path as _Path
    import matplotlib as mpl

    # 1) Explicit font-file paths. This is the most reliable on Windows.
    font_paths = [
        r"C:\Windows\Fonts\malgun.ttf",      # Malgun Gothic regular
        r"C:\Windows\Fonts\malgunbd.ttf",    # Malgun Gothic bold
        r"C:\Windows\Fonts\NanumGothic.ttf",
        r"/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        r"/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        r"/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for fp in font_paths:
        p = _Path(fp)
        if p.exists():
            try:
                fm.fontManager.addfont(str(p))
                font_name = fm.FontProperties(fname=str(p)).get_name()
                mpl.rcParams["font.family"] = font_name
                mpl.rcParams["font.sans-serif"] = [font_name]
                mpl.rcParams["axes.unicode_minus"] = False
                return f"{font_name} ({p})"
            except Exception:
                pass

    # 2) Fallback to family names already known to matplotlib.
    candidates = [
        "Malgun Gothic",       # Windows
        "맑은 고딕",
        "NanumGothic",
        "Noto Sans CJK KR",
        "Noto Sans KR",
        "AppleGothic",         # macOS
        "Arial Unicode MS",
    ]
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            mpl.rcParams["font.family"] = name
            mpl.rcParams["font.sans-serif"] = [name]
            mpl.rcParams["axes.unicode_minus"] = False
            return name

    mpl.rcParams["axes.unicode_minus"] = False
    return None


def df_to_markdown_simple(df: pd.DataFrame) -> str:
    """Small markdown-table writer that does not require the tabulate package."""
    if df is None or df.empty:
        return "_No rows._"
    temp = df.copy()
    # Keep the report readable. Round floats but preserve IDs/strings.
    for c in temp.columns:
        if pd.api.types.is_float_dtype(temp[c]):
            temp[c] = temp[c].map(lambda x: "" if pd.isna(x) else f"{x:.3f}")
        else:
            temp[c] = temp[c].map(lambda x: "" if pd.isna(x) else str(x))
    headers = [str(c) for c in temp.columns]
    rows = temp.values.tolist()
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        # Escape pipes inside cells.
        cells = [str(x).replace("|", "\|") for x in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


try:
    import statsmodels.formula.api as smf
    HAS_STATSMODELS = True
except Exception:
    HAS_STATSMODELS = False

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_CRITERION_WINDOW = 27
DEFAULT_CRITERION_CORRECT = 25
DEFAULT_RETENTION_TRIALS = 18
SYMBOL_ORDER = ["기역", "니은", "디귿", "리을", "미음", "비읍", "시옷", "이응", "지읒"]
CONDITION_ORDER_NOMINAL = [
    "C1_PhoneLike",
    "C2_KeyboardLike",
    "C3_MediumA",
    "C4_MediumB",
    "C5_LowA",
    "C6_LowB",
]
CONDITION_TYPE = {
    "C1_PhoneLike": "High-schema",
    "C2_KeyboardLike": "High-schema",
    "C3_MediumA": "Medium-order",
    "C4_MediumB": "Medium-order",
    "C5_LowA": "Low-order",
    "C6_LowB": "Low-order",
}

# Logical grid position helper
POSITION_LABEL = {
    1: "P1 wrist-left", 2: "P2 wrist-center", 3: "P3 wrist-right",
    4: "P4 mid-left", 5: "P5 mid-center", 6: "P6 mid-right",
    7: "P7 elbow-left", 8: "P8 elbow-center", 9: "P9 elbow-right",
}

# -----------------------------------------------------------------------------
# IO and cleaning
# -----------------------------------------------------------------------------

def find_csv_files(data_dir: Path, recursive: bool = True) -> List[Path]:
    if not data_dir.exists():
        raise FileNotFoundError(f"data-dir does not exist: {data_dir}")
    patterns = ["*.csv"] if not recursive else ["**/*.csv"]
    files: List[Path] = []
    for pat in patterns:
        files.extend(data_dir.glob(pat))
    # exclude our own outputs if user points to a broad root
    files = [f for f in files if not any(part.lower().startswith("analysis") for part in f.parts)]
    return sorted(set(files))


def read_csv_safely(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            df = pd.read_csv(path, encoding=enc)
            df["source_file"] = str(path)
            return df
        except Exception:
            continue
    # final fallback
    df = pd.read_csv(path, encoding_errors="replace")
    df["source_file"] = str(path)
    return df


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Add missing expected columns.
    expected = [
        "subject_id", "session_id", "condition_index", "condition_name", "condition_score",
        "phase", "trial_global", "trial_in_condition", "mini_block", "position", "motor_id",
        "correct_symbol", "correct_consonant", "response_symbol", "response_source", "is_correct",
        "voice_onset_rt_sec", "response_confirm_rt_sec", "top5_json", "timestamp",
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = np.nan

    # Type conversions.
    for c in ["subject_id", "condition_index", "condition_score", "trial_global", "trial_in_condition", "mini_block", "position", "motor_id", "is_correct"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["voice_onset_rt_sec", "response_confirm_rt_sec", "timestamp"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["phase"] = df["phase"].astype(str).str.strip().str.lower()
    df.loc[~df["phase"].isin(["learning", "retention"]), "phase"] = "learning"
    df["condition_name"] = df["condition_name"].astype(str).str.strip()
    df["correct_symbol"] = df["correct_symbol"].astype(str).str.strip()
    df["response_symbol"] = df["response_symbol"].astype(str).str.strip()

    # If condition index missing but condition_name present, infer.
    cond_to_idx = {name: i + 1 for i, name in enumerate(CONDITION_ORDER_NOMINAL)}
    missing_idx = df["condition_index"].isna() | (df["condition_index"] <= 0)
    df.loc[missing_idx, "condition_index"] = df.loc[missing_idx, "condition_name"].map(cond_to_idx)

    # If condition score missing, infer.
    score_map = {
        "C1_PhoneLike": 8, "C2_KeyboardLike": 8,
        "C3_MediumA": 4, "C4_MediumB": 4,
        "C5_LowA": 1, "C6_LowB": 1,
    }
    missing_score = df["condition_score"].isna() | (df["condition_score"] < 0)
    df.loc[missing_score, "condition_score"] = df.loc[missing_score, "condition_name"].map(score_map)

    # Drop rows that are not actual trial rows.
    df = df[df["condition_index"].notna() & df["condition_name"].notna()]
    df = df[df["position"].notna()]

    # Fill subject from filename if missing.
    if df["subject_id"].isna().any():
        def subj_from_file(s: str):
            m = re.search(r"subject[_-]?(\d+)", s, flags=re.I)
            return int(m.group(1)) if m else np.nan
        inferred = df["source_file"].map(subj_from_file)
        df["subject_id"] = df["subject_id"].fillna(inferred)

    df["subject_id"] = df["subject_id"].astype("Int64")
    df["condition_index"] = df["condition_index"].astype("Int64")
    df["condition_score"] = df["condition_score"].astype("Int64")
    df["position"] = df["position"].astype("Int64")
    df["is_correct"] = df["is_correct"].fillna(0).astype(int)

    df["condition_type"] = df["condition_name"].map(CONDITION_TYPE).fillna("Other")
    df["position_label"] = df["position"].astype(float).astype("Int64").map(POSITION_LABEL)

    # Stable sort within files/subjects.
    sort_cols = ["subject_id", "session_id", "trial_global", "timestamp"]
    df = df.sort_values(sort_cols, na_position="last").reset_index(drop=True)
    return df


def load_all_logs(data_dir: Path, recursive: bool = True) -> pd.DataFrame:
    files = find_csv_files(data_dir, recursive=recursive)
    if not files:
        raise FileNotFoundError(f"No CSV files found under: {data_dir}")
    frames = []
    for f in files:
        try:
            frames.append(read_csv_safely(f))
        except Exception as e:
            print(f"[WARN] Failed to read {f}: {e}")
    if not frames:
        raise RuntimeError("No readable CSV files.")
    df = pd.concat(frames, ignore_index=True, sort=False)
    return normalize_columns(df)

# -----------------------------------------------------------------------------
# Core analyses
# -----------------------------------------------------------------------------

def add_learning_indices(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["learning_trial_index"] = np.nan
    df["retention_trial_index"] = np.nan
    df["symbol_exposure_index"] = np.nan
    df["position_exposure_index"] = np.nan

    group_cols = ["subject_id", "session_id", "condition_name"]
    for _, idx in df.groupby(group_cols, dropna=False).groups.items():
        sub = df.loc[idx].sort_values(["trial_global", "timestamp"])
        learn_idx = sub[sub["phase"] == "learning"].index
        ret_idx = sub[sub["phase"] == "retention"].index
        df.loc[learn_idx, "learning_trial_index"] = np.arange(1, len(learn_idx) + 1)
        df.loc[ret_idx, "retention_trial_index"] = np.arange(1, len(ret_idx) + 1)

        # Exposure count during learning only.
        ldf = df.loc[learn_idx].copy()
        if len(ldf):
            df.loc[learn_idx, "symbol_exposure_index"] = ldf.groupby("correct_symbol").cumcount().values + 1
            df.loc[learn_idx, "position_exposure_index"] = ldf.groupby("position").cumcount().values + 1

    df["mini_block_calc"] = np.ceil(df["learning_trial_index"] / 9.0)
    return df


def first_criterion_trial(learning: pd.DataFrame, window: int, correct_needed: int) -> Tuple[Optional[int], Optional[float], Optional[int]]:
    """Return learning trial index, elapsed seconds, and global trial when criterion first met."""
    if learning.empty or len(learning) < window:
        return None, None, None
    learning = learning.sort_values(["learning_trial_index", "trial_global", "timestamp"])
    correct = learning["is_correct"].astype(int).to_numpy()
    roll = pd.Series(correct).rolling(window=window, min_periods=window).sum().to_numpy()
    hits = np.where(roll >= correct_needed)[0]
    if len(hits) == 0:
        return None, None, None
    hit_pos = int(hits[0])  # zero-based index in learning df
    row = learning.iloc[hit_pos]
    trial_idx = int(row["learning_trial_index"])
    global_trial = int(row["trial_global"]) if pd.notna(row["trial_global"]) else None
    ts0 = learning["timestamp"].dropna().min()
    if pd.notna(row.get("timestamp", np.nan)) and pd.notna(ts0):
        elapsed = float(row["timestamp"] - ts0)
    else:
        elapsed = None
    return trial_idx, elapsed, global_trial


def summarize_subject_condition(df: pd.DataFrame, window: int, correct_needed: int) -> pd.DataFrame:
    rows = []
    group_cols = ["subject_id", "session_id", "condition_index", "condition_name"]
    for key, sub in df.groupby(group_cols, dropna=False):
        sid, sess, cidx, cname = key
        sub = sub.sort_values(["trial_global", "timestamp"])
        learning = sub[sub["phase"] == "learning"].copy()
        retention = sub[sub["phase"] == "retention"].copy()
        crit_trial, crit_time, crit_global = first_criterion_trial(learning, window, correct_needed)
        reached = crit_trial is not None
        final18 = learning.tail(18)
        final27 = learning.tail(27)
        early18 = learning.head(18)
        rows.append({
            "subject_id": sid,
            "session_id": sess,
            "condition_index": int(cidx) if pd.notna(cidx) else np.nan,
            "condition_name": cname,
            "condition_type": CONDITION_TYPE.get(cname, "Other"),
            "condition_score": int(learning["condition_score"].dropna().iloc[0]) if len(learning) and learning["condition_score"].notna().any() else np.nan,
            "n_learning_trials": int(len(learning)),
            "criterion_reached": int(reached),
            "trials_to_criterion": crit_trial,
            "time_to_criterion_sec": crit_time,
            "global_trial_at_criterion": crit_global,
            "early18_accuracy": float(early18["is_correct"].mean()) if len(early18) else np.nan,
            "final18_accuracy": float(final18["is_correct"].mean()) if len(final18) else np.nan,
            "final27_accuracy": float(final27["is_correct"].mean()) if len(final27) else np.nan,
            "learning_accuracy_all": float(learning["is_correct"].mean()) if len(learning) else np.nan,
            "learning_rt_mean_correct": float(learning.loc[learning["is_correct"] == 1, "voice_onset_rt_sec"].mean()) if len(learning) else np.nan,
            "learning_rt_median_correct": float(learning.loc[learning["is_correct"] == 1, "voice_onset_rt_sec"].median()) if len(learning) else np.nan,
            "n_retention_trials": int(len(retention)),
            "retention_accuracy": float(retention["is_correct"].mean()) if len(retention) else np.nan,
            "retention_rt_mean_correct": float(retention.loc[retention["is_correct"] == 1, "voice_onset_rt_sec"].mean()) if len(retention) else np.nan,
        })
    return pd.DataFrame(rows).sort_values(["subject_id", "condition_index"])


def summarize_group(subject_summary: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "criterion_reached", "trials_to_criterion", "time_to_criterion_sec",
        "n_learning_trials", "early18_accuracy", "final18_accuracy", "final27_accuracy",
        "learning_accuracy_all", "learning_rt_mean_correct", "retention_accuracy", "retention_rt_mean_correct",
    ]
    rows = []
    for cname, sub in subject_summary.groupby("condition_name"):
        row = {
            "condition_name": cname,
            "condition_type": CONDITION_TYPE.get(cname, "Other"),
            "condition_score": sub["condition_score"].dropna().iloc[0] if sub["condition_score"].notna().any() else np.nan,
            "n_subject_condition_rows": len(sub),
            "n_subjects": sub["subject_id"].nunique(),
        }
        for m in metrics:
            vals = pd.to_numeric(sub[m], errors="coerce")
            row[f"{m}_mean"] = float(vals.mean()) if vals.notna().any() else np.nan
            row[f"{m}_sd"] = float(vals.std(ddof=1)) if vals.notna().sum() > 1 else np.nan
            row[f"{m}_sem"] = float(vals.sem()) if vals.notna().sum() > 1 else np.nan
        rows.append(row)
    out = pd.DataFrame(rows)
    cat = pd.Categorical(out["condition_name"], categories=CONDITION_ORDER_NOMINAL, ordered=True)
    out = out.assign(_order=cat).sort_values("_order").drop(columns="_order")
    return out


def learning_curves(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    learning = df[df["phase"] == "learning"].copy()

    # Condition x mini-block curve per subject, then group average.
    subj_block = learning.groupby(["subject_id", "session_id", "condition_name", "mini_block_calc"], dropna=False).agg(
        accuracy=("is_correct", "mean"),
        n_trials=("is_correct", "size"),
        rt_mean_correct=("voice_onset_rt_sec", lambda s: safe_mean_correct_rt(s, learning)),
    ).reset_index().rename(columns={"mini_block_calc": "mini_block"})
    group_block = subj_block.groupby(["condition_name", "mini_block"], dropna=False).agg(
        accuracy_mean=("accuracy", "mean"),
        accuracy_sd=("accuracy", "std"),
        accuracy_sem=("accuracy", "sem"),
        rt_mean_correct_mean=("rt_mean_correct", "mean"),
        n_subject_blocks=("accuracy", "size"),
    ).reset_index()

    # Symbol and position exposure curves.
    symbol_curve = learning.groupby(["correct_symbol", "symbol_exposure_index"], dropna=False).agg(
        accuracy=("is_correct", "mean"),
        n_trials=("is_correct", "size"),
        rt_mean_correct=("voice_onset_rt_sec", lambda s: safe_mean_correct_rt(s, learning)),
    ).reset_index().rename(columns={"symbol_exposure_index": "exposure_index"})

    position_curve = learning.groupby(["position", "position_label", "position_exposure_index"], dropna=False).agg(
        accuracy=("is_correct", "mean"),
        n_trials=("is_correct", "size"),
        rt_mean_correct=("voice_onset_rt_sec", lambda s: safe_mean_correct_rt(s, learning)),
    ).reset_index().rename(columns={"position_exposure_index": "exposure_index"})

    return subj_block, group_block, symbol_curve, position_curve


def symbol_position_effect_summary(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    learning = df[df["phase"] == "learning"].copy()
    learning = learning.dropna(subset=["subject_id", "condition_name", "position", "correct_symbol", "is_correct"])
    if learning.empty:
        return pd.DataFrame(), "No learning rows."

    # Exposure bin makes the model compare performance at similar learning stage.
    learning["exposure_bin"] = pd.cut(
        learning["learning_trial_index"],
        bins=[0, 9, 18, 27, 36, 9999],
        labels=["1-9", "10-18", "19-27", "28-36", "37+"],
        include_lowest=True,
    )

    # Variability approach: if accuracy differs more by position than by symbol, position may be stronger bottleneck.
    by_symbol = learning.groupby(["correct_symbol", "exposure_bin"], observed=False)["is_correct"].mean().reset_index()
    by_position = learning.groupby(["position", "exposure_bin"], observed=False)["is_correct"].mean().reset_index()
    var_rows = []
    for bin_name in by_symbol["exposure_bin"].dropna().unique():
        svals = by_symbol.loc[by_symbol["exposure_bin"] == bin_name, "is_correct"].dropna()
        pvals = by_position.loc[by_position["exposure_bin"] == bin_name, "is_correct"].dropna()
        var_rows.append({
            "exposure_bin": str(bin_name),
            "symbol_accuracy_sd": float(svals.std(ddof=1)) if len(svals) > 1 else np.nan,
            "position_accuracy_sd": float(pvals.std(ddof=1)) if len(pvals) > 1 else np.nan,
            "larger_variability": "position" if (len(pvals) > 1 and len(svals) > 1 and pvals.std(ddof=1) > svals.std(ddof=1)) else "symbol_or_tie",
        })
    var_df = pd.DataFrame(var_rows)

    msg_lines = []
    if HAS_STATSMODELS:
        # Linear probability models for exploratory effect comparison.
        # This is not the final inferential model, but it helps compare symbol vs position explanatory power.
        model_data = learning.copy()
        model_data["subject_id"] = model_data["subject_id"].astype(str)
        model_data["position"] = model_data["position"].astype(str)
        try:
            base = smf.ols("is_correct ~ C(subject_id) + C(condition_name) + C(exposure_bin)", data=model_data).fit()
            m_symbol = smf.ols("is_correct ~ C(subject_id) + C(condition_name) + C(exposure_bin) + C(correct_symbol)", data=model_data).fit()
            m_position = smf.ols("is_correct ~ C(subject_id) + C(condition_name) + C(exposure_bin) + C(position)", data=model_data).fit()
            m_both = smf.ols("is_correct ~ C(subject_id) + C(condition_name) + C(exposure_bin) + C(correct_symbol) + C(position)", data=model_data).fit()
            comp = pd.DataFrame([
                {"model": "base", "adj_r2": base.rsquared_adj, "aic": base.aic, "bic": base.bic},
                {"model": "+symbol", "adj_r2": m_symbol.rsquared_adj, "aic": m_symbol.aic, "bic": m_symbol.bic},
                {"model": "+position", "adj_r2": m_position.rsquared_adj, "aic": m_position.aic, "bic": m_position.bic},
                {"model": "+symbol+position", "adj_r2": m_both.rsquared_adj, "aic": m_both.aic, "bic": m_both.bic},
            ])
            comp["delta_adj_r2_vs_base"] = comp["adj_r2"] - float(base.rsquared_adj)
            var_df = var_df.merge(pd.DataFrame({"key": [1]}), how="cross") if not var_df.empty else pd.DataFrame({"key": [1]})
            # Save model comparison separately by appending rows with exposure_bin = MODEL_COMPARISON.
            model_rows = comp.copy()
            model_rows.insert(0, "exposure_bin", "MODEL_COMPARISON")
            for col in ["symbol_accuracy_sd", "position_accuracy_sd", "larger_variability"]:
                if col not in model_rows.columns:
                    model_rows[col] = np.nan
            model_rows = model_rows.rename(columns={"model": "comparison_model"})
            var_df = pd.concat([var_df.drop(columns=["key"], errors="ignore"), model_rows], ignore_index=True, sort=False)
            msg_lines.append("Statsmodels exploratory OLS comparison was computed. See symbol_position_effect_summary.csv rows marked MODEL_COMPARISON.")
        except Exception as e:
            msg_lines.append(f"Statsmodels model comparison failed: {e}")
    else:
        msg_lines.append("statsmodels not available; only variability summary was computed.")
    return var_df, "\n".join(msg_lines)



def sem_numeric(x: pd.Series) -> float:
    vals = pd.to_numeric(x, errors="coerce").dropna()
    if len(vals) <= 1:
        return np.nan
    return float(vals.std(ddof=1) / math.sqrt(len(vals)))


def rt_by_symbol_position_summary(df: pd.DataFrame):
    """Compute correct-trial voice-onset RT summaries by consonant and position.

    Subject-level means are computed first, then group-level means/SEMs are
    computed over subject-level means. This avoids overweighting participants
    who completed more trials.
    """
    d = df.copy()
    if "voice_onset_rt_sec" not in d.columns:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    d["voice_onset_rt_sec"] = pd.to_numeric(d["voice_onset_rt_sec"], errors="coerce")
    d = d[(d["is_correct"] == 1) & d["voice_onset_rt_sec"].notna()].copy()
    # Remove implausible RTs. Keep broad bounds because early learning can be slow.
    d = d[(d["voice_onset_rt_sec"] >= 0.05) & (d["voice_onset_rt_sec"] <= 8.0)].copy()
    if d.empty:
        return (pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    # Subject-level RT by phase and consonant/position.
    sym_subj = d.groupby(["phase", "subject_id", "correct_symbol"], dropna=False).agg(
        rt_mean=("voice_onset_rt_sec", "mean"),
        rt_median=("voice_onset_rt_sec", "median"),
        n_correct_rt=("voice_onset_rt_sec", "size"),
    ).reset_index()

    pos_subj = d.groupby(["phase", "subject_id", "position", "position_label"], dropna=False).agg(
        rt_mean=("voice_onset_rt_sec", "mean"),
        rt_median=("voice_onset_rt_sec", "median"),
        n_correct_rt=("voice_onset_rt_sec", "size"),
    ).reset_index()

    # Group-level over subjects.
    sym_group = sym_subj.groupby(["phase", "correct_symbol"], dropna=False).agg(
        rt_mean=("rt_mean", "mean"),
        rt_median_mean=("rt_median", "mean"),
        rt_sem=("rt_mean", sem_numeric),
        n_subjects=("subject_id", "nunique"),
        n_subject_phase_symbol=("rt_mean", "size"),
        n_correct_rt_total=("n_correct_rt", "sum"),
    ).reset_index()
    sym_group["correct_symbol"] = pd.Categorical(sym_group["correct_symbol"], categories=SYMBOL_ORDER, ordered=True)
    sym_group = sym_group.sort_values(["phase", "correct_symbol"]).reset_index(drop=True)
    sym_group["correct_symbol"] = sym_group["correct_symbol"].astype(str)

    pos_group = pos_subj.groupby(["phase", "position", "position_label"], dropna=False).agg(
        rt_mean=("rt_mean", "mean"),
        rt_median_mean=("rt_median", "mean"),
        rt_sem=("rt_mean", sem_numeric),
        n_subjects=("subject_id", "nunique"),
        n_subject_phase_position=("rt_mean", "size"),
        n_correct_rt_total=("n_correct_rt", "sum"),
    ).reset_index()
    pos_group["position"] = pd.to_numeric(pos_group["position"], errors="coerce")
    pos_group = pos_group.sort_values(["phase", "position"]).reset_index(drop=True)

    # Exposure-wise RT curves during learning, correct trials only.
    learn = d[d["phase"] == "learning"].copy()
    if not learn.empty:
        sym_curve = learn.groupby(["correct_symbol", "symbol_exposure_index"], dropna=False).agg(
            rt_mean=("voice_onset_rt_sec", "mean"),
            rt_sem=("voice_onset_rt_sec", sem_numeric),
            n_correct_rt=("voice_onset_rt_sec", "size"),
        ).reset_index().rename(columns={"symbol_exposure_index": "exposure_index"})
        sym_curve["correct_symbol"] = pd.Categorical(sym_curve["correct_symbol"], categories=SYMBOL_ORDER, ordered=True)
        sym_curve = sym_curve.sort_values(["correct_symbol", "exposure_index"]).reset_index(drop=True)
        sym_curve["correct_symbol"] = sym_curve["correct_symbol"].astype(str)

        pos_curve = learn.groupby(["position", "position_label", "position_exposure_index"], dropna=False).agg(
            rt_mean=("voice_onset_rt_sec", "mean"),
            rt_sem=("voice_onset_rt_sec", sem_numeric),
            n_correct_rt=("voice_onset_rt_sec", "size"),
        ).reset_index().rename(columns={"position_exposure_index": "exposure_index"})
        pos_curve["position"] = pd.to_numeric(pos_curve["position"], errors="coerce")
        pos_curve = pos_curve.sort_values(["position", "exposure_index"]).reset_index(drop=True)
    else:
        sym_curve = pd.DataFrame()
        pos_curve = pd.DataFrame()

    return sym_subj, pos_subj, sym_group, pos_group, sym_curve, pos_curve

# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------

def save_bar(df: pd.DataFrame, x: str, y: str, title: str, ylabel: str, out: Path, yerr: Optional[str] = None):
    if df.empty or y not in df.columns:
        return
    plot_df = df.copy()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    xs = np.arange(len(plot_df))
    vals = plot_df[y].astype(float).values
    err = plot_df[yerr].astype(float).values if yerr and yerr in plot_df.columns else None
    ax.bar(xs, vals, yerr=err, capsize=4 if err is not None else 0)
    ax.set_xticks(xs)
    ax.set_xticklabels(plot_df[x].astype(str), rotation=25, ha="right")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)



def plot_rt_item_bars(sym_rt_group: pd.DataFrame, pos_rt_group: pd.DataFrame, out_dir: Path):
    """Save RT bar plots by consonant and position for learning/retention."""
    if not sym_rt_group.empty:
        for phase, filename, title in [
            ("learning", "bar_rt_learning_by_consonant.png", "Voice onset RT by consonant during learning"),
            ("retention", "bar_rt_retention_by_consonant.png", "Voice onset RT by consonant during retention"),
        ]:
            sub = sym_rt_group[sym_rt_group["phase"] == phase].copy()
            if sub.empty:
                continue
            sub["correct_symbol"] = pd.Categorical(sub["correct_symbol"], categories=SYMBOL_ORDER, ordered=True)
            sub = sub.sort_values("correct_symbol")
            save_bar(
                sub,
                x="correct_symbol",
                y="rt_mean",
                yerr="rt_sem",
                title=title,
                ylabel="Voice onset RT (s)",
                out=out_dir / filename,
            )

        # Fastest response ranking during learning: lower RT means faster.
        learn = sym_rt_group[sym_rt_group["phase"] == "learning"].copy()
        if not learn.empty:
            learn = learn.sort_values("rt_mean", ascending=True)
            save_bar(
                learn,
                x="correct_symbol",
                y="rt_mean",
                yerr="rt_sem",
                title="Fastest consonants by voice onset RT during learning",
                ylabel="Mean correct RT (s)",
                out=out_dir / "bar_fastest_rt_consonants_learning.png",
            )

    if not pos_rt_group.empty:
        for phase, filename, title in [
            ("learning", "bar_rt_learning_by_position.png", "Voice onset RT by position during learning"),
            ("retention", "bar_rt_retention_by_position.png", "Voice onset RT by position during retention"),
        ]:
            sub = pos_rt_group[pos_rt_group["phase"] == phase].copy()
            if sub.empty:
                continue
            sub["position"] = pd.to_numeric(sub["position"], errors="coerce")
            sub = sub.sort_values("position")
            save_bar(
                sub,
                x="position_label",
                y="rt_mean",
                yerr="rt_sem",
                title=title,
                ylabel="Voice onset RT (s)",
                out=out_dir / filename,
            )

        learn = pos_rt_group[pos_rt_group["phase"] == "learning"].copy()
        if not learn.empty:
            learn = learn.sort_values("rt_mean", ascending=True)
            save_bar(
                learn,
                x="position_label",
                y="rt_mean",
                yerr="rt_sem",
                title="Fastest positions by voice onset RT during learning",
                ylabel="Mean correct RT (s)",
                out=out_dir / "bar_fastest_rt_positions_learning.png",
            )


def plot_rt_exposure_curves(sym_rt_curve: pd.DataFrame, pos_rt_curve: pd.DataFrame, out_dir: Path):
    """Save exposure-wise RT curves for consonants and positions."""
    if not sym_rt_curve.empty:
        fig, ax = plt.subplots(figsize=(9.5, 5.2))
        for sym in SYMBOL_ORDER:
            sub = sym_rt_curve[sym_rt_curve["correct_symbol"] == sym].sort_values("exposure_index")
            if sub.empty:
                continue
            ax.plot(sub["exposure_index"], sub["rt_mean"], marker="o", label=sym)
        ax.set_xlabel("Exposure count for each consonant")
        ax.set_ylabel("Voice onset RT (s, correct trials)")
        ax.set_title("RT learning curve by consonant")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, ncol=3)
        fig.tight_layout()
        fig.savefig(out_dir / "rt_curve_by_consonant_exposure.png", dpi=200)
        plt.close(fig)

    if not pos_rt_curve.empty:
        fig, ax = plt.subplots(figsize=(9.5, 5.2))
        for pos in sorted(pd.to_numeric(pos_rt_curve["position"], errors="coerce").dropna().unique()):
            sub = pos_rt_curve[pd.to_numeric(pos_rt_curve["position"], errors="coerce") == pos].sort_values("exposure_index")
            if sub.empty:
                continue
            label = str(sub["position_label"].iloc[0]) if "position_label" in sub.columns else f"P{int(pos)}"
            ax.plot(sub["exposure_index"], sub["rt_mean"], marker="o", label=label)
        ax.set_xlabel("Exposure count for each position")
        ax.set_ylabel("Voice onset RT (s, correct trials)")
        ax.set_title("RT learning curve by position")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, ncol=3)
        fig.tight_layout()
        fig.savefig(out_dir / "rt_curve_by_position_exposure.png", dpi=200)
        plt.close(fig)


def plot_learning_curve(group_block: pd.DataFrame, out: Path):
    if group_block.empty:
        return
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    for cname in CONDITION_ORDER_NOMINAL:
        sub = group_block[group_block["condition_name"] == cname].sort_values("mini_block")
        if sub.empty:
            continue
        ax.plot(sub["mini_block"], sub["accuracy_mean"], marker="o", label=cname)
        if "accuracy_sem" in sub.columns:
            x = sub["mini_block"].astype(float).to_numpy()
            y = sub["accuracy_mean"].astype(float).to_numpy()
            e = sub["accuracy_sem"].astype(float).fillna(0).to_numpy()
            ax.fill_between(x, y-e, y+e, alpha=0.12)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Mini-block (9 learning trials)")
    ax.set_ylabel("Accuracy")
    ax.set_title("Learning curve by condition")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def plot_symbol_position_curves(symbol_curve: pd.DataFrame, position_curve: pd.DataFrame, out_dir: Path):
    if not symbol_curve.empty:
        fig, ax = plt.subplots(figsize=(9.5, 5.2))
        for sym in SYMBOL_ORDER:
            sub = symbol_curve[symbol_curve["correct_symbol"] == sym].sort_values("exposure_index")
            if sub.empty:
                continue
            ax.plot(sub["exposure_index"], sub["accuracy"], marker="o", label=sym)
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Exposure count for each consonant")
        ax.set_ylabel("Accuracy")
        ax.set_title("Learning curve by consonant")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, ncol=3)
        fig.tight_layout()
        fig.savefig(out_dir / "learning_curve_by_consonant.png", dpi=200)
        plt.close(fig)

    if not position_curve.empty:
        fig, ax = plt.subplots(figsize=(9.5, 5.2))
        for pos in range(1, 10):
            sub = position_curve[position_curve["position"] == pos].sort_values("exposure_index")
            if sub.empty:
                continue
            ax.plot(sub["exposure_index"], sub["accuracy"], marker="o", label=f"P{pos}")
        ax.set_ylim(0, 1.02)
        ax.set_xlabel("Exposure count for each position")
        ax.set_ylabel("Accuracy")
        ax.set_title("Learning curve by position")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, ncol=3)
        fig.tight_layout()
        fig.savefig(out_dir / "learning_curve_by_position.png", dpi=200)
        plt.close(fig)



def first_item_criterion_exposure(sub: pd.DataFrame, exposure_col: str, window: int, correct_needed: int) -> Tuple[Optional[int], int, Optional[float]]:
    """Return first exposure count where an item-specific rolling criterion is met.

    Example default: window=3 and correct_needed=3 means the item is considered
    learned when the last 3 exposures of that consonant/position were all correct.
    Returns (exposure_count_to_learn, n_exposures, elapsed_sec_at_learning).
    """
    if sub.empty:
        return None, 0, None
    sub = sub.sort_values([exposure_col, "learning_trial_index", "trial_global", "timestamp"])
    n_exp = int(sub[exposure_col].max()) if sub[exposure_col].notna().any() else len(sub)
    if len(sub) < window:
        return None, n_exp, None
    correct = sub["is_correct"].astype(int).to_numpy()
    roll = pd.Series(correct).rolling(window=window, min_periods=window).sum().to_numpy()
    hits = np.where(roll >= correct_needed)[0]
    if len(hits) == 0:
        return None, n_exp, None
    hit_pos = int(hits[0])
    row = sub.iloc[hit_pos]
    exp_count = int(row[exposure_col]) if pd.notna(row[exposure_col]) else hit_pos + 1
    ts0 = sub["timestamp"].dropna().min()
    elapsed = None
    if pd.notna(row.get("timestamp", np.nan)) and pd.notna(ts0):
        elapsed = float(row["timestamp"] - ts0)
    return exp_count, n_exp, elapsed


def item_learning_count_summary(df: pd.DataFrame, window: int = 3, correct_needed: int = 3) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute exposure count until each consonant/position is learned.

    The analysis is done within each subject × condition, then averaged.
    This helps answer whether learning stabilizes faster for particular
    consonants or particular forearm positions.
    """
    learning = df[df["phase"] == "learning"].copy()
    rows_sym = []
    rows_pos = []
    if learning.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    for (sid, sess, cname), block in learning.groupby(["subject_id", "session_id", "condition_name"], dropna=False):
        for sym, sub in block.groupby("correct_symbol", dropna=False):
            learned_exp, n_exp, elapsed = first_item_criterion_exposure(
                sub, "symbol_exposure_index", window, correct_needed
            )
            rows_sym.append({
                "subject_id": sid,
                "session_id": sess,
                "condition_name": cname,
                "condition_type": CONDITION_TYPE.get(cname, "Other"),
                "correct_symbol": sym,
                "item_criterion_window": window,
                "item_criterion_correct": correct_needed,
                "learned": int(learned_exp is not None),
                "exposures_to_learn": learned_exp,
                "n_exposures": n_exp,
                "elapsed_sec_to_learn": elapsed,
                "final_item_accuracy": float(sub["is_correct"].mean()) if len(sub) else np.nan,
            })
        for pos, sub in block.groupby("position", dropna=False):
            learned_exp, n_exp, elapsed = first_item_criterion_exposure(
                sub, "position_exposure_index", window, correct_needed
            )
            rows_pos.append({
                "subject_id": sid,
                "session_id": sess,
                "condition_name": cname,
                "condition_type": CONDITION_TYPE.get(cname, "Other"),
                "position": int(pos) if pd.notna(pos) else np.nan,
                "position_label": POSITION_LABEL.get(int(pos), f"P{pos}") if pd.notna(pos) else "",
                "item_criterion_window": window,
                "item_criterion_correct": correct_needed,
                "learned": int(learned_exp is not None),
                "exposures_to_learn": learned_exp,
                "n_exposures": n_exp,
                "elapsed_sec_to_learn": elapsed,
                "final_item_accuracy": float(sub["is_correct"].mean()) if len(sub) else np.nan,
            })

    sym_detail = pd.DataFrame(rows_sym)
    pos_detail = pd.DataFrame(rows_pos)

    def sem(x):
        x = pd.to_numeric(x, errors="coerce").dropna()
        return float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else np.nan

    if not sym_detail.empty:
        # Main question: which consonants are learned faster?
        # exposures_to_learn_* is computed only from cases where the item-level criterion was reached.
        # effective_exposures_to_learn treats unreached cases as n_exposures + 1, so slower/unreached items
        # are penalized in a robustness summary without emphasizing reached rate.
        sym_detail["effective_exposures_to_learn"] = sym_detail["exposures_to_learn"].where(
            sym_detail["learned"] == 1,
            sym_detail["n_exposures"] + 1
        )
        sym_group = sym_detail.groupby("correct_symbol").agg(
            n_observations=("learned", "size"),
            learned_count=("learned", "sum"),
            exposures_to_learn_mean=("exposures_to_learn", "mean"),
            exposures_to_learn_median=("exposures_to_learn", "median"),
            exposures_to_learn_sem=("exposures_to_learn", sem),
            effective_exposures_to_learn_mean=("effective_exposures_to_learn", "mean"),
            effective_exposures_to_learn_median=("effective_exposures_to_learn", "median"),
            elapsed_sec_to_learn_mean=("elapsed_sec_to_learn", "mean"),
            final_item_accuracy_mean=("final_item_accuracy", "mean"),
        ).reset_index()
        sym_group["correct_symbol"] = pd.Categorical(sym_group["correct_symbol"], categories=SYMBOL_ORDER, ordered=True)
        sym_group = sym_group.sort_values("correct_symbol")
    else:
        sym_group = pd.DataFrame()

    if not pos_detail.empty:
        pos_detail["effective_exposures_to_learn"] = pos_detail["exposures_to_learn"].where(
            pos_detail["learned"] == 1,
            pos_detail["n_exposures"] + 1
        )
        pos_group = pos_detail.groupby(["position", "position_label"]).agg(
            n_observations=("learned", "size"),
            learned_count=("learned", "sum"),
            exposures_to_learn_mean=("exposures_to_learn", "mean"),
            exposures_to_learn_median=("exposures_to_learn", "median"),
            exposures_to_learn_sem=("exposures_to_learn", sem),
            effective_exposures_to_learn_mean=("effective_exposures_to_learn", "mean"),
            effective_exposures_to_learn_median=("effective_exposures_to_learn", "median"),
            elapsed_sec_to_learn_mean=("elapsed_sec_to_learn", "mean"),
            final_item_accuracy_mean=("final_item_accuracy", "mean"),
        ).reset_index().sort_values("position")
    else:
        pos_group = pd.DataFrame()

    return sym_detail, pos_detail, sym_group, pos_group


def plot_item_learning_count_bars(symbol_count: pd.DataFrame, position_count: pd.DataFrame, out_dir: Path):
    """Bar plots for how quickly each consonant/position reaches item-level learning.

    Lower values mean faster learning. We intentionally focus on exposure count rather than
    reached rate, because the main research question is which items are learned earlier.
    """
    if not symbol_count.empty and "exposures_to_learn_mean" in symbol_count.columns:
        plot_df = symbol_count.copy()
        plot_df["symbol_label"] = plot_df["correct_symbol"].astype(str)
        # Ordered by Korean consonant order.
        save_bar(
            plot_df,
            x="symbol_label",
            y="exposures_to_learn_mean",
            yerr="exposures_to_learn_sem",
            title="Exposures needed to learn each consonant",
            ylabel="Mean exposures to learn (lower = faster)",
            out=out_dir / "bar_exposures_to_learn_by_consonant.png",
        )
        # Ranked version: fastest consonants first.
        ranked = plot_df.sort_values("exposures_to_learn_mean", ascending=True).copy()
        save_bar(
            ranked,
            x="symbol_label",
            y="exposures_to_learn_mean",
            yerr="exposures_to_learn_sem",
            title="Fastest-learned consonants",
            ylabel="Mean exposures to learn (lower = faster)",
            out=out_dir / "bar_fastest_learned_consonants.png",
        )
        # Robust version penalizes unreached cases as n_exposures + 1.
        if "effective_exposures_to_learn_mean" in plot_df.columns:
            ranked_eff = plot_df.sort_values("effective_exposures_to_learn_mean", ascending=True).copy()
            save_bar(
                ranked_eff,
                x="symbol_label",
                y="effective_exposures_to_learn_mean",
                title="Fastest-learned consonants, unreached penalized",
                ylabel="Effective exposures to learn (lower = faster)",
                out=out_dir / "bar_fastest_learned_consonants_effective.png",
            )

    if not position_count.empty and "exposures_to_learn_mean" in position_count.columns:
        plot_df = position_count.copy()
        plot_df["position_short"] = plot_df["position"].map(lambda x: f"P{int(x)}" if pd.notna(x) else "")
        # Anatomical/logical order P1-P9.
        save_bar(
            plot_df,
            x="position_short",
            y="exposures_to_learn_mean",
            yerr="exposures_to_learn_sem",
            title="Exposures needed to learn each position",
            ylabel="Mean exposures to learn (lower = faster)",
            out=out_dir / "bar_exposures_to_learn_by_position.png",
        )
        # Ranked version: fastest positions first.
        ranked = plot_df.sort_values("exposures_to_learn_mean", ascending=True).copy()
        save_bar(
            ranked,
            x="position_short",
            y="exposures_to_learn_mean",
            yerr="exposures_to_learn_sem",
            title="Fastest-learned positions",
            ylabel="Mean exposures to learn (lower = faster)",
            out=out_dir / "bar_fastest_learned_positions.png",
        )
        if "effective_exposures_to_learn_mean" in plot_df.columns:
            ranked_eff = plot_df.sort_values("effective_exposures_to_learn_mean", ascending=True).copy()
            save_bar(
                ranked_eff,
                x="position_short",
                y="effective_exposures_to_learn_mean",
                title="Fastest-learned positions, unreached penalized",
                ylabel="Effective exposures to learn (lower = faster)",
                out=out_dir / "bar_fastest_learned_positions_effective.png",
            )

def plot_heatmaps(df: pd.DataFrame, out_dir: Path):
    learning = df[df["phase"] == "learning"].copy()
    if learning.empty:
        return
    # Final/overall accuracy by symbol and condition.
    sym_cond = learning.groupby(["correct_symbol", "condition_name"])["is_correct"].mean().unstack("condition_name")
    sym_cond = sym_cond.reindex(SYMBOL_ORDER)
    sym_cond = sym_cond.reindex(columns=[c for c in CONDITION_ORDER_NOMINAL if c in sym_cond.columns])
    if not sym_cond.empty:
        fig, ax = plt.subplots(figsize=(9, 4.8))
        im = ax.imshow(sym_cond.values.astype(float), vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(sym_cond.shape[1])); ax.set_xticklabels(sym_cond.columns, rotation=30, ha="right")
        ax.set_yticks(range(sym_cond.shape[0])); ax.set_yticklabels(sym_cond.index)
        ax.set_title("Learning accuracy by consonant and condition")
        fig.colorbar(im, ax=ax, label="Accuracy")
        fig.tight_layout()
        fig.savefig(out_dir / "heatmap_consonant_condition_accuracy.png", dpi=200)
        plt.close(fig)

    pos_cond = learning.groupby(["position", "condition_name"])["is_correct"].mean().unstack("condition_name")
    pos_cond = pos_cond.reindex(range(1, 10))
    pos_cond = pos_cond.reindex(columns=[c for c in CONDITION_ORDER_NOMINAL if c in pos_cond.columns])
    if not pos_cond.empty:
        fig, ax = plt.subplots(figsize=(9, 4.8))
        im = ax.imshow(pos_cond.values.astype(float), vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(pos_cond.shape[1])); ax.set_xticklabels(pos_cond.columns, rotation=30, ha="right")
        ax.set_yticks(range(pos_cond.shape[0])); ax.set_yticklabels([f"P{i}" for i in pos_cond.index])
        ax.set_title("Learning accuracy by position and condition")
        fig.colorbar(im, ax=ax, label="Accuracy")
        fig.tight_layout()
        fig.savefig(out_dir / "heatmap_position_condition_accuracy.png", dpi=200)
        plt.close(fig)


def plot_confusion_matrices(df: pd.DataFrame, out_dir: Path):
    # One confusion matrix per condition for retention if available, otherwise all rows.
    labels = SYMBOL_ORDER
    for phase in ["learning", "retention"]:
        phase_df = df[df["phase"] == phase]
        if phase_df.empty:
            continue
        for cname, sub in phase_df.groupby("condition_name"):
            if sub.empty:
                continue
            mat = pd.crosstab(sub["correct_symbol"], sub["response_symbol"], normalize="index")
            mat = mat.reindex(index=labels, columns=labels, fill_value=0)
            fig, ax = plt.subplots(figsize=(6.5, 5.8))
            im = ax.imshow(mat.values, vmin=0, vmax=1, aspect="auto")
            ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=45, ha="right")
            ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
            ax.set_xlabel("Response")
            ax.set_ylabel("Target")
            ax.set_title(f"Confusion matrix: {cname} ({phase})")
            fig.colorbar(im, ax=ax, label="Row-normalized proportion")
            fig.tight_layout()
            fig.savefig(out_dir / f"confusion_{phase}_{cname}.png", dpi=200)
            plt.close(fig)

# -----------------------------------------------------------------------------
# Report writing
# -----------------------------------------------------------------------------

def write_markdown_report(out_dir: Path, df: pd.DataFrame, subj_summary: pd.DataFrame, group_summary: pd.DataFrame, effect_msg: str):
    n_subjects = df["subject_id"].nunique()
    n_trials = len(df)
    lines = []
    lines.append("# Tactile consonant learning analysis summary\n")
    lines.append(f"- Subjects: **{n_subjects}**")
    lines.append(f"- Total trial rows: **{n_trials}**")
    lines.append("- Primary criterion: recent 27 trials >= 25 correct")
    lines.append("- Item-level learned count: default recent 3 exposures >= 3 correct for each consonant/position")
    lines.append("- Retention: 18 trials per condition if completed by the app\n")

    lines.append("## Group summary by condition\n")
    cols = [
        "condition_name", "condition_type", "n_subjects",
        "criterion_reached_mean", "trials_to_criterion_mean", "time_to_criterion_sec_mean",
        "final27_accuracy_mean", "retention_accuracy_mean", "learning_rt_mean_correct_mean",
    ]
    show = group_summary[[c for c in cols if c in group_summary.columns]].copy()
    lines.append(df_to_markdown_simple(show))
    lines.append("\n")

    lines.append("## Symbol vs position influence note\n")
    lines.append(effect_msg if effect_msg else "See symbol_position_effect_summary.csv.")
    lines.append("\n")

    lines.append("## Output files\n")
    for p in sorted(out_dir.glob("*")):
        if p.name == "analysis_report.md":
            continue
        lines.append(f"- {p.name}")
    (out_dir / "analysis_report.md").write_text("\n".join(lines), encoding="utf-8")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    used_font = setup_korean_font()
    if used_font:
        print(f"[Info] Matplotlib Korean font: {used_font}")
    else:
        print("[Info] No Korean font found for matplotlib. Plots will still be saved, but Korean labels may not render correctly.")

    parser = argparse.ArgumentParser(description="Analyze tactile consonant learning experiment logs. v7: item-level learning and RT plots.")
    parser.add_argument("--data-dir", type=str, default="data/logs", help="Folder containing experiment CSV logs.")
    parser.add_argument("--out-dir", type=str, default="analysis_results", help="Output folder for analysis results.")
    parser.add_argument("--criterion-window", type=int, default=DEFAULT_CRITERION_WINDOW)
    parser.add_argument("--criterion-correct", type=int, default=DEFAULT_CRITERION_CORRECT)
    parser.add_argument("--no-recursive", action="store_true", help="Do not search data-dir recursively.")
    parser.add_argument("--item-criterion-window", type=int, default=3, help="Rolling exposure window for item-level learning speed. Default: 3 exposures.")
    parser.add_argument("--item-criterion-correct", type=int, default=3, help="Correct responses needed in the rolling item window. Default: 3/3 correct.")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_all_logs(data_dir, recursive=not args.no_recursive)
    df = add_learning_indices(df)
    df.to_csv(out_dir / "all_trials_clean.csv", index=False, encoding="utf-8-sig")

    subj_summary = summarize_subject_condition(df, args.criterion_window, args.criterion_correct)
    group_summary = summarize_group(subj_summary)
    subj_block, group_block, symbol_curve, position_curve = learning_curves(df)
    effect_summary, effect_msg = symbol_position_effect_summary(df)
    symbol_count_detail, position_count_detail, symbol_count_group, position_count_group = item_learning_count_summary(
        df, window=args.item_criterion_window, correct_needed=args.item_criterion_correct
    )
    sym_rt_subj, pos_rt_subj, sym_rt_group, pos_rt_group, sym_rt_curve, pos_rt_curve = rt_by_symbol_position_summary(df)

    # Additional detailed tables.
    symbol_overall = df[df["phase"] == "learning"].groupby("correct_symbol").agg(
        learning_accuracy=("is_correct", "mean"),
        n_trials=("is_correct", "size"),
        rt_mean_correct=("voice_onset_rt_sec", lambda s: safe_mean_correct_rt(s, df)),
    ).reset_index()
    position_overall = df[df["phase"] == "learning"].groupby(["position", "position_label"]).agg(
        learning_accuracy=("is_correct", "mean"),
        n_trials=("is_correct", "size"),
        rt_mean_correct=("voice_onset_rt_sec", lambda s: safe_mean_correct_rt(s, df)),
    ).reset_index()

    # Save CSV outputs.
    subj_summary.to_csv(out_dir / "subject_condition_summary.csv", index=False, encoding="utf-8-sig")
    group_summary.to_csv(out_dir / "group_condition_summary.csv", index=False, encoding="utf-8-sig")
    subj_block.to_csv(out_dir / "subject_learning_curve_by_miniblock.csv", index=False, encoding="utf-8-sig")
    group_block.to_csv(out_dir / "group_learning_curve_by_miniblock.csv", index=False, encoding="utf-8-sig")
    symbol_curve.to_csv(out_dir / "consonant_learning_curve_by_exposure.csv", index=False, encoding="utf-8-sig")
    position_curve.to_csv(out_dir / "position_learning_curve_by_exposure.csv", index=False, encoding="utf-8-sig")
    symbol_overall.to_csv(out_dir / "consonant_overall_learning_summary.csv", index=False, encoding="utf-8-sig")
    position_overall.to_csv(out_dir / "position_overall_learning_summary.csv", index=False, encoding="utf-8-sig")
    effect_summary.to_csv(out_dir / "symbol_position_effect_summary.csv", index=False, encoding="utf-8-sig")
    symbol_count_detail.to_csv(out_dir / "consonant_exposures_to_learn_subject_condition.csv", index=False, encoding="utf-8-sig")
    position_count_detail.to_csv(out_dir / "position_exposures_to_learn_subject_condition.csv", index=False, encoding="utf-8-sig")
    symbol_count_group.to_csv(out_dir / "consonant_exposures_to_learn_group.csv", index=False, encoding="utf-8-sig")
    position_count_group.to_csv(out_dir / "position_exposures_to_learn_group.csv", index=False, encoding="utf-8-sig")
    sym_rt_subj.to_csv(out_dir / "consonant_rt_subject_phase.csv", index=False, encoding="utf-8-sig")
    pos_rt_subj.to_csv(out_dir / "position_rt_subject_phase.csv", index=False, encoding="utf-8-sig")
    sym_rt_group.to_csv(out_dir / "consonant_rt_group_phase.csv", index=False, encoding="utf-8-sig")
    pos_rt_group.to_csv(out_dir / "position_rt_group_phase.csv", index=False, encoding="utf-8-sig")
    sym_rt_curve.to_csv(out_dir / "consonant_rt_curve_by_exposure.csv", index=False, encoding="utf-8-sig")
    pos_rt_curve.to_csv(out_dir / "position_rt_curve_by_exposure.csv", index=False, encoding="utf-8-sig")
    # Ranked summaries for the main question: lower exposure count means faster learning.
    if not symbol_count_group.empty and "exposures_to_learn_mean" in symbol_count_group.columns:
        symbol_count_group.sort_values("exposures_to_learn_mean", ascending=True).to_csv(
            out_dir / "rank_fastest_learned_consonants.csv", index=False, encoding="utf-8-sig"
        )
    if not position_count_group.empty and "exposures_to_learn_mean" in position_count_group.columns:
        position_count_group.sort_values("exposures_to_learn_mean", ascending=True).to_csv(
            out_dir / "rank_fastest_learned_positions.csv", index=False, encoding="utf-8-sig"
        )
    if not sym_rt_group.empty and "rt_mean" in sym_rt_group.columns:
        sym_rt_group[sym_rt_group["phase"] == "learning"].sort_values("rt_mean", ascending=True).to_csv(
            out_dir / "rank_fastest_rt_consonants_learning.csv", index=False, encoding="utf-8-sig"
        )
    if not pos_rt_group.empty and "rt_mean" in pos_rt_group.columns:
        pos_rt_group[pos_rt_group["phase"] == "learning"].sort_values("rt_mean", ascending=True).to_csv(
            out_dir / "rank_fastest_rt_positions_learning.csv", index=False, encoding="utf-8-sig"
        )

    # Save Excel workbook if possible.
    try:
        with pd.ExcelWriter(out_dir / "analysis_summary.xlsx", engine="openpyxl") as writer:
            subj_summary.to_excel(writer, sheet_name="subject_condition", index=False)
            group_summary.to_excel(writer, sheet_name="group_condition", index=False)
            group_block.to_excel(writer, sheet_name="learning_curve_group", index=False)
            symbol_curve.to_excel(writer, sheet_name="consonant_curve", index=False)
            position_curve.to_excel(writer, sheet_name="position_curve", index=False)
            symbol_overall.to_excel(writer, sheet_name="consonant_overall", index=False)
            position_overall.to_excel(writer, sheet_name="position_overall", index=False)
            effect_summary.to_excel(writer, sheet_name="symbol_vs_position", index=False)
            symbol_count_detail.to_excel(writer, sheet_name="consonant_learn_count_subj", index=False)
            position_count_detail.to_excel(writer, sheet_name="position_learn_count_subj", index=False)
            symbol_count_group.to_excel(writer, sheet_name="consonant_learn_count_group", index=False)
            position_count_group.to_excel(writer, sheet_name="position_learn_count_group", index=False)
            sym_rt_group.to_excel(writer, sheet_name="consonant_rt_group", index=False)
            pos_rt_group.to_excel(writer, sheet_name="position_rt_group", index=False)
            sym_rt_curve.to_excel(writer, sheet_name="consonant_rt_curve", index=False)
            pos_rt_curve.to_excel(writer, sheet_name="position_rt_curve", index=False)
    except Exception as e:
        print(f"[WARN] Excel export failed: {e}")

    # Plots.
    save_bar(
        group_summary,
        x="condition_name",
        y="trials_to_criterion_mean",
        yerr="trials_to_criterion_sem",
        title="Trials to criterion by condition",
        ylabel="Trials to criterion",
        out=out_dir / "bar_trials_to_criterion.png",
    )
    save_bar(
        group_summary,
        x="condition_name",
        y="retention_accuracy_mean",
        yerr="retention_accuracy_sem",
        title="Retention accuracy by condition",
        ylabel="Retention accuracy",
        out=out_dir / "bar_retention_accuracy.png",
    )
    save_bar(
        group_summary,
        x="condition_name",
        y="criterion_reached_mean",
        yerr="criterion_reached_sem",
        title="Criterion reached rate by condition",
        ylabel="Proportion reached",
        out=out_dir / "bar_criterion_reached_rate.png",
    )
    plot_learning_curve(group_block, out_dir / "learning_curve_by_condition.png")
    plot_symbol_position_curves(symbol_curve, position_curve, out_dir)
    plot_item_learning_count_bars(symbol_count_group, position_count_group, out_dir)
    plot_rt_item_bars(sym_rt_group, pos_rt_group, out_dir)
    plot_rt_exposure_curves(sym_rt_curve, pos_rt_curve, out_dir)
    plot_heatmaps(df, out_dir)
    plot_confusion_matrices(df, out_dir)

    write_markdown_report(out_dir, df, subj_summary, group_summary, effect_msg)

    print("Analysis complete.")
    print(f"Input: {data_dir}")
    print(f"Output: {out_dir.resolve()}")
    print("Key files:")
    print(f"  - {out_dir / 'analysis_summary.xlsx'}")
    print(f"  - {out_dir / 'analysis_report.md'}")
    print(f"  - {out_dir / 'group_condition_summary.csv'}")


if __name__ == "__main__":
    main()
