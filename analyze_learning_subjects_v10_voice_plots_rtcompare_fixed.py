import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# ------------------------------------------------------------
# Korean font setting for matplotlib
# ------------------------------------------------------------
# This prevents warnings such as:
#   RuntimeWarning: Glyph xxxx missing from current font
#
# On Windows, Malgun Gothic is usually available by default.
try:
    font_path = "C:/Windows/Fonts/malgun.ttf"
    font_name = fm.FontProperties(fname=font_path).get_name()
    plt.rcParams["font.family"] = font_name
except Exception:
    plt.rcParams["font.family"] = "Malgun Gothic"

plt.rcParams["axes.unicode_minus"] = False


# ============================================================
# Hangul tactile learning analysis by subject + group
# ============================================================
#
# Usage:
#   python analyze_learning_subjects.py
#
# Input:
#   ./hangul_learning_results/subject_*/subject_*.csv
#
# Output:
#   ./analysis_learning_subjects/
#       results_by_subject/
#           subject_1/
#           subject_2/
#           ...
#       group_summary/
#
# Handles incomplete days/sessions automatically.
#
# RT convention:
#   Uses onset-based RT: stimulus command sent time -> response click.
#   Stimulus duration is NOT subtracted.
# ============================================================


RESULT_DIR = Path("hangul_learning_results")
OUT_DIR = Path("analysis_learning_subjects_voice")

MOVING_WINDOW = 10

SESSION_ORDER = [
    "basic_consonants",
    "long_consonants",
    "double_consonants",
    "all_consonants",
    "basic_vowels",
    "double_vowels",
    "complex_vowels",
    "all_vowels",
    "syllable_top50",
    "syllable_top100",
    "syllable_top200",
]

SESSION_LABELS = {
    "basic_consonants": "S1 Basic consonants",
    "long_consonants": "S2 Long consonants",
    "double_consonants": "S3 Double consonants",
    "all_consonants": "S4 All consonants",
    "basic_vowels": "S5 Basic vowels",
    "double_vowels": "S6 Double vowels",
    "complex_vowels": "S7 Complex vowels",
    "all_vowels": "S8 All vowels",
    "syllable_top50": "S9 Syllable Top 50",
    "syllable_top100": "S10 Syllable Top 100",
    "syllable_top200": "S11 Syllable Top 200",

    # Backward compatibility with older app versions
    "short_consonants": "S1 Short consonants",
    "mixed_consonants": "S4 All consonants",
    "extended_vowels": "S7 Complex vowels",
    "mixed_vowels": "S8 All vowels",
}


CONSONANT_PAIRS = [
    ("ㄱ", "ㅋ"),
    ("ㄴ", "ㄹ"),
    ("ㄷ", "ㅌ"),
    ("ㅂ", "ㅍ"),
    ("ㅅ", "ㅎ"),
    ("ㅇ", "ㅁ"),
    ("ㅈ", "ㅊ"),
]

VOWEL_PAIRS = [
    ("ㅣ", "ㅡ"),
    ("ㅏ", "ㅑ"),
    ("ㅓ", "ㅕ"),
    ("ㅗ", "ㅛ"),
    ("ㅜ", "ㅠ"),
]


def sem(x):
    x = pd.to_numeric(x, errors="coerce").dropna()
    if len(x) <= 1:
        return 0
    return x.std(ddof=1) / math.sqrt(len(x))


def safe_name(x):
    return str(x).replace("/", "_").replace("\\", "_").replace(":", "_").replace(" ", "_")


def estimate_command_duration_ms(command_body):
    """Estimate stimulus duration from target_command.

    Examples:
        3/150 -> 150 ms
        5/100.5/d,2/i/100.2/150 -> 100 + 100 + 150 = 350 ms
        pattern.0/150.pattern -> includes the 150 ms interval

    Rule:
        Sum numeric duration values immediately after '/'.
        Non-duration tokens such as /d or /i are ignored.
    """
    if pd.isna(command_body):
        return np.nan

    s = str(command_body).strip()
    if not s:
        return np.nan

    matches = re.findall(r"/(\d+(?:\.\d+)?)", s)

    if not matches:
        return np.nan

    total = 0.0
    for m in matches:
        try:
            total += float(m)
        except Exception:
            pass

    return total


def load_learning_data():
    files = sorted(RESULT_DIR.glob("**/*.csv"))

    valid_files = []
    for p in files:
        name = p.name.lower()
        if name.startswith("~$"):
            continue
        if "trial_plan" in name:
            continue
        if any(skip in name for skip in ["summary", "confusion", "merged", "analysis"]):
            continue
        valid_files.append(p)

    if not valid_files:
        raise FileNotFoundError(f"No CSV files found under {RESULT_DIR}")

    frames = []
    for p in valid_files:
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(p)

        if df.empty:
            continue

        df["source_file"] = str(p)
        frames.append(df)

    if not frames:
        raise FileNotFoundError("CSV files were found, but all were empty.")

    return pd.concat(frames, ignore_index=True)


