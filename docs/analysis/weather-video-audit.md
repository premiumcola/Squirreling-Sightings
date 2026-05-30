# Weather / Timelapse Video Health Audit

**Date:** 2026-05-30 · **Scope:** `storage/weather/<cam>/<phase>/*.mp4` (sun-timelapse
+ event-timelapse + heavy_rain) · **Mode:** READ-ONLY investigation — nothing was
deleted, repaired, or written to `settings.json`. Analysis ran inside the
container (ffmpeg + OpenCV + the existing `app.frame_helpers` validators);
the throwaway probe scripts were piped via stdin and never committed.

> ⚠️ This is a findings report only. Every "Fix" below is a **proposal**, not an
> applied change. Review before acting.

---

## TL;DR — headline numbers

| Metric | Value |
|---|---|
| `*.json` files under `storage/weather` | **82** |
| → real sighting manifests | **37** |
| → `*.mp4.qa.json` QA sidecars (mis-counted as sightings) | **22** |
| → `*_skip.json` skip markers (mis-counted as sightings) | **23** |
| `/api/weather/sightings` reported `total` | **82** ← inflated, should be ~37 |
| `.mp4` files on disk | **36** |
| → decode OK | **22** (61 %) |
| → 258-byte truncated stubs (won't open) | **10** (28 %) |
| → open but **no decodable frames** (corrupt H264) | **4** (11 %) |
| Real manifests with **no clip at all** | **1** |
| Today's (2026-05-30) clips on disk | 1 — a 258-byte stub (**not playable**) |
| Frozen / near-static clips | 7 · Black clips: 0 · Short-vs-target: 3 |

**Two independent problems dominate:**
1. **`list_sightings` globs every `*.json`**, so 45 non-manifest sidecars
   (QA + skip) are counted as "sightings" → wrong totals + latent ghost cards.
2. **~39 % of clips are corrupt** (truncated stub or undecodable H264). The QA
   sidecars prove most of them were *once* valid → corruption happens **after**
   a successful encode (non-atomic write / truncating re-encode).

---

## 1 · Storage structure vs. expectations

Actual on-disk layout (3 configured cameras):

| Camera | Phase dir | mp4 | real manifest | jpg | qa.json | skip.json |
|---|---|---:|---:|---:|---:|---:|
| Gartendachterrasse | `sunrise_timelapse` | 5 | 5 | 5 | 4 | 3 |
| Gartendachterrasse | `sunset_timelapse` | 4 | 4 | 4 | ~ | ~ |
| Squirreltownnutbar | `sunrise_timelapse` | 13 | 13 | 14 | ~ | ~ |
| Squirreltownnutbar | `sunset_timelapse` | 11 | 11 | 11 | ~ | ~ |
| Squirreltownnutbar | `heavy_rain` | 3 | 3 | 3 | 0 | 0 |
| **Werkstatt** | *(none)* | 0 | 0 | 0 | 0 | 0 |

(`~` = remaining qa/skip files spread across the sun phases; totals: 22 qa + 23 skip.)

**Mismatches found:**

- **M1 — JSON glob pollution (critical).** `list_sightings` in
  `weather_service/_manifests.py` walks `evt_dir.glob("*.json")` and treats every
  hit as a sighting. That sweeps in the QA sidecars (`<clip>.mp4.qa.json`, written
  by `timelapse_qa.py`) and the skip markers (`<stem>_skip.json`, written by
  `_write_sun_skip_json` in `_sun_tl/__init__.py`). Result: `total = 82` when only
  **37** real manifests exist. These junk records have no `event_type`/`cam_id`, so
  they inflate the subtitle count and `counts`, and would render as broken cards if
  the user turns all filter pills off (see §4).
- **M2 — `heavy_rain` is outside the rescan phase set.** The rescan / thumb-regen
  endpoints in `routes/weather.py` only walk `_WEATHER_PHASE_DIRS =
  (sunrise_timelapse, sunset_timelapse, sun_timelapse, event_timelapse)`. The
  `heavy_rain` event dir (a valid raw-clip event) is **not** in that tuple, so
  orphan-mp4 synthesis and thumb regeneration never run for it. (`list_sightings`
  *does* list it, because it walks all `evt_dir`s — so the two code paths disagree
  on which dirs are "weather".) Harmless today (heavy_rain is balanced 3/3/3) but a
  latent inconsistency.
- **M3 — 1 orphan thumb.** Squirreltownnutbar `sunrise_timelapse` has 14 `.jpg`
  but 13 `.mp4` — a leftover thumbnail whose clip is gone (skip/truncation
  residue).
- **M4 — 1 clipless real manifest.** 37 real manifests vs 36 clips → one sighting
  JSON points at a clip that no longer exists on disk.
- **No legacy-layout drift.** No shared `sun_timelapse/` or `event_timelapse/`
  dirs remain — the per-phase migration ran cleanly. No `*.tracks.json` sidecars
  in the weather tree.

---

## 2 · Playability (ffprobe / OpenCV per clip)

Of the 36 clips, **14 (39 %) are unplayable**, in two distinct failure classes:

### Class A — 258-byte truncated stubs (10 clips)
A 258-byte `.mp4` is just an `ftyp` + empty `moov` header — zero media. OpenCV
cannot open them; a browser `<video>` gets a 200 response but nothing to play.

Representative files (all confirmed 258 bytes):
- `Squirreltownnutbar/sunrise_timelapse/2026-05-30_sunrise_…mp4` ← **today**
- `Squirreltownnutbar/sunset_timelapse/2026-05-28_sunset_…mp4`
- `Gartendachterrasse/sunrise_timelapse/2026-05-15_sunrise_…mp4`
- `Gartendachterrasse/sunset_timelapse/2026-05-13_sunset_…mp4`

**9 of these 10 have a `.mp4.qa.json` sidecar** reporting a real frame count
(78 – 670 frames). The QA sidecar is written *only after a successful encode*, so
these were **complete, valid clips that were later truncated to a header stub.**

### Class B — opens but no decodable frames (4 clips)
OpenCV opens the container and reads a valid `moov` (correct fps / 1920×1080 /
frame count), but **frame 0 fails to decode**. stderr floods with
`h264 … Invalid NAL unit size (… > …)` / `Error splitting the input into NAL
units` — genuine bitstream corruption (garbage NAL lengths), not a codec-support
gap. A browser would also fail or show a frozen/garbled frame.

| File | Size | moov frames | decodes? | qa sidecar |
|---|---:|---:|---|---|
| `Squirreltownnutbar/…/2026-05-29_sunset_…mp4` ← **2nd-newest** | 10.2 MB | 164 | ✗ | yes (164) |
| `Squirreltownnutbar/…/2026-05-15_sunrise_…mp4` | 14.3 MB | 183 | ✗ | yes (183) |
| `Squirreltownnutbar/…/2026-05-16_sunrise_…mp4` | 7.4 MB | 116 | ✗ | yes (116) |
| `Squirreltownnutbar/…/2026-05-07_sunset_…mp4` | 16.5 MB | 776 | ✗ | no |

### Why the *newest* sightings won't play (direct answer)
- **Today, 2026-05-30 sunrise** (Squirreltownnutbar) → the only clip dated today
  is a **258-byte stub** (Class A). The file exists and is >0, so the `/clip`
  endpoint resolves and returns HTTP 200 — but the encode never produced media.
- **2026-05-29 sunset** (2nd-newest) → **Class B** corrupt H264 (10.2 MB, opens,
  zero decodable frames).
- In both cases the **thumbnail is a valid JPEG** (898 KB – 3.3 MB, decodes fine),
  because the thumb is a mid-window frame captured *before* the broken encode. So
  the card looks normal; only playback fails. `/clip` does **not** validate the
  container — it serves whatever bytes exist.

### Manifest duration disagreements (8 clips)
`duration_s` in the manifest is computed at capture time as
`len(images)//fps` (intended frames), independent of encode success, so it
overstates badly when the encode dropped frames or truncated:

| File | manifest `duration_s` | actual (frames/fps) |
|---|---:|---:|
| `Squirreltownnutbar/…/2026-05-11_sunrise_…` | 26 s | **0.32 s** |
| `Gartendachterrasse/…/2026-05-14_sunset_…` | 45 s | 7.4 s |
| `Gartendachterrasse/…/2026-05-12_sunrise_…` | 32 s | 12.0 s |

(+ 5 more, incl. the `_test_*` diagnostic captures whose manifests intentionally
carry tiny target durations.)

---

## 3 · Content sanity (sampled 8 frames/clip · reused `frame_helpers`)

Used `is_grey_frame`, `perceptual_hash` + `hamming_distance` from
`app.frame_helpers` (the production validator stack) on the 22 decodable clips:

- **Black / near-black: 0.** No clip is all-black. → The "black card" the user
  sees is **not** caused by black video content (see §4).
- **Frozen / near-static: 7.** pHash is invariant (or near-invariant) across all
  8 samples. Includes the 3 `heavy_rain` raw clips (`2026-05-05_122701/183659/
  183846.mp4`, hamming distance 0 — a single repeated frame end-to-end) and
  several sunset clips. Signature of a **stuck RTSP frame** repeated through the
  whole capture window.
- **Short vs. target: 3.** Actual duration < 50 % of the manifest target, e.g.
  `2026-05-11_sunrise_squirreltownnutbar` = 0.32 s of an intended 26 s. Effectively
  empty clips that still got a manifest.

---

## 4 · UI placeholder states → data cause

The user reports two broken-card looks. Mapping each to the exact code branch in
`_weatherSightingCardHTML` (`web/static/js/weather/sightings.js`):

| UI appearance | Code branch | Data condition that triggers it |
|---|---|---|
| **Hatched / struck-through** (135° striped thumb, dimmed 0.65) — `.ws-card--orphan` + `.ws-card-thumb--orphan` | `camActive === false` → striped `<div>`, no `<img>` requested | `s.cam_id ∉ state.cameras`. Two sources: **(a)** sighting from a **removed / renamed** camera (cam-slug drift); **(b)** a **ghost sidecar record** (`*.qa.json` / `*_skip.json`) mis-listed by `list_sightings` — it has no `cam_id`, so `camActive` is false. |
| **Fully black** (play button on black, no image) | `camActive === true` → `<img … onerror="this.style.opacity=0.2">` over the `#0a0e14` `.ws-card-thumb-wrap` background | Active camera, but the **thumb `<img>` fails to load** → the `/thumb` endpoint 404s, which happens only when the `.jpg` is missing **and** the clip is too corrupt to regenerate one. Also hit by ghost records that *do* reach the active branch via a stray `cam_id` (their `/sightings/undefined/thumb` 404s). |
| **Normal card that won't play** (valid thumb + play button, dead player on open) | Card renders fully; failure is in the lightbox `<video>` | **Corrupt clip with a valid thumb** — the 258-byte stubs (Class A) and no-frame H264 clips (Class B). This is the **dominant real-world symptom** and what "newest not playable" actually is. |

Key nuance: in the *current* dataset all clips happen to have valid `.jpg`
thumbs and all live under active cameras, so the pure "black card" and "hatched"
states are mostly **latent**; the user is overwhelmingly seeing the **third**
case — a healthy-looking card whose video is broken. The hatched/black states
surface as soon as (a) a camera is renamed, or (b) the filter pills are all
toggled off (which reveals the 45 ghost sidecar records).

---

## 5 · Root causes + recommended fixes (proposals only)

| # | Finding | Hypothesised root cause | Suggested fix (not applied) |
|---|---|---|---|
| **F1** | `total`=82 vs 37 real; ghost cards possible | `list_sightings` `glob("*.json")` ingests `*.mp4.qa.json` + `*_skip.json` (+ would ingest `*.tracks.json`) | In `_manifests.py`, filter the glob: skip names ending `.qa.json` / `_skip.json` / `.tracks.json`, **and** require a manifest shape (`event_type` **and** `clip_path`/`id` present) before appending. Belt-and-braces both. |
| **F2** | 10× 258-byte stubs + 4× undecodable H264, mostly with QA sidecars (= once valid) | mp4 write / re-encode is **not atomic** — a truncating re-open or interrupted ffmpeg leaves a header-only stub or a half-written mdat while the old `.qa.json` survives | Encode to a temp file, **probe it** (frame count > 0, first frame decodes), then `os.replace` into place. Never overwrite a good clip in place. On probe failure, keep the prior good file (or route to skip) instead of leaving a stub. |
| **F3** | Manifest written even when clip is empty/short → duration mismatch + clipless manifest | Manifest `duration_s = len(images)//fps` and the JSON are written **independent of** encode success | Write the sighting manifest **after** the encode is validated; source `duration_s` from the probed clip, not the intended frame count. Extend the existing skip-gate so a *failed encode* also writes `_skip.json` (and no manifest), exactly like a low-frame capture. |
| **F4** | `/clip` serves stubs; `/thumb` regen can't recover | `api_weather_sighting_clip` only checks `exists()`, not validity | Add a cheap guard in `/clip` (size threshold or a one-frame probe). Return a typed status (e.g. 422 + `{"corrupt": true}`) so the UI can show a real "Aufnahme beschädigt" state instead of a dead `<video>`. |
| **F5** | UI can't tell "corrupt video" from "orphan cam" | Card only has thumb-onerror (→ black) and orphan (→ hatched) states | Have the backend include a clip-health hint (the new `file_size_bytes` from task C2 is a start — add a `playable`/`clip_ok` flag from a probe). Render a dedicated ⚠ "beschädigt / leer" overlay for corrupt/short/missing clips, distinct from the orphan-camera look. |
| **F6** | rescan/thumb-regen skips `heavy_rain` | `heavy_rain ∉ _WEATHER_PHASE_DIRS`, while `list_sightings` walks all dirs | Reconcile the two: either add `heavy_rain` (and any raw-event dirs) to the rescan walk, or drive both paths from one shared "weather event dirs" helper. |
| **F7** | Frozen / near-static clips (7), incl. heavy_rain | Stuck RTSP frame repeated; capture didn't dedup before encode | Capture side already has `is_near_duplicate` / `perceptual_hash` — gate frames through it and abort-to-skip when unique-frame ratio is too low (the `too_many_consecutive_backfills` skip already catches the low-fresh-frame variant; tune its thresholds to also catch "many frames, all identical"). |
| **F8** | 1 orphan thumb (M3), 1 clipless manifest (M4) | Skip/truncation left residue; clip deleted out-of-band | A reconcile pass (the existing rescan, once F6-corrected) can mark clipless manifests `missing_clip` and report orphan thumbs for cleanup — surfaced, not auto-deleted. |

### Notes for the fix phase
- The `_skip.json` mechanism itself is **working as designed** — it correctly bails
  when too few fresh frames are captured (example: `n_written=2`, `min_required=30`,
  `backfill_ratio=0.93`). The bug is purely that those markers are *counted as
  sightings* (F1). Do **not** delete skip markers; fix the reader.
- The corruption (F2/F3) is the higher-severity issue: it silently destroys clips
  that had already encoded successfully. Prioritise the atomic-write + post-encode
  probe before any cleanup of the existing stubs.
- No destructive action is recommended here. A future cleanup should *quarantine*
  (move aside) corrupt stubs rather than delete, so the originals — if recoverable
  from any backup/source frames — aren't lost.
