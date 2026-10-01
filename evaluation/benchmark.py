import json
import sys
import os
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.model import Model
from ai.linear_probe import ProbeClassifier


VIOLENCE_SCORE_THRESHOLD = 0.195
VIOLENCE_INSTANT_THRESHOLD = 0.235
VIOLENCE_LABELS = {
    "fight on a street", "street violence", "violence in office",
    "fire in office", "fire on a street", "person holding a gun",
    "person holding a knife", "weapon", "armed robbery",
    "physical assault", "explosion", "violence"
}

MIN_TRUSTWORTHY_SAMPLES = 200


def wilson_confidence_interval(successes, total, z=1.96):
    """95% Wilson score interval for a proportion. No scipy dependency."""
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half_width = (z / denom) * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    return max(0.0, center - half_width), min(1.0, center + half_width)


def load_samples():
    labels_file = Path(__file__).parent / "labels.json"
    if not labels_file.exists():
        print("labels.json not found.")
        return []
    config = json.loads(labels_file.read_text())
    samples = []
    step = config.get("sample_seconds", 3)
    for filename, metadata in config["videos"].items():
        video_path = ROOT / "videos" / filename
        if not video_path.exists():
            continue
        capture = cv2.VideoCapture(str(video_path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 25
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        timestamp = 0
        while timestamp <= duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            success, frame = capture.read()
            if success:
                positive = any(start <= timestamp <= end for start, end in metadata["incident_ranges"])
                samples.append({
                    "video": filename,
                    "time": timestamp,
                    "ground_truth": positive,
                    "image": cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                })
            timestamp += step
        capture.release()
    return samples


def sweep_optimal_threshold(samples, score_sets):
    """Find the threshold that maximizes F1 score across the sample set."""
    best_thresh = VIOLENCE_SCORE_THRESHOLD
    best_f1 = -1.0
    best_metrics = {}

    for thresh in np.arange(0.10, 0.40, 0.005):
        preds = []
        for sample, scores in zip(samples, score_sets):
            label = max(VIOLENCE_LABELS, key=lambda item: scores.get(item, -1.0))
            score = scores.get(label, 0.0)
            normal = max(
                (value for key, value in scores.items() if key not in VIOLENCE_LABELS),
                default=0.0
            )
            candidate = score >= thresh and score >= normal
            preds.append(candidate)

        tp = sum(p and s["ground_truth"] for p, s in zip(preds, samples))
        tn = sum(not p and not s["ground_truth"] for p, s in zip(preds, samples))
        fp = sum(p and not s["ground_truth"] for p, s in zip(preds, samples))
        fn = sum(not p and s["ground_truth"] for p, s in zip(preds, samples))

        prec = tp / max(tp + fp, 1)
        rec = tp / max(tp + fn, 1)
        f1 = 2 * prec * rec / max(prec + rec, 1e-9)

        if f1 > best_f1:
            best_f1 = f1
            best_thresh = round(float(thresh), 3)
            best_metrics = {
                "threshold": best_thresh,
                "f1": round(f1 * 100, 1),
                "precision": round(prec * 100, 1),
                "recall": round(rec * 100, 1),
                "accuracy": round(100 * (tp + tn) / max(len(samples), 1), 1)
            }

    return best_thresh, best_metrics


def evaluate():
    samples = load_samples()
    if not samples:
        print("No evaluation videos found locally under 'videos/'.")
        print("To run the benchmark, please add video1.mp4..video5.mp4 into the videos/ directory.")
        return

    classifier = Model()
    all_scores = []
    for offset in range(0, len(samples), 8):
        batch = samples[offset:offset + 8]
        score_sets = classifier.predict_batch_scores([sample["image"] for sample in batch])
        all_scores.extend(score_sets)
        for sample, scores in zip(batch, score_sets):
            label = max(VIOLENCE_LABELS, key=lambda item: scores.get(item, -1.0))
            score = scores.get(label, 0.0)
            normal = max(
                (value for key, value in scores.items() if key not in VIOLENCE_LABELS),
                default=0.0
            )
            sample.update(
                label=label,
                score=score,
                candidate=score >= VIOLENCE_SCORE_THRESHOLD and score >= normal
            )

    # Temporal confirmation with EWMA simulation
    for video in {sample["video"] for sample in samples}:
        video_samples = [item for item in samples if item["video"] == video]
        ewma = 0.0
        alpha = 0.45
        for sample in video_samples:
            instant = sample["score"] if sample["candidate"] else 0.0
            ewma = (1 - alpha) * ewma + alpha * instant
            immediate = sample["label"] in {
                "person holding a gun", "person holding a knife"
            }
            sample["prediction"] = (
                immediate or
                sample["score"] >= VIOLENCE_INSTANT_THRESHOLD or
                (sample["candidate"] and ewma >= (VIOLENCE_SCORE_THRESHOLD * 0.90))
            )

    tp = sum(x["prediction"] and x["ground_truth"] for x in samples)
    tn = sum(not x["prediction"] and not x["ground_truth"] for x in samples)
    fp = sum(x["prediction"] and not x["ground_truth"] for x in samples)
    fn = sum(not x["prediction"] and x["ground_truth"] for x in samples)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)          # sensitivity: real incidents caught
    specificity = tn / max(tn + fp, 1)     # normal footage correctly left alone
    accuracy = (tp + tn) / len(samples)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    acc_lo, acc_hi = wilson_confidence_interval(tp + tn, len(samples))

    per_video = {}
    for video in sorted({sample["video"] for sample in samples}):
        video_samples = [s for s in samples if s["video"] == video]
        correct = sum(s["prediction"] == s["ground_truth"] for s in video_samples)
        per_video[video] = {
            "samples": len(video_samples),
            "correct": correct,
            "accuracy": round(100 * correct / len(video_samples), 1),
        }

    best_thresh, best_metrics = sweep_optimal_threshold(samples, all_scores)

    result = {
        "samples": len(samples), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": round(accuracy * 100, 1),
        "accuracy_95ci": [round(acc_lo * 100, 1), round(acc_hi * 100, 1)],
        "precision": round(precision * 100, 1),
        "recall_sensitivity": round(recall * 100, 1),
        "specificity": round(specificity * 100, 1),
        "f1": round(f1 * 100, 1),
        "optimal_threshold_sweep": best_metrics,
        "per_video": per_video,
    }
    (Path(__file__).parent / "latest-results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

    if len(samples) < MIN_TRUSTWORTHY_SAMPLES:
        print(
            f"\nWARNING: only {len(samples)} samples. The 95% confidence interval on "
            f"accuracy is {result['accuracy_95ci'][0]}%-{result['accuracy_95ci'][1]}%."
        )


if __name__ == "__main__":
    evaluate()