def standardize(df):
    df = df.copy()

    for col, default in [
        ("subject", ""),
        ("day", ""),
        ("session_idx", np.nan),
        ("session_name", ""),
        ("session_title", ""),
        ("trial_index_global", np.nan),
        ("trial_index_session", np.nan),
        ("target_label", ""),
        ("target_command", ""),
        ("response_mode", ""),
        ("voice_engine", ""),
        ("stt_model", ""),
        ("voice_stt_raw", ""),
        ("voice_stt_norm", ""),
        ("voice_process_time_sec", np.nan),
        ("voice_recorded_duration_sec", np.nan),
        ("within_unit_interval_ms", np.nan),
        ("cv_interval_ms", np.nan),
        ("stimulus_duration_sec", np.nan),
        ("top_candidates", ""),
        ("option_count", np.nan),
        ("syllable_reps_required", np.nan),
        ("selected_label", ""),
        ("correct", np.nan),
        ("rt_sec", np.nan),
        ("timestamp", ""),
    ]:
        if col not in df.columns:
            df[col] = default

    df["subject"] = df["subject"].astype(str).str.strip()
    df["day"] = df["day"].astype(str).str.strip()
    df["session_name"] = df["session_name"].astype(str).str.strip()
    df["session_title"] = df["session_title"].astype(str).str.strip()
    df["target_label"] = df["target_label"].astype(str).str.strip()
    df["target_command"] = df["target_command"].astype(str).str.strip()
    df["response_mode"] = df["response_mode"].astype(str).str.strip()
    df["selected_label"] = df["selected_label"].astype(str).str.strip()

    df["option_count"] = pd.to_numeric(df["option_count"], errors="coerce")
    df["syllable_reps_required"] = pd.to_numeric(df["syllable_reps_required"], errors="coerce")

    # Older files may not have response_mode.
    df.loc[
        df["response_mode"].isin(["", "nan"]),
        "response_mode"
    ] = np.where(
        df.loc[df["response_mode"].isin(["", "nan"]), "session_name"].eq("syllable_top200"),
        "typing",
        "choice"
    )

    df["session_idx"] = pd.to_numeric(df["session_idx"], errors="coerce")
    df["trial_index_global"] = pd.to_numeric(df["trial_index_global"], errors="coerce")
    df["trial_index_session"] = pd.to_numeric(df["trial_index_session"], errors="coerce")
    df["correct"] = pd.to_numeric(df["correct"], errors="coerce")
    df["rt_sec"] = pd.to_numeric(df["rt_sec"], errors="coerce")
    for col in ["voice_process_time_sec", "voice_recorded_duration_sec", "within_unit_interval_ms", "cv_interval_ms", "stimulus_duration_sec"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["day_elapsed_sec", "session_elapsed_sec", "trial_elapsed_sec", "rt_from_stimulus_sec", "rt_from_stimulus_end_sec"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan

    # ------------------------------------------------------------
    # RT handling for voice-based response
    # ------------------------------------------------------------
    # Current convention:
    #   rt_sec = stimulus onset -> voice onset
    #   rt_from_stimulus_sec = stimulus end -> voice onset
    #
    # Older files may only have voice_onset_rt_sec or may have
    # rt_from_stimulus_sec copied from rt_sec. We keep both columns
    # and use rt_sec as the main onset-based RT for plots.
    if "voice_onset_rt_sec" in df.columns:
        old_rt = pd.to_numeric(df["voice_onset_rt_sec"], errors="coerce")
        df["rt_sec"] = pd.to_numeric(df["rt_sec"], errors="coerce")
        df.loc[df["rt_sec"].isna(), "rt_sec"] = old_rt[df["rt_sec"].isna()]

    df["stimulus_duration_ms_est"] = df["target_command"].apply(estimate_command_duration_ms)
    df["stimulus_duration_sec_est"] = df["stimulus_duration_ms_est"] / 1000.0

    if "stimulus_duration_sec" in df.columns:
        supplied_dur = pd.to_numeric(df["stimulus_duration_sec"], errors="coerce")
        df.loc[supplied_dur.notna(), "stimulus_duration_sec_est"] = supplied_dur[supplied_dur.notna()]

    df["rt_sec"] = pd.to_numeric(df["rt_sec"], errors="coerce")
    df["rt_from_stimulus_sec"] = pd.to_numeric(df["rt_from_stimulus_sec"], errors="coerce")

    missing_from_end = df["rt_from_stimulus_sec"].isna()
    df.loc[missing_from_end, "rt_from_stimulus_sec"] = (
        df.loc[missing_from_end, "rt_sec"] - df.loc[missing_from_end, "stimulus_duration_sec_est"]
    )
    df.loc[df["rt_from_stimulus_sec"] < 0, "rt_from_stimulus_sec"] = np.nan

    df["rt_sec_raw"] = df["rt_sec"]
    df["rt_onset_sec"] = df["rt_sec"]
    df["rt_end_corrected_sec"] = df["rt_from_stimulus_sec"]

    empty_day = df["day"].eq("") | df["day"].eq("nan")
    if empty_day.any() and "timestamp" in df.columns:
        inferred = pd.to_datetime(df["timestamp"], errors="coerce").dt.date.astype(str)
        df.loc[empty_day, "day"] = inferred[empty_day]

    idx_to_name = {
        1: "basic_consonants",
        2: "long_consonants",
        3: "double_consonants",
        4: "all_consonants",
        5: "basic_vowels",
        6: "double_vowels",
        7: "complex_vowels",
        8: "all_vowels",
        9: "syllable_top50",
        10: "syllable_top100",
        11: "syllable_top200",
    }

    empty_session = df["session_name"].eq("") | df["session_name"].eq("nan")
    if empty_session.any():
        inferred = df["session_idx"].map(idx_to_name)
        df.loc[empty_session, "session_name"] = inferred[empty_session]

    order_map = {name: i + 1 for i, name in enumerate(SESSION_ORDER)}
    df["session_order"] = df["session_name"].map(order_map)
    df["session_label"] = df["session_name"].map(SESSION_LABELS).fillna(df["session_name"])

    df = df[df["target_label"].notna() & (df["target_label"].astype(str).str.strip() != "")].copy()
    return df



def rt_columns_for_plots(df):
    """Return RT columns to plot: full onset RT and stimulus-end-corrected RT."""
    cols = []
    if "rt_sec" in df.columns:
        cols.append(("rt_sec", "RT onset (s)", "rt_onset"))
    if "rt_from_stimulus_sec" in df.columns:
        cols.append(("rt_from_stimulus_sec", "RT after stimulus end (s)", "rt_after_stimulus"))
    return cols


def moving_mean(s, window=MOVING_WINDOW):
    return pd.to_numeric(s, errors="coerce").rolling(window=window, min_periods=1).mean()


def summary_by_session(df):
    rows = []
    for (subject, day, session_name), g in df.groupby(["subject", "day", "session_name"], dropna=False):
        g = g.sort_values("trial_index_session")

        completed = 0
        if "session_completed_after_trial" in g.columns:
            completed = int(pd.to_numeric(g["session_completed_after_trial"], errors="coerce").fillna(0).max() > 0)

        failed = 0
        if "session_failed_after_trial" in g.columns:
            failed = int(pd.to_numeric(g["session_failed_after_trial"], errors="coerce").fillna(0).max() > 0)

        rows.append({
            "subject": subject,
            "day": day,
            "session_name": session_name,
            "session_label": SESSION_LABELS.get(session_name, session_name),
            "session_order": g["session_order"].iloc[0] if "session_order" in g.columns else np.nan,
            "n_trials": len(g),
            "n_unique_targets": g["target_label"].nunique(),
            "mean_reps_per_target": len(g) / g["target_label"].nunique() if g["target_label"].nunique() > 0 else np.nan,
            "response_mode": g["response_mode"].dropna().iloc[0] if "response_mode" in g.columns and len(g["response_mode"].dropna()) else "",
            "accuracy": g["correct"].mean(),
            "rt_mean_sec": g["rt_sec"].mean(),
            "rt_median_sec": g["rt_sec"].median(),
            "rt_from_stimulus_mean_sec": g["rt_from_stimulus_sec"].mean(),
            "rt_from_stimulus_median_sec": g["rt_from_stimulus_sec"].median(),
            "stimulus_duration_mean_sec": g["stimulus_duration_sec_est"].mean(),
            "completed": completed,
            "failed": failed,
            "session_elapsed_final_sec": g["session_elapsed_sec"].max(),
            "day_elapsed_final_sec": g["day_elapsed_sec"].max(),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["subject", "day", "session_order"])


def summary_by_day(df):
    rows = []
    for (subject, day), g in df.groupby(["subject", "day"], dropna=False):
        sessions_present = [s for s in SESSION_ORDER if s in set(g["session_name"])]
        rows.append({
            "subject": subject,
            "day": day,
            "n_sessions_present": len(sessions_present),
            "sessions_present": "|".join(sessions_present),
            "n_trials": len(g),
            "n_unique_targets": g["target_label"].nunique(),
            "mean_reps_per_target": len(g) / g["target_label"].nunique() if g["target_label"].nunique() > 0 else np.nan,
            "response_mode": g["response_mode"].dropna().iloc[0] if "response_mode" in g.columns and len(g["response_mode"].dropna()) else "",
            "accuracy": g["correct"].mean(),
            "rt_mean_sec": g["rt_sec"].mean(),
            "rt_median_sec": g["rt_sec"].median(),
            "rt_from_stimulus_mean_sec": g["rt_from_stimulus_sec"].mean(),
            "rt_from_stimulus_median_sec": g["rt_from_stimulus_sec"].median(),
            "day_elapsed_final_sec": g["day_elapsed_sec"].max(),
        })
    return pd.DataFrame(rows).sort_values(["subject", "day"])


def item_summary(df):
    out = (
        df.groupby(["subject", "day", "session_name", "target_label"], as_index=False)
        .agg(
            n_trials=("correct", "size"),
            accuracy=("correct", "mean"),
            rt_mean_sec=("rt_sec", "mean"),
            rt_median_sec=("rt_sec", "median"),
            rt_from_stimulus_mean_sec=("rt_from_stimulus_sec", "mean"),
            rt_from_stimulus_median_sec=("rt_from_stimulus_sec", "median"),
            n_errors=("correct", lambda x: int((pd.to_numeric(x, errors="coerce") == 0).sum())),
        )
    )
    out["session_order"] = out["session_name"].map({name: i + 1 for i, name in enumerate(SESSION_ORDER)})
    return out.sort_values(["subject", "day", "session_order", "target_label"])


def pair_confusion_summary(df):
    rows = []
    session_pair_map = {
        "mixed_consonants": CONSONANT_PAIRS,
        "mixed_vowels": VOWEL_PAIRS,
    }

    for session_name, pairs in session_pair_map.items():
        gsession = df[df["session_name"] == session_name].copy()
        if gsession.empty:
            continue

        for (subject, day), gday in gsession.groupby(["subject", "day"]):
            for a, b in pairs:
                target_a = gday[gday["target_label"] == a]
                target_b = gday[gday["target_label"] == b]
                n_a = len(target_a)
                n_b = len(target_b)
                a_to_b = int((target_a["selected_label"] == b).sum()) if n_a else 0
                b_to_a = int((target_b["selected_label"] == a).sum()) if n_b else 0
                total = n_a + n_b

                rows.append({
                    "subject": subject,
                    "day": day,
                    "session_name": session_name,
                    "pair": f"{a}-{b}",
                    "a_to_b_errors": a_to_b,
                    "b_to_a_errors": b_to_a,
                    "total_pair_confusions": a_to_b + b_to_a,
                    "total_trials_in_pair": total,
                    "pair_confusion_rate": (a_to_b + b_to_a) / total if total else np.nan,
                })

    return pd.DataFrame(rows)


def save_confusion_matrix(g, out_path, title):
    labels = sorted(set(g["target_label"]).union(set(g["selected_label"])))
    labels = [x for x in labels if str(x).strip() and str(x).lower() != "nan"]

    if not labels:
        return

    idx = {label: i for i, label in enumerate(labels)}
    mat = np.zeros((len(labels), len(labels)), dtype=int)

    for _, row in g.iterrows():
        t = row["target_label"]
        r = row["selected_label"]
        if t in idx and r in idx:
            mat[idx[t], idx[r]] += 1

    fig, ax = plt.subplots(figsize=(max(5, len(labels) * 0.55), max(5, len(labels) * 0.55)))
    ax.imshow(mat)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Selected")
    ax.set_ylabel("Target")
    ax.set_title(title)

    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, str(mat[i, j]), ha="center", va="center", fontsize=8)

    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()


def plot_subject_day_summary(day_df, out_dir, subject):
    if day_df.empty:
        return

    g = day_df.sort_values("day")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(f"Subject {subject}: day-level change")

    axes[0].plot(g["day"], g["accuracy"], marker="o")
    axes[0].set_ylim(0, 1.05)
    axes[0].set_ylabel("Accuracy")
    axes[0].set_xlabel("Day")
    axes[0].tick_params(axis="x", rotation=45)

    axes[1].plot(g["day"], g["rt_mean_sec"], marker="o")
    axes[1].set_ylabel("Mean RT (s)")
    axes[1].set_xlabel("Day")
    axes[1].tick_params(axis="x", rotation=45)

    plt.tight_layout()
    plt.savefig(out_dir / "day_change.png", dpi=300)
    plt.close()

    if "rt_from_stimulus_mean_sec" in day_df.columns:
        g = day_df.sort_values("day")
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        fig.suptitle(f"Subject {subject}: day-level RT comparison")

        axes[0].plot(g["day"], g["rt_mean_sec"], marker="o")
        axes[0].set_ylabel("RT onset (s)")
        axes[0].set_xlabel("Day")
        axes[0].tick_params(axis="x", rotation=45)

        axes[1].plot(g["day"], g["rt_from_stimulus_mean_sec"], marker="o")
        axes[1].set_ylabel("RT after stimulus (s)")
        axes[1].set_xlabel("Day")
        axes[1].tick_params(axis="x", rotation=45)

        plt.tight_layout()
        plt.savefig(out_dir / "day_change_rt_comparison.png", dpi=300)
        plt.close()


def plot_subject_session_summary(session_df, out_dir, subject):
    if session_df.empty:
        return

    for day, g in session_df.groupby("day"):
        g = g.sort_values("session_order")

        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        fig.suptitle(f"Subject {subject} | {day}: session summary")

        x = np.arange(len(g))
        labels = g["session_label"].tolist()

        axes[0].bar(x, g["accuracy"])
        axes[0].set_ylim(0, 1.05)
        axes[0].set_title("Accuracy")

        axes[1].bar(x, g["rt_mean_sec"])
        axes[1].set_title("RT")

        axes[2].bar(x, g["n_trials"])
        axes[2].set_title("Trials")

        for ax in axes:
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=45, ha="right")

        plt.tight_layout()
        plt.savefig(out_dir / f"session_summary_day_{safe_name(day)}.png", dpi=300)
        plt.close()

    # Additional RT plot using stimulus-end-corrected RT if available.
    if "rt_from_stimulus_mean_sec" in session_df.columns:
        for day, g in session_df.groupby("day"):
            g = g.sort_values("session_order")
            fig, axes = plt.subplots(1, 2, figsize=(12, 4))
            fig.suptitle(f"Subject {subject} | {day}: RT comparison")

            x = np.arange(len(g))
            labels = g["session_label"].tolist()

            axes[0].bar(x, g["rt_mean_sec"])
            axes[0].set_title("RT: stimulus onset → voice onset")
            axes[0].set_ylabel("RT (s)")

            axes[1].bar(x, g["rt_from_stimulus_mean_sec"])
            axes[1].set_title("RT: stimulus end → voice onset")
            axes[1].set_ylabel("RT after stimulus (s)")

            for ax in axes:
                ax.set_xticks(x)
                ax.set_xticklabels(labels, rotation=45, ha="right")

            plt.tight_layout()
            plt.savefig(out_dir / f"session_summary_rt_comparison_day_{safe_name(day)}.png", dpi=300)
            plt.close()


def plot_learning_curves(df, out_dir):
    curve_dir = out_dir / "learning_curves"
    curve_dir.mkdir(exist_ok=True)

    curve_rows = []

    for (day, session_name), g in df.groupby(["day", "session_name"], dropna=False):
        g = g.sort_values("trial_index_session").copy()
        if g.empty:
            continue

        g["moving_accuracy"] = moving_mean(g["correct"])
        g["moving_rt"] = moving_mean(g["rt_sec"])
        g["moving_rt_from_stimulus"] = moving_mean(g["rt_from_stimulus_sec"])

        for _, row in g.iterrows():
            curve_rows.append({
                "day": day,
                "session_name": session_name,
                "trial_index_session": row["trial_index_session"],
                "correct": row["correct"],
                "rt_sec": row["rt_sec"],
                "moving_accuracy": row["moving_accuracy"],
                "moving_rt": row["moving_rt"],
                "moving_rt_from_stimulus": row["moving_rt_from_stimulus"],
                "target_label": row["target_label"],
                "selected_label": row["selected_label"],
            })

        fig, ax1 = plt.subplots(figsize=(8, 4))
        ax1.plot(g["trial_index_session"], g["moving_accuracy"], marker="o")
        ax1.set_ylim(0, 1.05)
        ax1.set_xlabel("Trial in session")
        ax1.set_ylabel(f"Moving accuracy (window={MOVING_WINDOW})")
        ax1.set_title(f"{day} | {SESSION_LABELS.get(session_name, session_name)}")

        ax2 = ax1.twinx()
        ax2.plot(g["trial_index_session"], g["moving_rt"], marker="x", alpha=0.7)
        ax2.set_ylabel(f"Moving RT (s)")

        plt.tight_layout()
        plt.savefig(curve_dir / f"day_{safe_name(day)}_{safe_name(session_name)}_curve.png", dpi=300)
        plt.close()

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(g["trial_index_session"], g["moving_rt"], marker="x", label="RT onset")
        ax.plot(g["trial_index_session"], g["moving_rt_from_stimulus"], marker="o", label="RT after stimulus")
        ax.set_xlabel("Trial in session")
        ax.set_ylabel("RT (s)")
        ax.set_title(f"{day} | {SESSION_LABELS.get(session_name, session_name)} RT comparison")
        ax.legend()
        ax.grid(alpha=0.25)
        plt.tight_layout()
        plt.savefig(curve_dir / f"day_{safe_name(day)}_{safe_name(session_name)}_rt_comparison_curve.png", dpi=300)
        plt.close()

    pd.DataFrame(curve_rows).to_csv(out_dir / "learning_curve_points.csv", index=False, encoding="utf-8-sig")


def plot_item_summary(item_df, out_dir):
    item_dir = out_dir / "item_plots"
    item_dir.mkdir(exist_ok=True)

    if item_df.empty:
        return

    for (day, session_name), g in item_df.groupby(["day", "session_name"]):
        group = (
            g.groupby("target_label", as_index=False)
            .agg(
                accuracy=("accuracy", "mean"),
                rt_mean_sec=("rt_mean_sec", "mean"),
                rt_from_stimulus_mean_sec=("rt_from_stimulus_mean_sec", "mean"),
                n_trials=("n_trials", "sum"),
            )
        )

        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        fig.suptitle(f"{day} | {SESSION_LABELS.get(session_name, session_name)}")

        axes[0].bar(group["target_label"], group["accuracy"])
        axes[0].set_ylim(0, 1.05)
        axes[0].set_ylabel("Accuracy")
        axes[0].set_title("Item accuracy")

        axes[1].bar(group["target_label"], group["rt_mean_sec"])
        axes[1].set_ylabel("RT onset (s)")
        axes[1].set_title("Item RT onset")

        plt.tight_layout()
        plt.savefig(item_dir / f"day_{safe_name(day)}_{safe_name(session_name)}_items.png", dpi=300)
        plt.close()

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.bar(group["target_label"], group["rt_from_stimulus_mean_sec"])
        ax.set_ylabel("RT after stimulus (s)")
        ax.set_title(f"{day} | {SESSION_LABELS.get(session_name, session_name)} item RT after stimulus")
        plt.tight_layout()
        plt.savefig(item_dir / f"day_{safe_name(day)}_{safe_name(session_name)}_items_rt_after_stimulus.png", dpi=300)
        plt.close()



def plot_day_session_learning_curves(df, out_dir, subject):
    """For each subject, plot day-by-day learning curves for each session.

    This directly shows, for example:
    Day 1 - Session 1: how moving accuracy/RT changed across trials.
    """
    out = out_dir / "day_session_learning_curves"
    out.mkdir(exist_ok=True)

    if df.empty:
        return

    for day, gday in df.groupby("day"):
        sessions = [s for s in SESSION_ORDER if s in set(gday["session_name"])]
        if not sessions:
            continue

        n = len(sessions)
        fig, axes = plt.subplots(n, 2, figsize=(12, max(3.2, 3.0 * n)), squeeze=False)
        fig.suptitle(f"Subject {subject} | Day {day}: learning curves by session", fontsize=14)

        for row_idx, session_name in enumerate(sessions):
            g = gday[gday["session_name"] == session_name].sort_values("trial_index_session").copy()
            if g.empty:
                continue

            g["moving_accuracy"] = moving_mean(g["correct"])
            g["moving_rt"] = moving_mean(g["rt_sec"])
            g["moving_rt_from_stimulus"] = moving_mean(g["rt_from_stimulus_sec"])

            ax_acc = axes[row_idx, 0]
            ax_rt = axes[row_idx, 1]

            ax_acc.plot(g["trial_index_session"], g["moving_accuracy"], marker="o", linewidth=1.5)
            ax_acc.scatter(g["trial_index_session"], g["correct"], alpha=0.25, s=20)
            ax_acc.set_ylim(-0.05, 1.05)
            ax_acc.set_ylabel("Accuracy")
            ax_acc.set_title(f"{SESSION_LABELS.get(session_name, session_name)}")
            ax_acc.set_xlabel("Trial in session")
            ax_acc.grid(alpha=0.25)

            ax_rt.plot(g["trial_index_session"], g["moving_rt"], marker="x", linewidth=1.5, label="RT onset")
            ax_rt.plot(g["trial_index_session"], g["moving_rt_from_stimulus"], marker="o", linewidth=1.5, label="RT after stimulus")
            ax_rt.scatter(g["trial_index_session"], g["rt_sec"], alpha=0.20, s=20)
            ax_rt.scatter(g["trial_index_session"], g["rt_from_stimulus_sec"], alpha=0.20, s=20)
            ax_rt.set_ylabel("RT (s)")
            ax_rt.legend(fontsize=8)
            ax_rt.set_title(f"{SESSION_LABELS.get(session_name, session_name)}")
            ax_rt.set_xlabel("Trial in session")
            ax_rt.grid(alpha=0.25)

        plt.tight_layout()
        plt.savefig(out / f"subject_{safe_name(subject)}_day_{safe_name(day)}_session_learning_curves.png", dpi=300)
        plt.close()


def plot_day_session_trial_counts(session_df, out_dir, subject):
    """Visualize how many trials were used for each session on each day."""
    out = out_dir / "day_session_progress"
    out.mkdir(exist_ok=True)

    if session_df.empty:
        return

    pivot_trials = session_df.pivot_table(
        index="day",
        columns="session_label",
        values="n_trials",
        aggfunc="sum",
        fill_value=0,
    )

    session_labels = [
        SESSION_LABELS[s] for s in SESSION_ORDER
        if SESSION_LABELS[s] in pivot_trials.columns
    ]
    pivot_trials = pivot_trials.reindex(columns=session_labels)

    fig, ax = plt.subplots(figsize=(max(8, 1.4 * len(session_labels)), 5))
    pivot_trials.plot(kind="bar", ax=ax)
    ax.set_title(f"Subject {subject}: number of trials by day and session")
    ax.set_xlabel("Day")
    ax.set_ylabel("Number of trials")
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    plt.savefig(out / "day_by_session_trial_counts.png", dpi=300)
    plt.close()

    # Heatmap
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(session_labels)), max(3, 0.7 * len(pivot_trials))))
    im = ax.imshow(pivot_trials.values, aspect="auto")

    ax.set_xticks(range(len(pivot_trials.columns)))
    ax.set_xticklabels(pivot_trials.columns, rotation=45, ha="right")

    ax.set_yticks(range(len(pivot_trials.index)))
    ax.set_yticklabels(pivot_trials.index)

    ax.set_title(f"Subject {subject}: trial-count heatmap")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(pivot_trials.shape[0]):
        for j in range(pivot_trials.shape[1]):
            ax.text(j, i, str(int(pivot_trials.values[i, j])), ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Trials")
    plt.tight_layout()
    plt.savefig(out / "day_by_session_trial_count_heatmap.png", dpi=300)
    plt.close()

    # Completion status heatmap
    if "completed" in session_df.columns:
        pivot_completed = session_df.pivot_table(
            index="day",
            columns="session_label",
            values="completed",
            aggfunc="max",
            fill_value=0,
        )
        pivot_completed = pivot_completed.reindex(columns=session_labels)

        fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(session_labels)), max(3, 0.7 * len(pivot_completed))))
        im = ax.imshow(pivot_completed.values, aspect="auto", vmin=0, vmax=1)

        ax.set_xticks(range(len(pivot_completed.columns)))
        ax.set_xticklabels(pivot_completed.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(pivot_completed.index)))
        ax.set_yticklabels(pivot_completed.index)

        ax.set_title(f"Subject {subject}: session completion by day")
        ax.set_xlabel("Session")
        ax.set_ylabel("Day")

        for i in range(pivot_completed.shape[0]):
            for j in range(pivot_completed.shape[1]):
                txt = "Done" if int(pivot_completed.values[i, j]) == 1 else "-"
                ax.text(j, i, txt, ha="center", va="center", fontsize=9)

        plt.colorbar(im, ax=ax, label="Completed")
        plt.tight_layout()
        plt.savefig(out / "day_by_session_completion_heatmap.png", dpi=300)
        plt.close()


