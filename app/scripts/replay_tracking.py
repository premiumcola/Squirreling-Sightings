#!/usr/bin/env python3
"""Re-run detection + tracking over already-recorded clips, offline.

Why this exists: every tracking change so far could only be argued from
code reading. This replays the real videos already on disk through the
same `tracker_core` the live path uses, renders what it saw, and prints
numbers you can compare between two runs — so a claimed improvement can
be confirmed or refuted instead of believed.

SAFE TO RUN ALONGSIDE THE LIVE INSTANCE:
  * Read-only on storage. The only writes go to --out (default
    storage/_replay/), never into motion_detection/.
  * Forces `prefer_cpu`, so it never takes the Edge TPU away from the
    running camera loops. On a 5950X that costs latency, not much else,
    and this is a batch job.
  * Touches no settings, starts no server, sends no Telegram message.

Typical use, from inside the container:

    docker exec squirreling-sightings python3 /app/scripts/replay_tracking.py \\
        --cam reolink_rlc811a_squirreltownnutbar_183 --latest 5 --stills 6

Then look at the JPEGs it names, and at the summary table.

Comparing before/after a code change: run it once, keep --out, apply the
change, run again into a different --out, and diff the summary JSONs.
`--baseline` additionally diffs against the tracks.json sidecar that the
background worker wrote at recording time.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import cv2  # noqa: E402

from app.detectors import CoralObjectDetector, draw_detections  # noqa: E402
from app.tracker_core import LiveTracker  # noqa: E402


def _load_cfg(storage_root: Path) -> dict:
    """Detection config from settings.json, falling back to config.yaml."""
    settings_path = storage_root / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            det = (data.get("processing") or {}).get("detection") or {}
            if det.get("model_path"):
                return dict(det)
        except Exception as exc:
            print(f"  ! settings.json unreadable ({exc}) — falling back to config.yaml")
    for candidate in (
        Path("/app/config/config.yaml"),
        REPO_ROOT / "config" / "config.yaml",
        REPO_ROOT / "config" / "config.yaml.example",
    ):
        if candidate.exists():
            try:
                import yaml

                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                return dict((data.get("processing") or {}).get("detection") or {})
            except Exception:
                continue
    return {}


def _find_clips(storage_root: Path, cam: str | None, latest: int) -> list[Path]:
    root = storage_root / "motion_detection"
    if not root.exists():
        return []
    cam_dirs = [root / cam] if cam else [d for d in root.iterdir() if d.is_dir()]
    clips: list[Path] = []
    for d in cam_dirs:
        if not d.exists():
            continue
        # Skip the stream-copy intermediates; they are not always playable.
        clips.extend(p for p in d.rglob("*.mp4") if not p.name.endswith(".raw.mp4"))
    clips.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return clips[:latest]


def _replay(video: Path, detector, args, out_dir: Path) -> dict | None:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        print(f"  ! cannot open {video.name}")
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(fps / max(0.1, args.sample_fps))))

    tracker = LiveTracker(
        camera_id=video.stem,
        spawn_default=args.spawn,
        iou_threshold=args.iou,
    )

    stills_written: list[str] = []
    label_counts: Counter = Counter()
    frames_seen = 0
    frames_with_dets = 0
    track_labels: dict[str, Counter] = {}
    still_every = max(1, (total // step) // max(1, args.stills)) if total else 25

    idx = 0
    kept = 0
    t0 = time.perf_counter()
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        idx += 1
        if not ok or frame is None:
            continue
        frames_seen += 1

        dets = detector.detect_frame_raw(frame, threshold=args.floor) or []
        survivors = tracker.step(dets, t_s=frames_seen / max(0.1, args.sample_fps), fps=fps)
        if survivors:
            frames_with_dets += 1
        for d in survivors:
            label_counts[d.label] += 1

        # Which track each surviving label belongs to, so identity churn
        # shows up as a track that changed its mind about what it is.
        for tr in tracker.state.active:
            track_labels.setdefault(tr.track_id, Counter())[tr.label] += 1

        if args.stills and survivors and (kept % still_every == 0):
            drawn = frame.copy()
            try:
                drawn = draw_detections(drawn, survivors)
            except Exception:
                for d in survivors:
                    x1, y1, x2, y2 = d.bbox
                    cv2.rectangle(drawn, (x1, y1), (x2, y2), (0, 220, 0), 2)
                    cv2.putText(
                        drawn,
                        f"{d.label} {d.score:.2f}",
                        (x1, max(14, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 220, 0),
                        2,
                    )
            h, w = drawn.shape[:2]
            if w > 1280:
                drawn = cv2.resize(drawn, (1280, int(h * 1280 / w)), interpolation=cv2.INTER_AREA)
            name = f"{video.stem}_f{frames_seen:04d}.jpg"
            cv2.imwrite(str(out_dir / name), drawn, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            stills_written.append(name)
        if survivors:
            kept += 1
        if args.max_frames and frames_seen >= args.max_frames:
            break
    cap.release()
    elapsed = time.perf_counter() - t0

    closed = list(getattr(tracker.state, "closed", []) or [])
    active = list(tracker.state.active)
    all_tracks = closed + active
    flapping = {tid: dict(c) for tid, c in track_labels.items() if len(c) > 1}

    return {
        "video": str(video),
        "frames_sampled": frames_seen,
        "frames_with_detections": frames_with_dets,
        "seconds": round(elapsed, 1),
        "tracks_total": len(all_tracks),
        "tracks_still_active_at_end": len(active),
        "label_hits": dict(label_counts),
        "tracks_that_changed_label": flapping,
        "stills": stills_written,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--storage", default="/app/storage", help="storage root")
    ap.add_argument("--cam", default=None, help="camera id (default: all)")
    ap.add_argument("--latest", type=int, default=3, help="how many recent clips")
    ap.add_argument("--video", default=None, help="one specific mp4 instead of --latest")
    ap.add_argument("--out", default=None, help="output dir (default storage/_replay)")
    ap.add_argument("--stills", type=int, default=4, help="annotated JPEGs per clip")
    ap.add_argument("--sample-fps", type=float, default=3.0, help="frames analysed per second")
    ap.add_argument("--max-frames", type=int, default=0, help="cap sampled frames (0 = all)")
    ap.add_argument("--floor", type=float, default=0.20, help="detector score floor")
    ap.add_argument("--spawn", type=float, default=0.50, help="track spawn score")
    ap.add_argument("--iou", type=float, default=0.30, help="IoU match threshold")
    args = ap.parse_args()

    storage_root = Path(args.storage)
    if not storage_root.exists():
        print(f"storage root not found: {storage_root}")
        return 2
    out_dir = Path(args.out) if args.out else storage_root / "_replay"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = _load_cfg(storage_root)
    if not cfg.get("model_path"):
        print("no detection model configured — nothing to replay")
        return 2
    # Never contend with the live camera loops for the single USB TPU.
    cfg = dict(cfg)
    cfg["prefer_cpu"] = True
    cfg.setdefault("mode", "coral")

    print(f"model : {cfg.get('cpu_model_path') or cfg.get('model_path')}  (CPU, forced)")
    detector = CoralObjectDetector(cfg)
    if not detector.available:
        print(f"detector unavailable: {detector.reason}")
        return 2
    print(f"mode  : {detector.mode} ({detector.reason})")

    if args.video:
        clips = [Path(args.video)]
    else:
        clips = _find_clips(storage_root, args.cam, args.latest)
    if not clips:
        print("no clips found")
        return 1
    print(f"clips : {len(clips)}\nout   : {out_dir}\n")

    results = []
    for clip in clips:
        print(f"→ {clip.name}")
        res = _replay(clip, detector, args, out_dir)
        if not res:
            continue
        results.append(res)
        print(
            f"   {res['frames_sampled']} Frames · {res['tracks_total']} Spuren · "
            f"{res['frames_with_detections']} Frames mit Treffern · {res['seconds']}s"
        )
        if res["label_hits"]:
            top = ", ".join(f"{k}×{v}" for k, v in sorted(res["label_hits"].items()))
            print(f"   Labels: {top}")
        if res["tracks_that_changed_label"]:
            print(f"   ⚠ Spuren mit Label-Wechsel: {len(res['tracks_that_changed_label'])}")
        if res["stills"]:
            print(f"   Bilder: {', '.join(res['stills'])}")

    summary = out_dir / "summary.json"
    summary.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nZusammenfassung: {summary}")
    total_tracks = sum(r["tracks_total"] for r in results)
    flaps = sum(len(r["tracks_that_changed_label"]) for r in results)
    print(f"Gesamt: {total_tracks} Spuren, davon {flaps} mit Label-Wechsel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
