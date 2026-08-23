# Rakshak AI — Bug Audit & Fix Report

Full-codebase review of `app.py`, `database.py`, `report_generator.py`, `train.py`, `wsgi.py`,
`ai/detector.py`, `ai/face_recognition.py`, `ai/model.py`, `evaluation/benchmark.py`, and every
template's inline JavaScript. Findings are grouped by area; each entry lists the problem, its
real-world impact, and exactly how it was fixed. Two items required a product decision rather
than a mechanical fix — those were confirmed with the maintainer before changing behavior.

Verification performed after fixing: every edited `.py` file compiles (`py_compile`), and every
template still renders through Jinja with no template errors.

---

## Security

### 1. Hardcoded backdoor login credential
**File:** `app.py`
**Problem:** `LOGIN_ACCOUNTS` unconditionally included `"test@gmail.com": "123"` — a trivial,
permanent authentication bypass baked into the source, active in every environment including a
real deployment.
**Fix:** The account is now only added when `RAKSHAK_ALLOW_TEST_LOGIN=1` is explicitly set (off
by default). Documented in `.env.example`.

### 2. No brute-force protection on OTP verification
**File:** `app.py` (`/verify_otp`)
**Problem:** A 6-digit OTP has 1,000,000 possible values, and there was no limit on how many
guesses `/verify_otp` would accept — an attacker who knew the admin email could script unlimited
guesses against a single OTP.
**Fix:** Added a 5-attempt cap (`OTP_MAX_ATTEMPTS`) tracked per-session. After 5 wrong guesses the
OTP is invalidated and the user is sent back to request a new one. Also switched the OTP
comparison to `hmac.compare_digest` (timing-safe), matching how the login password is already
compared.

### 3. Session hard-expired instead of sliding-window
**File:** `app.py` (`enforce_session_timeout`)
**Problem:** `session["login_time"]` was set once at login and never refreshed, so every session
expired exactly 5 minutes after login *regardless of activity*. Meanwhile, each page's client-side
JS independently restarts its own 5-minute auto-logout timer on every navigation — the two clocks
drifted, so a user actively working (e.g. watching the live dashboard, browsing analytics) could
be silently rejected by the server mid-task before the client even expected a timeout.
**Fix:** `enforce_session_timeout` now refreshes `login_time` on every authenticated request,
making the timeout a genuine 5-minutes-of-inactivity sliding window that matches the per-page
client-side timers.