def plot_group_day_session_trial_counts(session_df, group_dir):
    """Group-level visualization of trial counts by day/session."""
    out = group_dir / "day_session_progress"
    out.mkdir(exist_ok=True)

    if session_df.empty:
        return

    group = (
        session_df
        .groupby(["day", "session_label"], as_index=False)
        .agg(
            mean_trials=("n_trials", "mean"),
            sem_trials=("n_trials", sem),
            mean_accuracy=("accuracy", "mean"),
            sem_accuracy=("accuracy", sem),
            mean_rt=("rt_mean_sec", "mean"),
            sem_rt=("rt_mean_sec", sem),
            n_subjects=("subject", "nunique"),
        )
    )

    group.to_csv(out / "group_day_session_summary.csv", index=False, encoding="utf-8-sig")

    session_labels = [SESSION_LABELS[s] for s in SESSION_ORDER]
    days = sorted(group["day"].dropna().unique())

    # Mean trials heatmap
    pivot_trials = group.pivot_table(
        index="day",
        columns="session_label",
        values="mean_trials",
        aggfunc="mean",
        fill_value=np.nan,
    ).reindex(index=days, columns=[s for s in session_labels if s in group["session_label"].unique()])

    fig, ax = plt.subplots(figsize=(max(8, 1.2 * pivot_trials.shape[1]), max(3, 0.7 * pivot_trials.shape[0])))
    im = ax.imshow(pivot_trials.values, aspect="auto")

    ax.set_xticks(range(len(pivot_trials.columns)))
    ax.set_xticklabels(pivot_trials.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(pivot_trials.index)))
    ax.set_yticklabels(pivot_trials.index)
    ax.set_title("Group mean trial counts by day and session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(pivot_trials.shape[0]):
        for j in range(pivot_trials.shape[1]):
            val = pivot_trials.values[i, j]
            txt = "" if np.isnan(val) else f"{val:.1f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Mean trials")
    plt.tight_layout()
    plt.savefig(out / "group_day_by_session_trial_count_heatmap.png", dpi=300)
    plt.close()

    # Mean accuracy heatmap
    pivot_acc = group.pivot_table(
        index="day",
        columns="session_label",
        values="mean_accuracy",
        aggfunc="mean",
        fill_value=np.nan,
    ).reindex(index=days, columns=pivot_trials.columns)

    fig, ax = plt.subplots(figsize=(max(8, 1.2 * pivot_acc.shape[1]), max(3, 0.7 * pivot_acc.shape[0])))
    im = ax.imshow(pivot_acc.values, aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(pivot_acc.columns)))
    ax.set_xticklabels(pivot_acc.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(pivot_acc.index)))
    ax.set_yticklabels(pivot_acc.index)
    ax.set_title("Group mean accuracy by day and session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(pivot_acc.shape[0]):
        for j in range(pivot_acc.shape[1]):
            val = pivot_acc.values[i, j]
            txt = "" if np.isnan(val) else f"{val:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Mean accuracy")
    plt.tight_layout()
    plt.savefig(out / "group_day_by_session_accuracy_heatmap.png", dpi=300)
    plt.close()


