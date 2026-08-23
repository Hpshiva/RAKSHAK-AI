import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.model import Model


VIOLENCE_SCORE_THRESHOLD = 0.195
VIOLENCE_INSTANT_THRESHOLD = 0.235
VIOLENCE_LABELS = {
    "fight on a street", "street violence", "violence in office",
    "fire in office", "fire on a street", "person holding a gun",
    "person holding a knife", "weapon", "armed robbery",
    "physical assault", "explosion",
}

# Below this sample count, a single accuracy number is not trustworthy: the
# confidence interval is wide enough that "78%" and "88%" (let alone "95%+")
# aren't statistically distinguishable. Report the interval, don't just the
# point estimate, whenever n is below this.
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
    config = json.loads((Path(__file__).parent / "labels.json").read_text())
    samples = []
    step = config["sample_seconds"]
    for filename, metadata in config["videos"].items():
        capture = cv2.VideoCapture(str(ROOT / "videos" / filename))
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


def evaluate():
    samples = load_samples()
    classifier = Model()
    for offset in range(0, len(samples), 8):
        batch = samples[offset:offset + 8]
        score_sets = classifier.predict_batch_scores([sample["image"] for sample in batch])
        for sample, scores in zip(batch, score_sets):
            label = max(VIOLENCE_LABELS, key=lambda item: scores[item])
            score = scores[label]
            normal = max(value for key, value in scores.items() if key not in VIOLENCE_LABELS)
            sample.update(label=label, score=score, candidate=score >= VIOLENCE_SCORE_THRESHOLD and score >= normal)

    for video in {sample["video"] for sample in samples}:
        history = []
        for sample in [item for item in samples if item["video"] == video]:
            history.append(sample["candidate"])
            history = history[-3:]
            immediate = sample["label"] in {
                "person holding a gun", "person holding a knife",
            }
            sample["prediction"] = sample["candidate"] and (
                immediate or sample["score"] >= VIOLENCE_INSTANT_THRESHOLD or sum(history) >= 2
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

    result = {
        "samples": len(samples), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": round(accuracy * 100, 1),
        "accuracy_95ci": [round(acc_lo * 100, 1), round(acc_hi * 100, 1)],
        "precision": round(precision * 100, 1),
        "recall_sensitivity": round(recall * 100, 1),
        "specificity": round(specificity * 100, 1),
        "f1": round(f1 * 100, 1),
        "per_video": per_video,
    }
    (Path(__file__).parent / "latest-results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

    if len(samples) < MIN_TRUSTWORTHY_SAMPLES:
        print(
            f"\nWARNING: only {len(samples)} samples. The 95% confidence interval on "
            f"accuracy is {result['accuracy_95ci'][0]}%-{result['accuracy_95ci'][1]}% — "
            "too wide to treat the point estimate as a production accuracy claim, and far "
            "too small to distinguish this from a 95%+ target. Add substantially more "
            "independent normal and incident footage before drawing conclusions or tuning "
            "thresholds (never tune on your final test split)."
        )


if __name__ == "__main__":
    evaluate()