### 4. `/faces_img/<filename>` didn't sanitize the filename
**File:** `app.py`
**Problem:** Unlike the sibling `/threat_screenshot/<filename>` route, this one passed the raw
path parameter straight to `send_from_directory` without `secure_filename()`. Not exploitable
today (Werkzeug's `safe_join` already blocks path traversal), but inconsistent and fragile.
**Fix:** Added `secure_filename(filename)`, matching the other file-serving routes.

### 5. Unescaped user-influenced data rendered via `innerHTML`
**Files:** `templates/faces.html`, `templates/dashboard.html`, `templates/video_analysis.html`
**Problem:** Face name/role/filename (faces.html) and detection labels (dashboard/video_analysis)
were interpolated directly into template-literal HTML — and in faces.html, also into inline
`onclick="...('${...}')"` JS-string attributes — with no escaping. Not currently exploitable
because `secure_filename()` sanitizes the underlying data before it's ever stored, but it's a
fragile, single-point-of-failure defense, and `analytics.html` already had its own `escapeHtml`
helper that these pages were missing.
**Fix:** Added the same `escapeHtml` helper to `faces.html`, `dashboard.html`, and
`video_analysis.html`, and used it everywhere user-influenced text is rendered. In `faces.html`,
also replaced the inline `onclick="..."` handlers with `data-*` attributes plus a single delegated
click listener, which removes the JS-string-escaping hazard entirely (mirrors the pattern
`analytics.html` already used for its delete buttons).

---

## Data integrity

### 6. Incident PDF could attach the wrong screenshot
**File:** `database.py` (`get_incident_report_data`)
**Problem:** The query that finds a snapshot for a CRITICAL incident picked whichever saved
screenshot was *closest in time* on that camera, with no cap on how far apart they could be. If no
snapshot from the actual incident existed, it would still silently attach a screenshot from a
completely unrelated, much earlier or later incident on the same camera — misattributing evidence
in a generated incident report.
**Fix:** Added a 120-second bound (`ABS(... ) <= 120`) to the query, so an unrelated snapshot is
now correctly treated as "no snapshot found" instead of being attached.

### 7. Face name/role filename encoding could collide with its own delimiter
**File:** `app.py` (`/api/upload_face`, `/api/edit_face`)
**Problem:** Name and role are encoded into the stored filename as `Name__Role__original.jpg`,
and parsed back with `filename.split('__')`. `secure_filename()` replaces each disallowed
character with `_` individually — so a name containing two adjacent special characters (e.g. two
apostrophes) could sanitize into a literal `__`, colliding with the delimiter and corrupting the
name/role split.
**Fix:** Added `_sanitize_face_component()`, which sanitizes the name/role and then collapses any
repeated underscores before they're joined into the filename, so the delimiter can no longer
appear inside either component.

---

## Correctness / logic

### 8. Recent-alerts sidebar always said "Violence Detected"
**Files:** `templates/dashboard.html`, `templates/video_analysis.html`
**Problem:** The log entry title was a hardcoded string, `Violence Detected`, regardless of what
was actually logged — including routine LOW-threat person sightings that are not violence at all,
and CRITICAL events where the specific label (e.g. "Person Holding A Gun Detected") was silently
discarded. The backend already sends the correct formatted label (`item.label`) and the camera
name (`item.camera`); the frontend just wasn't using them.
**Fix:** The log title now renders the real `item.label`, and the meta row now also shows which
camera the event came from — important context on a multi-camera system that was previously
missing entirely.

### 9. HIGH ("Elevated") threat tier was completely unreachable
**File:** `ai/detector.py` (`get_threat_level`)
**Problem:** The function's signature (`get_threat_level(count, is_violent)`) implies threat scales
with person count, but the body ignored `count` entirely and only ever returned `CRITICAL` or
`LOW`. This silently broke a tier the rest of the system was already built for: the orange
"Elevated" dashboard state, the audible-beep trigger condition (`threat === 'HIGH'`), the
robot-dispatch check (`"HIGH"` is already in its allow-list), and the `.threat-HIGH` /
`.threat-pill-warning` CSS — all dead code with nothing ever able to reach it.
**Decision:** Confirmed with the maintainer before changing live alerting behavior. Restored the
HIGH tier using a crowd-size heuristic: a non-violent scene is now flagged HIGH once person count
reaches `RAKSHAK_HIGH_THREAT_PERSON_COUNT` (default `6`, tunable via `.env` since the right number
depends on the camera/site). This lights up the previously dead UI/alerting paths as originally
intended.

### 10. Two people detected in the same frame could share one tracking ID
**File:** `ai/detector.py` (`_stabilize_person_box`)
**Problem:** Each detected person's box is matched to the nearest existing track by IoU to smooth
jitter. The matching didn't exclude tracks already claimed earlier in the *same* frame, so if two
people were both closest to the same track, the second person's box silently overwrote the first
person's smoothing state — causing box jitter/identity bleed between two distinct people in
crowded scenes.
**Fix:** Added a `claimed_track_ids` set, built fresh per frame in `ai_worker()` and threaded
through `_stabilize_person_box`, so a track ID can only be claimed by one person per frame.

### 11. Dead video-player code shipped on the dashboard page
**File:** `templates/dashboard.html`
**Problem:** `controlVideo()`, `closeVideo()`, and the progress-bar wiring were copy-pasted from
`video_analysis.html`, but `dashboard.html` has no uploaded-video player UI at all — these
functions referenced DOM elements (`play-btn`, `video-progress`, `uploaded-dot`, ...) that don't
exist anywhere on the page. Harmless (the progress-bar block is `if (progressSlider)`-guarded) but
pure dead weight and confusing to read.
**Fix:** Removed the dead block from `dashboard.html`. Confirmed via grep that no remaining code
on the page references those functions or element IDs.

### 12. Leftover old-palette colors after the UI redesign
**Files:** `templates/dashboard.html`, `templates/video_analysis.html`
**Problem:** Two spots were missed during the cream/coral redesign and still used the previous
Apple-glass palette: dashboard's camera-offline SVG placeholder (`black`/`white`/`#9ca3af`), and
video_analysis's `body.critical-alert` pulse animation (`rgba(239, 68, 68, ...)`).
**Fix:** Aligned both to the current theme (`#181715`/`#faf9f5`/`#a09d96` and
`rgba(198, 69, 69, ...)` respectively), matching the already-correct versions elsewhere in the app.

---

## Known limitations (documented, not changed)

These are real but weren't changed, either because I can't supply what's missing, or because
fixing them properly is a larger architectural change than a bug-fix pass should make silently.

### Missing audio asset — the audible CRITICAL alert has never worked
**Files:** `templates/dashboard.html`, `templates/video_analysis.html`
`new Audio('/static/assets/threat-buzzer.mp4')` points at a file that doesn't exist —
`static/assets/` only contains `kv-map.png`. The failure is caught (`.catch(...)`), so it doesn't
crash anything, but it means the audible siren for CRITICAL events has silently never played.
**Not auto-fixable:** I have no way to synthesize or source an actual audio asset in this session.
**To fix:** add a real audio file at `static/assets/threat-buzzer.mp3` (or `.wav`) and update the
`Audio(...)` path in both templates — `.mp4` is a video container and unreliable as an audio-only
source across browsers even if a file existed there.

### `CameraState` is mutated from multiple threads with no locking
**File:** `ai/detector.py`
`CameraState` fields (`tracks`, `last_violence_label`, `cached_boxes`, `screenshot_count_this_event`,
...) are read and written from three concurrent contexts: the `ai_worker` thread, the
`violence_worker` thread, and however many Flask generator threads are streaming camera feeds —
with no lock around any of it. Python's GIL keeps individual attribute assignments from
corrupting, but compound read-modify-write sequences (e.g. the tracks-dict rebuild, or the
check-then-set in `_trigger_threat_actions`) aren't atomic and can theoretically race under load.
**Why not fixed here:** proper fixes (per-camera locks or a single-writer queue) touch the hot
path of every frame and need real load testing to validate; not something to change silently in a
bug-fix pass.

### Shared global video-playback state across all browser sessions
**File:** `app.py`
`uploaded_video_path`, `video_playing`, `video_seek_request`, etc. are module-level globals, so if
two admins have the video analysis page open in two tabs/browsers at once, one admin's
play/pause/seek actions affect the other's view. Acceptable for a single-operator deployment;
would need per-session state to support concurrent operators.

### `Name__Role__photo` filename encoding is inherently fragile
**File:** `app.py`, `ai/face_recognition.py`
Bug #7 closed the specific delimiter-collision hole, but encoding structured data into a filename
via a string delimiter is still more fragile than a proper sidecar (e.g. a small JSON/SQLite
mapping of filename → name/role). Not changed here since it's a data-model change, not a bug fix,
but worth considering if face management grows more complex.

---

## Files changed

| File | Reason |
|---|---|
| `app.py` | Session sliding window, OTP lockout, test-login gating, filename hardening, `re` import |
| `database.py` | Snapshot time-window bound |
| `ai/detector.py` | HIGH threat tier restored, per-frame track-ID collision fix |
| `templates/dashboard.html` | Real alert label + camera, dead-code removal, leftover-color fix, `escapeHtml` |
| `templates/video_analysis.html` | Real alert label + camera, leftover-color fix, `escapeHtml` |
| `templates/faces.html` | `escapeHtml`, delegated click handlers instead of inline `onclick` |
| `.env.example` | Documented `RAKSHAK_ALLOW_TEST_LOGIN` and `RAKSHAK_HIGH_THREAT_PERSON_COUNT` |