def plot_group_day_session_learning_curves(df, group_dir):
    """Group-average moving learning curves for each day/session.

    Each subject-day-session curve is first computed, then averaged by trial index.
    This allows incomplete days/sessions to be included without requiring all sessions.
    """
    out = group_dir / "day_session_learning_curves"
    out.mkdir(exist_ok=True)

    rows = []
    for (subject, day, session_name), g in df.groupby(["subject", "day", "session_name"], dropna=False):
        g = g.sort_values("trial_index_session").copy()
        if g.empty:
            continue
        g["moving_accuracy"] = moving_mean(g["correct"])
        g["moving_rt"] = moving_mean(g["rt_sec"])

        for _, r in g.iterrows():
            rows.append({
                "subject": subject,
                "day": day,
                "session_name": session_name,
                "session_label": SESSION_LABELS.get(session_name, session_name),
                "trial_index_session": r["trial_index_session"],
                "moving_accuracy": r["moving_accuracy"],
                "moving_rt": r["moving_rt"],
            })

    curve = pd.DataFrame(rows)
    curve.to_csv(out / "group_learning_curve_points.csv", index=False, encoding="utf-8-sig")

    if curve.empty:
        return

    for day, gday in curve.groupby("day"):
        sessions = [s for s in SESSION_ORDER if s in set(gday["session_name"])]
        if not sessions:
            continue

        n = len(sessions)
        fig, axes = plt.subplots(n, 2, figsize=(12, max(3.2, 3.0 * n)), squeeze=False)
        fig.suptitle(f"Group | Day {day}: learning curves by session", fontsize=14)

        for row_idx, session_name in enumerate(sessions):
            gs = gday[gday["session_name"] == session_name].copy()
            grouped = (
                gs.groupby("trial_index_session", as_index=False)
                .agg(
                    mean_moving_accuracy=("moving_accuracy", "mean"),
                    sem_moving_accuracy=("moving_accuracy", sem),
                    mean_moving_rt=("moving_rt", "mean"),
                    sem_moving_rt=("moving_rt", sem),
                    n_subjects=("subject", "nunique"),
                )
            )

            ax_acc = axes[row_idx, 0]
            ax_rt = axes[row_idx, 1]

            x = grouped["trial_index_session"].values

            ax_acc.plot(x, grouped["mean_moving_accuracy"], marker="o")
            ax_acc.fill_between(
                x,
                grouped["mean_moving_accuracy"] - grouped["sem_moving_accuracy"],
                grouped["mean_moving_accuracy"] + grouped["sem_moving_accuracy"],
                alpha=0.2,
            )
            ax_acc.set_ylim(0, 1.05)
            ax_acc.set_ylabel("Moving accuracy")
            ax_acc.set_xlabel("Trial in session")
            ax_acc.set_title(SESSION_LABELS.get(session_name, session_name))
            ax_acc.grid(alpha=0.25)

            ax_rt.plot(x, grouped["mean_moving_rt"], marker="x")
            ax_rt.fill_between(
                x,
                grouped["mean_moving_rt"] - grouped["sem_moving_rt"],
                grouped["mean_moving_rt"] + grouped["sem_moving_rt"],
                alpha=0.2,
            )
            ax_rt.set_ylabel("Moving RT (s)")
            ax_rt.set_xlabel("Trial in session")
            ax_rt.set_title(SESSION_LABELS.get(session_name, session_name))
            ax_rt.grid(alpha=0.25)

        plt.tight_layout()
        plt.savefig(out / f"group_day_{safe_name(day)}_session_learning_curves.png", dpi=300)
        plt.close()


def plot_subject_day_change_by_session(session_df, out_dir, subject):
    """Plot day-level change separately for each session.

    This supplements day_change.png (overall day average) by showing:
    - how accuracy changes across days for each session
    - how RT changes across days for each session
    """
    out = out_dir / "day_level_session_change"
    out.mkdir(exist_ok=True)

    if session_df.empty:
        return

    g = session_df.sort_values(["day", "session_order"]).copy()
    if g.empty:
        return

    sessions_present = [s for s in SESSION_ORDER if s in set(g["session_name"])]
    if not sessions_present:
        return

    # Pivot for accuracy
    acc_pivot = g.pivot_table(
        index="day",
        columns="session_label",
        values="accuracy",
        aggfunc="mean"
    )

    # Keep canonical session order among existing sessions
    ordered_labels = [SESSION_LABELS[s] for s in sessions_present if SESSION_LABELS[s] in acc_pivot.columns]
    acc_pivot = acc_pivot.reindex(columns=ordered_labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in acc_pivot.columns:
        ax.plot(acc_pivot.index, acc_pivot[col], marker="o", label=col)

    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Accuracy")
    ax.set_xlabel("Day")
    ax.set_title(f"Subject {subject}: day-level accuracy by session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "day_change_by_session_accuracy.png", dpi=300)
    plt.close()

    # Pivot for RT
    rt_pivot = g.pivot_table(
        index="day",
        columns="session_label",
        values="rt_mean_sec",
        aggfunc="mean"
    )
    rt_pivot = rt_pivot.reindex(columns=ordered_labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in rt_pivot.columns:
        ax.plot(rt_pivot.index, rt_pivot[col], marker="o", label=col)

    ax.set_ylabel("RT (s)")
    ax.set_xlabel("Day")
    ax.set_title(f"Subject {subject}: day-level RT by session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "day_change_by_session_rt.png", dpi=300)
    plt.close()

    # Heatmap view for accuracy
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(ordered_labels)), max(3, 0.7 * len(acc_pivot.index))))
    im = ax.imshow(acc_pivot.values, aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(acc_pivot.columns)))
    ax.set_xticklabels(acc_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(acc_pivot.index)))
    ax.set_yticklabels(acc_pivot.index)

    ax.set_title(f"Subject {subject}: accuracy heatmap by day and session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(acc_pivot.shape[0]):
        for j in range(acc_pivot.shape[1]):
            val = acc_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Accuracy")
    plt.tight_layout()
    plt.savefig(out / "day_change_by_session_accuracy_heatmap.png", dpi=300)
    plt.close()

    # Heatmap view for RT
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(ordered_labels)), max(3, 0.7 * len(rt_pivot.index))))
    im = ax.imshow(rt_pivot.values, aspect="auto")

    ax.set_xticks(range(len(rt_pivot.columns)))
    ax.set_xticklabels(rt_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(rt_pivot.index)))
    ax.set_yticklabels(rt_pivot.index)

    ax.set_title(f"Subject {subject}: RT heatmap by day and session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(rt_pivot.shape[0]):
        for j in range(rt_pivot.shape[1]):
            val = rt_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="RT (s)")
    plt.tight_layout()
    plt.savefig(out / "day_change_by_session_rt_heatmap.png", dpi=300)
    plt.close()

    if "rt_from_stimulus_mean_sec" in g.columns:
        rt2_pivot = g.pivot_table(
            index="day",
            columns="session_label",
            values="rt_from_stimulus_mean_sec",
            aggfunc="mean"
        )
        rt2_pivot = rt2_pivot.reindex(columns=ordered_labels)

        fig, ax = plt.subplots(figsize=(10, 5))
        for col in rt2_pivot.columns:
            ax.plot(rt2_pivot.index, rt2_pivot[col], marker="o", label=col)

        ax.set_ylabel("RT after stimulus (s)")
        ax.set_xlabel("Day")
        ax.set_title(f"Subject {subject}: day-level RT after stimulus by session")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=9, loc="best")
        plt.tight_layout()
        plt.savefig(out / "day_change_by_session_rt_after_stimulus.png", dpi=300)
        plt.close()

        fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(ordered_labels)), max(3, 0.7 * len(rt2_pivot.index))))
        im = ax.imshow(rt2_pivot.values, aspect="auto")

        ax.set_xticks(range(len(rt2_pivot.columns)))
        ax.set_xticklabels(rt2_pivot.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(rt2_pivot.index)))
        ax.set_yticklabels(rt2_pivot.index)

        ax.set_title(f"Subject {subject}: RT after stimulus heatmap by day and session")
        ax.set_xlabel("Session")
        ax.set_ylabel("Day")

        for i in range(rt2_pivot.shape[0]):
            for j in range(rt2_pivot.shape[1]):
                val = rt2_pivot.values[i, j]
                txt = "" if pd.isna(val) else f"{val:.2f}"
                ax.text(j, i, txt, ha="center", va="center", fontsize=9)

        plt.colorbar(im, ax=ax, label="RT after stimulus (s)")
        plt.tight_layout()
        plt.savefig(out / "day_change_by_session_rt_after_stimulus_heatmap.png", dpi=300)
        plt.close()


