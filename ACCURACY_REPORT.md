# Rakshak AI — Accuracy Report

## Bottom line

**Current measured accuracy: 78.9%** (45/57 correct — 26 true positives, 19 true negatives, 6
false positives, 6 false negatives), from `evaluation/latest-results.json`, the last real run of
`evaluation/benchmark.py` against the project's own labeled dev videos.

**95%+ is not a credible claim right now, and I did not force the numbers to say otherwise.**
Two independent reasons:

1. **The sample is too small to support that claim either way.** With n=57, the 95% confidence
   interval on 78.9% is **66.7%–87.5%** (computed with a Wilson score interval — see
   `evaluation/benchmark.py`, now built into the tool itself). That range doesn't reach 95% no
   matter how you read it, and it's too wide to even confidently say the model beats 80%. You
   cannot responsibly claim ">95% accuracy" from 57 samples regardless of what the point estimate
   says.
2. **The videos this number came from aren't in this environment**, so I could not re-run the
   benchmark or validate any change against real footage this session. `video1.mp4`–`video5.mp4`
   are correctly excluded from the repo (same policy as uploads/snapshots), so I'm reporting the
   last recorded run rather than a fabricated fresh one.

Given that, "tune thresholds until this specific 57-sample set scores 95%" was the one thing I
deliberately did **not** do — the project's own `evaluation/README.md` already warns against it
("Never tune thresholds on the final test split"), and it would optimize for noise in 57 frames
rather than real-world accuracy, likely making the live system worse (more missed incidents or
more false alarms) while *looking* better on paper.

## What I changed instead

Two changes that are legitimate, well-established accuracy levers and don't require new data,
GPU fine-tuning, or touching the empirically-tuned decision thresholds:

### 1. CLIP prompt ensembling (`ai/model.py`)
Previously every label was scored against a single fixed phrasing (`"a photo of {label}"`). CLIP's
own paper shows that scoring against several phrasings and averaging the (renormalized) text
embeddings measurably improves zero-shot accuracy — often several points — with **zero added
per-frame cost**, since text embeddings are computed once at startup, not per frame. Implemented
via `PROMPT_TEMPLATES` (5 phrasings: `"a photo of {}"`, `"a security camera photo of {}"`, `"CCTV
footage showing {}"`, `"a low quality surveillance image of {}"`, `"a photo of a person during
{}"`) and a new `_vectorize_ensembled_prompts()` method. Verified end-to-end: model loads, text
feature matrix is `[24 labels, 768 dims]`, every row is unit-norm, and `predict_scores()` runs
correctly on a test image.

**Caveat — please read before trusting this in production:** changing the prompts shifts the
similarity-score distribution slightly. The existing thresholds
(`VIOLENCE_SCORE_THRESHOLD=0.195`, `VIOLENCE_INSTANT_THRESHOLD=0.235`,
`WEAPON_GUN_CROP_THRESHOLD=0.18`, `WEAPON_KNIFE_CROP_THRESHOLD=0.17` in `ai/detector.py`) were
tuned against the *old* single-template prompts. They will still work reasonably (the shift is
usually small), but **run `evaluation/benchmark.py` again once you have the video files locally,
before relying on this**, and re-tune the thresholds on a validation split if the numbers move.

### 2. Evaluation harness now reports honest statistics (`evaluation/benchmark.py`)
Previously it printed one blended accuracy number, which is exactly what made "just hit 95%" look
plausible at a glance. It now also reports:
- **95% confidence interval on accuracy** (Wilson score interval, no scipy dependency needed).
- **Sensitivity vs. specificity split out separately** (`recall_sensitivity`: real incidents
  caught; `specificity`: normal footage correctly left alone) — for a security system these matter
  differently (a missed incident vs. a false alarm are not the same cost), and a single accuracy
  number hides that trade-off.
- **Per-video accuracy breakdown**, so a failure concentrated in one clip (bad lighting, unusual
  angle) is visible instead of averaged away.
- **An explicit warning printed to the console** whenever the sample count is below 200,
  restating the confidence interval and refusing to let the point estimate pass as a production
  claim silently.

This doesn't change the model's accuracy — it changes whether you can trust what the tool tells
you about it, which has to come first.

## Why 95%+ isn't realistic yet, architecturally

The violence classifier is **zero-shot CLIP (ViT-L-14)** — it has never been trained or
fine-tuned on this project's actual footage. It's scoring "how similar does this image look to
this text prompt," not a model trained to distinguish this school's specific cameras, lighting,
and uniforms from real incidents. Zero-shot CLIP-family models on real-world violence/anomaly
benchmarks in published research typically land in the 70–90% range, not 95%+ — that ceiling
usually requires supervised fine-tuning on a labeled dataset from the target domain.

## Prioritized roadmap to a genuinely validated higher number

Ranked by leverage vs. effort. None of these were things I could execute this session (no GPU
available beyond CPU-only torch, no labeled dataset present, no video files) — they're the real
path, not a wishlist.

1. **Grow and rebalance the evaluation set — highest priority, blocks everything else.**
   57 samples from 5 videos cannot support any confidence claim. Target: hundreds of samples per
   class, drawn from footage genuinely representative of deployment cameras — including
   *hard negatives* (crowds, sports, hugging, falling, using tools, waving) that look
   superficially similar to violence but aren't. Split into calibration / validation / held-out
   test, and never touch the test split until the very end (per the project's own README).

2. **Threshold calibration on the validation split, once the above exists.** Sweep
   `VIOLENCE_SCORE_THRESHOLD` / `VIOLENCE_INSTANT_THRESHOLD` and the multi-frame confirmation
   window (`violence_history` size, currently 3, requiring 2 hits) against a precision-recall
   curve on validation data, then confirm once on test. This is the "safe" version of what
   forcing the number to 95% today would have skipped.

3. **Train a dedicated weapon detector.** `train.py` and `dataset.yaml` already scaffold a
   YOLO gun/knife detector, but `datasets/weapons/` doesn't exist yet — the app currently relies
   entirely on CLIP zero-shot crop scoring for weapons (`WEAPON_GUN_CROP_THRESHOLD` /
   `WEAPON_KNIFE_CROP_THRESHOLD` in `ai/detector.py`). A purpose-trained detector reliably
   outperforms zero-shot prompting for concrete objects like guns/knives and is likely the single
   highest-leverage improvement available, once labeled weapon images/boxes are collected.

4. **Fine-tune a lightweight linear probe on frozen CLIP features**, if a labeled violence
   image/clip dataset can be assembled (even a few thousand images). Cheap to train (no GPU
   fine-tuning of CLIP itself needed, just a linear layer on top of frozen embeddings), and
   typically closes much of the gap between zero-shot and fully fine-tuned accuracy.

5. **Active learning loop.** Log borderline-confidence detections (e.g. score within ±0.03 of
   the threshold) for human review, and feed confirmed labels back into the evaluation/training
   set. Turns real deployment into a continuously growing, genuinely representative dataset
   instead of a static 5-video benchmark.

## How to validate this yourself

```bash
# once video1.mp4..video5.mp4 exist locally under videos/
python evaluation/benchmark.py
```

Compare the new `accuracy_95ci`, `recall_sensitivity`/`specificity` split, and `per_video`
breakdown against `evaluation/latest-results.json`'s prior run. If accuracy drops or the
confidence interval widens unexpectedly after the prompt-ensembling change, revert
`PROMPT_TEMPLATES` in `ai/model.py` to a single `"a photo of {}"` entry and re-run before trusting
it further.