def make_completion_summary(df, session_df):
    """Summarize trials/time required to clear each session by day.

    Completion is defined by the first row where session_completed_after_trial == 1.
    If completion flag is missing or never reaches 1, completed=0 and completion metrics are NaN.
    """
    rows = []

    if df.empty:
        return pd.DataFrame(rows)

    for (subject, day, session_name), g in df.groupby(["subject", "day", "session_name"], dropna=False):
        g = g.sort_values("trial_index_session").copy()

        session_label = SESSION_LABELS.get(session_name, session_name)
        session_order = g["session_order"].iloc[0] if "session_order" in g.columns and len(g) else np.nan

        completed_rows = pd.DataFrame()
        if "session_completed_after_trial" in g.columns:
            comp = pd.to_numeric(g["session_completed_after_trial"], errors="coerce").fillna(0)
            completed_rows = g[comp == 1]

        if len(completed_rows) > 0:
            clear_row = completed_rows.iloc[0]
            completed = 1
            trials_to_clear = clear_row.get("trial_index_session", np.nan)
            time_to_clear_sec = clear_row.get("session_elapsed_sec", np.nan)
            day_elapsed_at_clear_sec = clear_row.get("day_elapsed_sec", np.nan)
        else:
            completed = 0
            trials_to_clear = np.nan
            time_to_clear_sec = np.nan
            day_elapsed_at_clear_sec = np.nan

        rows.append({
            "subject": subject,
            "day": day,
            "session_name": session_name,
            "session_label": session_label,
            "session_order": session_order,
            "completed": completed,
            "trials_to_clear": trials_to_clear,
            "time_to_clear_sec": time_to_clear_sec,
            "time_to_clear_min": time_to_clear_sec / 60 if pd.notna(time_to_clear_sec) else np.nan,
            "day_elapsed_at_clear_sec": day_elapsed_at_clear_sec,
            "day_elapsed_at_clear_min": day_elapsed_at_clear_sec / 60 if pd.notna(day_elapsed_at_clear_sec) else np.nan,
            "total_trials_recorded": len(g),
            "total_session_elapsed_sec": g["session_elapsed_sec"].max() if "session_elapsed_sec" in g.columns else np.nan,
            "total_session_elapsed_min": (g["session_elapsed_sec"].max() / 60) if "session_elapsed_sec" in g.columns and pd.notna(g["session_elapsed_sec"].max()) else np.nan,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    return out.sort_values(["subject", "day", "session_order"])


def plot_subject_completion_by_day(completion_df, out_dir, subject):
    """Plot day-level changes in trials/time to clear each session for one subject."""
    out = out_dir / "completion_by_day"
    out.mkdir(exist_ok=True)

    if completion_df.empty:
        return

    g = completion_df.copy()
    g = g[g["completed"] == 1].copy()

    if g.empty:
        return

    sessions_present = [s for s in SESSION_ORDER if s in set(g["session_name"])]
    ordered_labels = [SESSION_LABELS[s] for s in sessions_present]

    # Trials to clear line plot
    trial_pivot = g.pivot_table(
        index="day",
        columns="session_label",
        values="trials_to_clear",
        aggfunc="mean"
    ).reindex(columns=ordered_labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in trial_pivot.columns:
        ax.plot(trial_pivot.index, trial_pivot[col], marker="o", label=col)

    ax.set_ylabel("Trials to clear")
    ax.set_xlabel("Day")
    ax.set_title(f"Subject {subject}: trials required to clear each session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "trials_to_clear_by_day.png", dpi=300)
    plt.close()

    # Time to clear line plot
    time_pivot = g.pivot_table(
        index="day",
        columns="session_label",
        values="time_to_clear_min",
        aggfunc="mean"
    ).reindex(columns=ordered_labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in time_pivot.columns:
        ax.plot(time_pivot.index, time_pivot[col], marker="o", label=col)

    ax.set_ylabel("Time to clear (min)")
    ax.set_xlabel("Day")
    ax.set_title(f"Subject {subject}: time required to clear each session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "time_to_clear_by_day.png", dpi=300)
    plt.close()

    # Trials heatmap
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(trial_pivot.columns)), max(3, 0.7 * len(trial_pivot.index))))
    im = ax.imshow(trial_pivot.values, aspect="auto")

    ax.set_xticks(range(len(trial_pivot.columns)))
    ax.set_xticklabels(trial_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(trial_pivot.index)))
    ax.set_yticklabels(trial_pivot.index)
    ax.set_title(f"Subject {subject}: trials to clear heatmap")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(trial_pivot.shape[0]):
        for j in range(trial_pivot.shape[1]):
            val = trial_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.0f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Trials")
    plt.tight_layout()
    plt.savefig(out / "trials_to_clear_heatmap.png", dpi=300)
    plt.close()

    # Time heatmap
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(time_pivot.columns)), max(3, 0.7 * len(time_pivot.index))))
    im = ax.imshow(time_pivot.values, aspect="auto")

    ax.set_xticks(range(len(time_pivot.columns)))
    ax.set_xticklabels(time_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(time_pivot.index)))
    ax.set_yticklabels(time_pivot.index)
    ax.set_title(f"Subject {subject}: time to clear heatmap")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(time_pivot.shape[0]):
        for j in range(time_pivot.shape[1]):
            val = time_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.1f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Minutes")
    plt.tight_layout()
    plt.savefig(out / "time_to_clear_heatmap.png", dpi=300)
    plt.close()


def plot_group_completion_by_day(completion_df, group_dir):
    """Group-level trials/time-to-clear by day and session."""
    out = group_dir / "completion_by_day"
    out.mkdir(exist_ok=True)

    if completion_df.empty:
        return

    completed = completion_df[completion_df["completed"] == 1].copy()

    if completed.empty:
        return

    group = (
        completed
        .groupby(["day", "session_name", "session_label", "session_order"], as_index=False)
        .agg(
            mean_trials_to_clear=("trials_to_clear", "mean"),
            sem_trials_to_clear=("trials_to_clear", sem),
            mean_time_to_clear_min=("time_to_clear_min", "mean"),
            sem_time_to_clear_min=("time_to_clear_min", sem),
            n_subjects=("subject", "nunique"),
        )
        .sort_values(["day", "session_order"])
    )

    group.to_csv(out / "group_completion_by_day_session.csv", index=False, encoding="utf-8-sig")

    sessions_present = [s for s in SESSION_ORDER if s in set(group["session_name"])]
    ordered_labels = [SESSION_LABELS[s] for s in sessions_present]

    # Trials line plot
    trial_pivot = group.pivot_table(
        index="day",
        columns="session_label",
        values="mean_trials_to_clear",
        aggfunc="mean"
    ).reindex(columns=ordered_labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in trial_pivot.columns:
        ax.plot(trial_pivot.index, trial_pivot[col], marker="o", label=col)

    ax.set_ylabel("Mean trials to clear")
    ax.set_xlabel("Day")
    ax.set_title("Group: trials required to clear each session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "group_trials_to_clear_by_day.png", dpi=300)
    plt.close()

    # Time line plot
    time_pivot = group.pivot_table(
        index="day",
        columns="session_label",
        values="mean_time_to_clear_min",
        aggfunc="mean"
    ).reindex(columns=ordered_labels)

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in time_pivot.columns:
        ax.plot(time_pivot.index, time_pivot[col], marker="o", label=col)

    ax.set_ylabel("Mean time to clear (min)")
    ax.set_xlabel("Day")
    ax.set_title("Group: time required to clear each session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "group_time_to_clear_by_day.png", dpi=300)
    plt.close()

    # Heatmap: trials
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(trial_pivot.columns)), max(3, 0.7 * len(trial_pivot.index))))
    im = ax.imshow(trial_pivot.values, aspect="auto")

    ax.set_xticks(range(len(trial_pivot.columns)))
    ax.set_xticklabels(trial_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(trial_pivot.index)))
    ax.set_yticklabels(trial_pivot.index)
    ax.set_title("Group: trials to clear heatmap")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(trial_pivot.shape[0]):
        for j in range(trial_pivot.shape[1]):
            val = trial_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.1f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Mean trials")
    plt.tight_layout()
    plt.savefig(out / "group_trials_to_clear_heatmap.png", dpi=300)
    plt.close()

    # Heatmap: time
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(time_pivot.columns)), max(3, 0.7 * len(time_pivot.index))))
    im = ax.imshow(time_pivot.values, aspect="auto")

    ax.set_xticks(range(len(time_pivot.columns)))
    ax.set_xticklabels(time_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(time_pivot.index)))
    ax.set_yticklabels(time_pivot.index)
    ax.set_title("Group: time to clear heatmap")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")

    for i in range(time_pivot.shape[0]):
        for j in range(time_pivot.shape[1]):
            val = time_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.1f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)

    plt.colorbar(im, ax=ax, label="Mean minutes")
    plt.tight_layout()
    plt.savefig(out / "group_time_to_clear_heatmap.png", dpi=300)
    plt.close()


def make_syllable_summary(df):
    """Summarize syllable sessions 7-9.

    Handles:
    - Session 7: top50 choice
    - Session 8: top100 choice
    - Session 9: top200 typed
    """
    syll = df[df["session_name"].astype(str).str.startswith("syllable")].copy()

    if syll.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Per subject/day/session
    session_rows = []
    for (subject, day, session_name), g in syll.groupby(["subject", "day", "session_name"], dropna=False):
        g = g.copy()

        session_rows.append({
            "subject": subject,
            "day": day,
            "session_name": session_name,
            "session_label": SESSION_LABELS.get(session_name, session_name),
            "session_order": g["session_order"].iloc[0] if len(g) else np.nan,
            "response_mode": g["response_mode"].dropna().iloc[0] if len(g["response_mode"].dropna()) else "",
            "n_trials": len(g),
            "n_unique_syllables": g["target_label"].nunique(),
            "mean_reps_per_syllable": len(g) / g["target_label"].nunique() if g["target_label"].nunique() > 0 else np.nan,
            "accuracy": g["correct"].mean(),
            "rt_mean_sec": g["rt_sec"].mean(),
            "rt_median_sec": g["rt_sec"].median(),
            "rt_from_stimulus_mean_sec": g["rt_from_stimulus_sec"].mean(),
            "rt_from_stimulus_median_sec": g["rt_from_stimulus_sec"].median(),
            "n_correct": int((g["correct"] == 1).sum()),
            "n_errors": int((g["correct"] == 0).sum()),
        })

    syllable_session_summary = pd.DataFrame(session_rows)

    # Per syllable
    item = (
        syll
        .groupby(["subject", "day", "session_name", "target_label"], as_index=False)
        .agg(
            n_trials=("correct", "size"),
            accuracy=("correct", "mean"),
            rt_mean_sec=("rt_sec", "mean"),
            rt_median_sec=("rt_sec", "median"),
            rt_from_stimulus_mean_sec=("rt_from_stimulus_sec", "mean"),
            rt_from_stimulus_median_sec=("rt_from_stimulus_sec", "median"),
            n_errors=("correct", lambda x: int((pd.to_numeric(x, errors="coerce") == 0).sum())),
            most_common_response=("selected_label", lambda x: x.value_counts().index[0] if len(x.dropna()) else ""),
        )
    )

    item["session_label"] = item["session_name"].map(SESSION_LABELS).fillna(item["session_name"])
    item["session_order"] = item["session_name"].map({name: i + 1 for i, name in enumerate(SESSION_ORDER)})

    return syllable_session_summary, item.sort_values(["subject", "day", "session_order", "target_label"])


def plot_subject_syllable_summary(syll_session, syll_item, out_dir, subject):
    out = out_dir / "syllable_analysis"
    out.mkdir(exist_ok=True)

    if syll_session.empty:
        return

    syll_session = syll_session.copy()
    syll_item = syll_item.copy()
    if "rt_from_stimulus_mean_sec" not in syll_session.columns and "rt_mean_sec" in syll_session.columns:
        syll_session["rt_from_stimulus_mean_sec"] = syll_session["rt_mean_sec"]
    if "rt_from_stimulus_mean_sec" not in syll_item.columns and "rt_mean_sec" in syll_item.columns:
        syll_item["rt_from_stimulus_mean_sec"] = syll_item["rt_mean_sec"]

    syll_session.to_csv(out / "syllable_session_summary.csv", index=False, encoding="utf-8-sig")
    syll_item.to_csv(out / "syllable_item_summary.csv", index=False, encoding="utf-8-sig")

    # Session-level accuracy/RT
    for day, gday in syll_session.groupby("day"):
        gday = gday.sort_values("session_order")

        fig, axes = plt.subplots(1, 3, figsize=(14, 4))
        fig.suptitle(f"Subject {subject} | Day {day}: syllable sessions")

        x = np.arange(len(gday))
        labels = gday["session_label"].tolist()

        axes[0].bar(x, gday["accuracy"])
        axes[0].set_ylim(0, 1.05)
        axes[0].set_title("Accuracy")

        axes[1].bar(x, gday["rt_mean_sec"])
        axes[1].set_title("RT")

        axes[2].bar(x, gday["n_trials"])
        axes[2].set_title("Trials")

        for ax in axes:
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=45, ha="right")

        plt.tight_layout()
        plt.savefig(out / f"day_{safe_name(day)}_syllable_session_summary.png", dpi=300)
        plt.close()

    # Item-level plots by session
    for (day, session_name), g in syll_item.groupby(["day", "session_name"]):
        if g.empty:
            continue

        # For top200 there may be many labels; create a wider figure.
        fig_w = max(10, min(40, 0.25 * len(g)))
        fig, ax = plt.subplots(figsize=(fig_w, 4))

        ax.bar(g["target_label"], g["accuracy"])
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("Accuracy")
        ax.set_xlabel("Syllable")
        ax.set_title(f"Subject {subject} | {day} | {SESSION_LABELS.get(session_name, session_name)} item accuracy")
        ax.tick_params(axis="x", rotation=90)

        plt.tight_layout()
        plt.savefig(out / f"day_{safe_name(day)}_{safe_name(session_name)}_syllable_accuracy.png", dpi=300)
        plt.close()

        fig, ax = plt.subplots(figsize=(fig_w, 4))
        ax.bar(g["target_label"], g["rt_mean_sec"])
        ax.set_ylabel("RT (s)")
        ax.set_xlabel("Syllable")
        ax.set_title(f"Subject {subject} | {day} | {SESSION_LABELS.get(session_name, session_name)} item RT")
        ax.tick_params(axis="x", rotation=90)

        plt.tight_layout()
        plt.savefig(out / f"day_{safe_name(day)}_{safe_name(session_name)}_syllable_rt.png", dpi=300)
        plt.close()


def plot_group_syllable_summary(syll_session, syll_item, group_dir):
    out = group_dir / "syllable_analysis"
    out.mkdir(exist_ok=True)

    if syll_session.empty:
        return

    group_sess = (
        syll_session
        .groupby(["session_name", "session_label", "session_order"], as_index=False)
        .agg(
            mean_accuracy=("accuracy", "mean"),
            sem_accuracy=("accuracy", sem),
            mean_rt=("rt_mean_sec", "mean"),
            sem_rt=("rt_mean_sec", sem),
            mean_trials=("n_trials", "mean"),
            n_subject_days=("accuracy", "count"),
            n_subjects=("subject", "nunique"),
        )
        .sort_values("session_order")
    )

    group_sess.to_csv(out / "group_syllable_session_summary.csv", index=False, encoding="utf-8-sig")

    if not syll_item.empty:
        group_item = (
            syll_item
            .groupby(["session_name", "session_label", "target_label"], as_index=False)
            .agg(
                mean_accuracy=("accuracy", "mean"),
                sem_accuracy=("accuracy", sem),
                mean_rt=("rt_mean_sec", "mean"),
                sem_rt=("rt_mean_sec", sem),
                mean_rt_from_stimulus=("rt_from_stimulus_mean_sec", "mean"),
                sem_rt_from_stimulus=("rt_from_stimulus_mean_sec", sem),
                total_trials=("n_trials", "sum"),
                n_subjects=("subject", "nunique"),
            )
        )
        group_item.to_csv(out / "group_syllable_item_summary.csv", index=False, encoding="utf-8-sig")
    else:
        group_item = pd.DataFrame()

    # Session-level plot
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    x = np.arange(len(group_sess))
    labels = group_sess["session_label"].tolist()

    axes[0].bar(x, group_sess["mean_accuracy"], yerr=group_sess["sem_accuracy"], capsize=3)
    axes[0].set_ylim(0, 1.05)
    axes[0].set_title("Group syllable accuracy")

    axes[1].bar(x, group_sess["mean_rt"], yerr=group_sess["sem_rt"], capsize=3)
    axes[1].set_title("Group syllable RT")

    axes[2].bar(x, group_sess["mean_trials"])
    axes[2].set_title("Mean trials")

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")

    plt.tight_layout()
    plt.savefig(out / "group_syllable_session_summary.png", dpi=300)
    plt.close()

    # Item-level plots
    if not group_item.empty:
        for session_name, g in group_item.groupby("session_name"):
            g = g.sort_values("target_label")
            fig_w = max(10, min(40, 0.25 * len(g)))

            fig, ax = plt.subplots(figsize=(fig_w, 4))
            ax.bar(g["target_label"], g["mean_accuracy"], yerr=g["sem_accuracy"], capsize=2)
            ax.set_ylim(0, 1.05)
            ax.set_ylabel("Accuracy")
            ax.set_xlabel("Syllable")
            ax.set_title(f"Group {SESSION_LABELS.get(session_name, session_name)} item accuracy")
            ax.tick_params(axis="x", rotation=90)
            plt.tight_layout()
            plt.savefig(out / f"{safe_name(session_name)}_group_syllable_accuracy.png", dpi=300)
            plt.close()

            fig, ax = plt.subplots(figsize=(fig_w, 4))
            ax.bar(g["target_label"], g["mean_rt"], yerr=g["sem_rt"], capsize=2)
            ax.set_ylabel("RT (s)")
            ax.set_xlabel("Syllable")
            ax.set_title(f"Group {SESSION_LABELS.get(session_name, session_name)} item RT")
            ax.tick_params(axis="x", rotation=90)
            plt.tight_layout()
            plt.savefig(out / f"{safe_name(session_name)}_group_syllable_rt.png", dpi=300)
            plt.close()



def voice_engine_summary(df):
    """Summarize recognition engine and STT model use."""
    cols = [c for c in ["subject", "day", "session_name", "voice_engine", "stt_model"] if c in df.columns]
    if df.empty or "voice_engine" not in df.columns:
        return pd.DataFrame()

    out = (
        df.groupby(cols, dropna=False, as_index=False)
        .agg(
            n_trials=("correct", "size"),
            accuracy=("correct", "mean"),
            rt_mean_sec=("rt_sec", "mean"),
            rt_from_stimulus_mean_sec=("rt_from_stimulus_sec", "mean"),
            process_time_mean_sec=("voice_process_time_sec", "mean"),
        )
    )
    return out


def interval_summary(df):
    """Summarize effects of stimulus interval settings."""
    if "within_unit_interval_ms" not in df.columns or "cv_interval_ms" not in df.columns:
        return pd.DataFrame()

    out = (
        df.groupby(["subject", "day", "session_name", "within_unit_interval_ms", "cv_interval_ms"], dropna=False, as_index=False)
        .agg(
            n_trials=("correct", "size"),
            accuracy=("correct", "mean"),
            rt_mean_sec=("rt_sec", "mean"),
            rt_from_stimulus_mean_sec=("rt_from_stimulus_sec", "mean"),
        )
    )
    return out


def top_candidate_summary(df):
    """Check whether the final target appeared in the Top candidates."""
    if "top_candidates" not in df.columns:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        target = str(r.get("target_label", ""))
        raw = r.get("top_candidates", "")
        labels = []
        try:
            import json
            obj = json.loads(raw) if isinstance(raw, str) and raw else []
            if isinstance(obj, list):
                for x in obj:
                    if isinstance(x, dict):
                        labels.append(str(x.get("label", "")))
                    elif isinstance(x, (list, tuple)) and x:
                        labels.append(str(x[0]))
                    else:
                        labels.append(str(x))
        except Exception:
            pass
        rows.append({
            "subject": r.get("subject", ""),
            "day": r.get("day", ""),
            "session_name": r.get("session_name", ""),
            "target_in_top_candidates": int(target in labels),
            "top_candidate_count": len(labels),
        })

    tmp = pd.DataFrame(rows)
    if tmp.empty:
        return tmp

    return (
        tmp.groupby(["subject", "day", "session_name"], as_index=False)
        .agg(
            top_hit_rate=("target_in_top_candidates", "mean"),
            mean_top_candidate_count=("top_candidate_count", "mean"),
            n_trials=("target_in_top_candidates", "size"),
        )
    )


def plot_voice_engine_summary(voice_df, out_dir, subject=None):
    if voice_df.empty:
        return
    out = out_dir / "voice_engine_analysis"
    out.mkdir(exist_ok=True)

    voice_df.to_csv(out / "voice_engine_summary.csv", index=False, encoding="utf-8-sig")

    g = voice_df.copy()
    if "session_name" not in g.columns:
        return

    for day, gd in g.groupby("day"):
        gd = gd.sort_values("session_name")
        labels = gd["session_name"].astype(str) + "\\n" + gd["voice_engine"].astype(str)
        x = np.arange(len(gd))

        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        title_subject = f"Subject {subject} | " if subject is not None else ""
        fig.suptitle(f"{title_subject}{day}: voice engine summary")

        axes[0].bar(x, gd["accuracy"])
        axes[0].set_ylim(0, 1.05)
        axes[0].set_title("Accuracy")

        axes[1].bar(x, gd["rt_mean_sec"])
        axes[1].set_title("RT onset")

        axes[2].bar(x, gd["process_time_mean_sec"])
        axes[2].set_title("Processing time")

        for ax in axes:
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=45, ha="right")

        plt.tight_layout()
        plt.savefig(out / f"day_{safe_name(day)}_voice_engine_summary.png", dpi=300)
        plt.close()


def plot_interval_summary(interval_df, out_dir, subject=None):
    if interval_df.empty:
        return
    out = out_dir / "interval_analysis"
    out.mkdir(exist_ok=True)

    interval_df.to_csv(out / "interval_summary.csv", index=False, encoding="utf-8-sig")

    g = interval_df.copy()
    g["interval_label"] = (
        g["within_unit_interval_ms"].astype(str) + " / " +
        g["cv_interval_ms"].astype(str)
    )

    for day, gd in g.groupby("day"):
        grouped = (
            gd.groupby("interval_label", as_index=False)
            .agg(
                accuracy=("accuracy", "mean"),
                rt_mean_sec=("rt_mean_sec", "mean"),
                n_trials=("n_trials", "sum"),
            )
        )
        x = np.arange(len(grouped))
        fig, axes = plt.subplots(1, 3, figsize=(12, 4))
        title_subject = f"Subject {subject} | " if subject is not None else ""
        fig.suptitle(f"{title_subject}{day}: interval settings")

        axes[0].bar(x, grouped["accuracy"])
        axes[0].set_ylim(0, 1.05)
        axes[0].set_title("Accuracy")

        axes[1].bar(x, grouped["rt_mean_sec"])
        axes[1].set_title("RT")

        axes[2].bar(x, grouped["n_trials"])
        axes[2].set_title("Trials")

        for ax in axes:
            ax.set_xticks(x)
            ax.set_xticklabels(grouped["interval_label"], rotation=45, ha="right")

        plt.tight_layout()
        plt.savefig(out / f"day_{safe_name(day)}_interval_summary.png", dpi=300)
        plt.close()

def make_subject_outputs(df, session_df, day_df, item_df, pair_df, completion_df, syll_session_df, syll_item_df, voice_df, interval_df, top_df):
    subject_root = OUT_DIR / "results_by_subject"
    subject_root.mkdir(parents=True, exist_ok=True)

    for subject, gsub in df.groupby("subject"):
        out_dir = subject_root / f"subject_{safe_name(subject)}"
        out_dir.mkdir(parents=True, exist_ok=True)

        gsub.to_csv(out_dir / "all_trials.csv", index=False, encoding="utf-8-sig")

        ss = session_df[session_df["subject"] == subject].copy()
        sd = day_df[day_df["subject"] == subject].copy()
        si = item_df[item_df["subject"] == subject].copy()
        sp = pair_df[pair_df["subject"] == subject].copy() if not pair_df.empty else pd.DataFrame()

        ss.to_csv(out_dir / "summary_by_session.csv", index=False, encoding="utf-8-sig")
        sd.to_csv(out_dir / "summary_by_day.csv", index=False, encoding="utf-8-sig")
        si.to_csv(out_dir / "item_summary.csv", index=False, encoding="utf-8-sig")
        sp.to_csv(out_dir / "pair_confusion_summary.csv", index=False, encoding="utf-8-sig")

        sc = completion_df[completion_df["subject"] == subject].copy() if not completion_df.empty else pd.DataFrame()
        sc.to_csv(out_dir / "completion_summary.csv", index=False, encoding="utf-8-sig")

        ssy = syll_session_df[syll_session_df["subject"] == subject].copy() if not syll_session_df.empty else pd.DataFrame()
        siy = syll_item_df[syll_item_df["subject"] == subject].copy() if not syll_item_df.empty else pd.DataFrame()
        plot_subject_syllable_summary(ssy, siy, out_dir, subject)
        sv = voice_df[voice_df['subject'] == subject].copy() if not voice_df.empty else pd.DataFrame()
        si_int = interval_df[interval_df['subject'] == subject].copy() if not interval_df.empty else pd.DataFrame()
        st = top_df[top_df['subject'] == subject].copy() if not top_df.empty else pd.DataFrame()
        sv.to_csv(out_dir / 'voice_engine_summary.csv', index=False, encoding='utf-8-sig')
        si_int.to_csv(out_dir / 'interval_summary.csv', index=False, encoding='utf-8-sig')
        st.to_csv(out_dir / 'top_candidate_summary.csv', index=False, encoding='utf-8-sig')
        plot_voice_engine_summary(sv, out_dir, subject)
        plot_interval_summary(si_int, out_dir, subject)

        plot_subject_day_summary(sd, out_dir, subject)
        plot_subject_day_change_by_session(ss, out_dir, subject)
        plot_subject_completion_by_day(sc, out_dir, subject)
        plot_subject_session_summary(ss, out_dir, subject)
        plot_day_session_learning_curves(gsub, out_dir, subject)
        plot_day_session_trial_counts(ss, out_dir, subject)
        plot_learning_curves(gsub, out_dir)
        plot_item_summary(si, out_dir)

        cm_dir = out_dir / "confusion_matrices"
        cm_dir.mkdir(exist_ok=True)

        for (day, session_name), g in gsub.groupby(["day", "session_name"]):
            save_confusion_matrix(
                g,
                cm_dir / f"day_{safe_name(day)}_{safe_name(session_name)}_cm.png",
                f"Subject {subject} | {day} | {SESSION_LABELS.get(session_name, session_name)}",
            )



def plot_group_day_change_by_session(session_df, group_dir):
    """Group-level day change, separated by session."""
    out = group_dir / "day_level_session_change"
    out.mkdir(exist_ok=True)

    if session_df.empty:
        return

    group = (
        session_df
        .groupby(["day", "session_name", "session_label", "session_order"], as_index=False)
        .agg(
            mean_accuracy=("accuracy", "mean"),
            sem_accuracy=("accuracy", sem),
            mean_rt=("rt_mean_sec", "mean"),
            sem_rt=("rt_mean_sec", sem),
            n_subjects=("subject", "nunique"),
        )
        .sort_values(["day", "session_order"])
    )

    if group.empty:
        return

    sessions_present = [s for s in SESSION_ORDER if s in set(group["session_name"])]
    ordered_labels = [SESSION_LABELS[s] for s in sessions_present]

    # Accuracy line plot
    acc_pivot = group.pivot_table(index="day", columns="session_label", values="mean_accuracy", aggfunc="mean")
    acc_pivot = acc_pivot.reindex(columns=[c for c in ordered_labels if c in acc_pivot.columns])

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in acc_pivot.columns:
        ax.plot(acc_pivot.index, acc_pivot[col], marker="o", label=col)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Mean accuracy")
    ax.set_xlabel("Day")
    ax.set_title("Group: day-level accuracy by session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "group_day_change_by_session_accuracy.png", dpi=300)
    plt.close()

    # RT line plot
    rt_pivot = group.pivot_table(index="day", columns="session_label", values="mean_rt", aggfunc="mean")
    rt_pivot = rt_pivot.reindex(columns=[c for c in ordered_labels if c in rt_pivot.columns])

    fig, ax = plt.subplots(figsize=(10, 5))
    for col in rt_pivot.columns:
        ax.plot(rt_pivot.index, rt_pivot[col], marker="o", label=col)
    ax.set_ylabel("Mean RT (s)")
    ax.set_xlabel("Day")
    ax.set_title("Group: day-level RT by session")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()
    plt.savefig(out / "group_day_change_by_session_rt.png", dpi=300)
    plt.close()

    # Accuracy heatmap
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(acc_pivot.columns)), max(3, 0.7 * len(acc_pivot.index))))
    im = ax.imshow(acc_pivot.values, aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(acc_pivot.columns)))
    ax.set_xticklabels(acc_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(acc_pivot.index)))
    ax.set_yticklabels(acc_pivot.index)
    ax.set_title("Group: accuracy heatmap by day and session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")
    for i in range(acc_pivot.shape[0]):
        for j in range(acc_pivot.shape[1]):
            val = acc_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)
    plt.colorbar(im, ax=ax, label="Mean accuracy")
    plt.tight_layout()
    plt.savefig(out / "group_day_change_by_session_accuracy_heatmap.png", dpi=300)
    plt.close()

    # RT heatmap
    fig, ax = plt.subplots(figsize=(max(8, 1.2 * len(rt_pivot.columns)), max(3, 0.7 * len(rt_pivot.index))))
    im = ax.imshow(rt_pivot.values, aspect="auto")
    ax.set_xticks(range(len(rt_pivot.columns)))
    ax.set_xticklabels(rt_pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(rt_pivot.index)))
    ax.set_yticklabels(rt_pivot.index)
    ax.set_title("Group: RT heatmap by day and session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Day")
    for i in range(rt_pivot.shape[0]):
        for j in range(rt_pivot.shape[1]):
            val = rt_pivot.values[i, j]
            txt = "" if pd.isna(val) else f"{val:.2f}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=9)
    plt.colorbar(im, ax=ax, label="Mean RT (s)")
    plt.tight_layout()
    plt.savefig(out / "group_day_change_by_session_rt_heatmap.png", dpi=300)
    plt.close()

def make_group_outputs(df, session_df, day_df, item_df, pair_df, completion_df, syll_session_df, syll_item_df, voice_df, interval_df, top_df):
    group_dir = OUT_DIR / "group_summary"
    group_dir.mkdir(parents=True, exist_ok=True)

    session_df.to_csv(group_dir / "all_subjects_summary_by_session.csv", index=False, encoding="utf-8-sig")
    day_df.to_csv(group_dir / "all_subjects_summary_by_day.csv", index=False, encoding="utf-8-sig")
    item_df.to_csv(group_dir / "all_subjects_item_summary.csv", index=False, encoding="utf-8-sig")
    pair_df.to_csv(group_dir / "all_subjects_pair_confusion_summary.csv", index=False, encoding="utf-8-sig")
    completion_df.to_csv(group_dir / "all_subjects_completion_summary.csv", index=False, encoding="utf-8-sig")
    syll_session_df.to_csv(group_dir / "all_subjects_syllable_session_summary.csv", index=False, encoding="utf-8-sig")
    syll_item_df.to_csv(group_dir / "all_subjects_syllable_item_summary.csv", index=False, encoding="utf-8-sig")
    voice_df.to_csv(group_dir / "all_subjects_voice_engine_summary.csv", index=False, encoding="utf-8-sig")
    interval_df.to_csv(group_dir / "all_subjects_interval_summary.csv", index=False, encoding="utf-8-sig")
    top_df.to_csv(group_dir / "all_subjects_top_candidate_summary.csv", index=False, encoding="utf-8-sig")
    plot_voice_engine_summary(voice_df, group_dir)
    plot_interval_summary(interval_df, group_dir)
    plot_group_syllable_summary(syll_session_df, syll_item_df, group_dir)

    if not session_df.empty:
        group_session = (
            session_df
            .groupby(["session_name", "session_label", "session_order"], as_index=False)
            .agg(
                mean_accuracy=("accuracy", "mean"),
                sem_accuracy=("accuracy", sem),
                mean_rt=("rt_mean_sec", "mean"),
                sem_rt=("rt_mean_sec", sem),
                mean_trials=("n_trials", "mean"),
                sem_trials=("n_trials", sem),
                n_subject_days=("accuracy", "count"),
                n_subjects=("subject", "nunique"),
            )
            .sort_values("session_order")
        )
    else:
        group_session = pd.DataFrame()

    group_session.to_csv(group_dir / "group_session_summary.csv", index=False, encoding="utf-8-sig")

    if not day_df.empty:
        group_day = (
            day_df
            .groupby("day", as_index=False)
            .agg(
                mean_accuracy=("accuracy", "mean"),
                sem_accuracy=("accuracy", sem),
                mean_rt=("rt_mean_sec", "mean"),
                sem_rt=("rt_mean_sec", sem),
                mean_trials=("n_trials", "mean"),
                n_subjects=("subject", "nunique"),
            )
            .sort_values("day")
        )
    else:
        group_day = pd.DataFrame()

    group_day.to_csv(group_dir / "group_day_summary.csv", index=False, encoding="utf-8-sig")

    if not item_df.empty:
        group_item = (
            item_df
            .groupby(["session_name", "target_label"], as_index=False)
            .agg(
                mean_accuracy=("accuracy", "mean"),
                sem_accuracy=("accuracy", sem),
                mean_rt=("rt_mean_sec", "mean"),
                sem_rt=("rt_mean_sec", sem),
                total_trials=("n_trials", "sum"),
                n_subjects=("subject", "nunique"),
            )
        )
    else:
        group_item = pd.DataFrame()

    group_item.to_csv(group_dir / "group_item_summary.csv", index=False, encoding="utf-8-sig")

    if not pair_df.empty:
        group_pair = (
            pair_df
            .groupby(["session_name", "pair"], as_index=False)
            .agg(
                mean_pair_confusion_rate=("pair_confusion_rate", "mean"),
                sem_pair_confusion_rate=("pair_confusion_rate", sem),
                total_pair_confusions=("total_pair_confusions", "sum"),
                total_trials_in_pair=("total_trials_in_pair", "sum"),
                n_subjects=("subject", "nunique"),
            )
        )
    else:
        group_pair = pd.DataFrame()

    group_pair.to_csv(group_dir / "group_pair_confusion_summary.csv", index=False, encoding="utf-8-sig")

    # Group session plot
    if not group_session.empty:
        fig, axes = plt.subplots(1, 3, figsize=(15, 4))
        x = np.arange(len(group_session))
        labels = group_session["session_label"].tolist()

        axes[0].bar(x, group_session["mean_accuracy"], yerr=group_session["sem_accuracy"], capsize=3)
        axes[0].set_ylim(0, 1.05)
        axes[0].set_title("Group accuracy")
        axes[0].set_ylabel("Accuracy")

        axes[1].bar(x, group_session["mean_rt"], yerr=group_session["sem_rt"], capsize=3)
        axes[1].set_title("Group RT")
        axes[1].set_ylabel("RT (s)")

        axes[2].bar(x, group_session["mean_trials"], yerr=group_session["sem_trials"], capsize=3)
        axes[2].set_title("Trials by session")
        axes[2].set_ylabel("Trials")

        for ax in axes:
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=45, ha="right")

        plt.tight_layout()
        plt.savefig(group_dir / "group_session_summary.png", dpi=300)
        plt.close()


    if not group_session.empty and "mean_rt_from_stimulus" in group_session.columns:
        fig, ax = plt.subplots(figsize=(8, 4))
        x = np.arange(len(group_session))
        labels = group_session["session_label"].tolist()
        ax.bar(x, group_session["mean_rt_from_stimulus"], yerr=group_session["sem_rt_from_stimulus"], capsize=3)
        ax.set_title("Group RT after stimulus")
        ax.set_ylabel("RT after stimulus (s)")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(group_dir / "group_session_summary_rt_after_stimulus.png", dpi=300)
        plt.close()

    # Group day plot
    if not group_day.empty:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))

        axes[0].errorbar(group_day["day"], group_day["mean_accuracy"], yerr=group_day["sem_accuracy"], marker="o", capsize=3)
        axes[0].set_ylim(0, 1.05)
        axes[0].set_title("Group day accuracy")
        axes[0].set_ylabel("Accuracy")
        axes[0].tick_params(axis="x", rotation=45)

        axes[1].errorbar(group_day["day"], group_day["mean_rt"], yerr=group_day["sem_rt"], marker="o", capsize=3)
        axes[1].set_title("Group day RT")
        axes[1].set_ylabel("RT (s)")
        axes[1].tick_params(axis="x", rotation=45)

        plt.tight_layout()
        plt.savefig(group_dir / "group_day_summary.png", dpi=300)
        plt.close()

    # Group item plots by session
    item_plot_dir = group_dir / "item_plots"
    item_plot_dir.mkdir(exist_ok=True)

    if not group_item.empty:
        for session_name, g in group_item.groupby("session_name"):
            fig, axes = plt.subplots(1, 2, figsize=(10, 4))
            fig.suptitle(SESSION_LABELS.get(session_name, session_name))

            axes[0].bar(g["target_label"], g["mean_accuracy"], yerr=g["sem_accuracy"], capsize=3)
            axes[0].set_ylim(0, 1.05)
            axes[0].set_ylabel("Accuracy")
            axes[0].set_title("Group item accuracy")

            axes[1].bar(g["target_label"], g["mean_rt"], yerr=g["sem_rt"], capsize=3)
            axes[1].set_ylabel("RT (s)")
            axes[1].set_title("Group item RT")

            plt.tight_layout()
            plt.savefig(item_plot_dir / f"{safe_name(session_name)}_group_items.png", dpi=300)
            plt.close()

    # Day x session trial-count, completion, and learning-curve visualizations
    plot_group_day_session_trial_counts(session_df, group_dir)
    plot_group_day_session_learning_curves(df, group_dir)
    plot_group_day_change_by_session(session_df, group_dir)
    plot_group_completion_by_day(completion_df, group_dir)

    # Pair confusion plot
    if not group_pair.empty:
        for session_name, g in group_pair.groupby("session_name"):
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(g["pair"], g["mean_pair_confusion_rate"], yerr=g["sem_pair_confusion_rate"], capsize=3)
            ax.set_ylim(0, max(0.1, min(1.0, g["mean_pair_confusion_rate"].max() + 0.1)))
            ax.set_ylabel("Pair confusion rate")
            ax.set_title(f"Group pair confusion: {SESSION_LABELS.get(session_name, session_name)}")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            plt.savefig(group_dir / f"{safe_name(session_name)}_pair_confusion.png", dpi=300)
            plt.close()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_learning_data()
    df = standardize(df)

    df.to_csv(OUT_DIR / "all_trials_cleaned.csv", index=False, encoding="utf-8-sig")

    ss = summary_by_session(df)
    sd = summary_by_day(df)
    si = item_summary(df)
    sp = pair_confusion_summary(df)
    sc = make_completion_summary(df, ss)
    syll_session_df, syll_item_df = make_syllable_summary(df)
    sv = voice_engine_summary(df)
    sint = interval_summary(df)
    stop = top_candidate_summary(df)

    make_subject_outputs(df, ss, sd, si, sp, sc, syll_session_df, syll_item_df, sv, sint, stop)
    make_group_outputs(df, ss, sd, si, sp, sc, syll_session_df, syll_item_df, sv, sint, stop)

    print("Done.")
    print(f"Saved to: {OUT_DIR}")
    print(f"Subject folders: {OUT_DIR / 'results_by_subject'}")
    print(f"Group summary: {OUT_DIR / 'group_summary'}")

    print("\nGroup session summary:")
    group_summary_path = OUT_DIR / "group_summary" / "group_session_summary.csv"
    if group_summary_path.exists():
        print(pd.read_csv(group_summary_path, encoding="utf-8-sig").to_string(index=False))


if __name__ == "__main__":
    main()
