"""Archive sizing — the numbers the unified-Mediathek work has to design against.

The dev checkout has no archive: ``storage/motion_detection/`` does not
exist there and the weather trees are gitignored. So every paging and
windowing decision for the merged library is currently unsized, and
guessing them is how you ship a page that opens in eight seconds on a
phone. This script produces the missing numbers, on the box, read-only.

It answers four questions:

  * **How much is there** — events per camera per month, so the merged
    query knows whether a month is a page or a thousand pages.
  * **How wide is a day** — the busiest single day-folder, because the
    date-pruned reader opens whole day folders and its worst case is
    one folder, not the average.
  * **How much is weather** — manifests per category, plus recaps,
    manual events and episode-ledger rows, so the merged feed knows the
    mix it has to interleave.
  * **What retention is actually holding** — bytes per tree, so the
    retention rows in the unified maintenance panel are set against real
    consumption rather than round numbers.

Read-only by construction: it opens directories and stats files, and
parses JSON only for the small weather manifests. It never writes, never
deletes and never touches settings.

Usage (on the Unraid host, inside the container)::

    docker exec -it squirreling-sightings \\
        python3 -m app.scripts.diag_library_size

Optional: pass a storage root to run it against a copy::

    python3 -m app.scripts.diag_library_size /mnt/backup/storage
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def _tree_bytes(root: Path) -> tuple[int, int]:
    """(bytes, file_count) under ``root``. Missing tree → (0, 0)."""
    total = 0
    files = 0
    if not root.exists():
        return 0, 0
    for p in root.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
                files += 1
        except OSError:
            continue
    return total, files


def _motion(root: Path) -> None:
    """Events per camera per month, and the widest single day folder.

    The month histogram sizes a query; the widest day sizes its WORST
    case, because the date-pruned reader's unit of work is a day folder.
    """
    base = root / "motion_detection"
    print("\n── Bewegungs-Archiv " + "─" * 44)
    if not base.exists():
        print(f"  {base} existiert nicht")
        return

    per_cam_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    widest: tuple[int, str] = (0, "—")
    total_events = 0
    total_days = 0

    for cam_dir in sorted(base.iterdir()):
        if not cam_dir.is_dir():
            continue
        for day_dir in sorted(cam_dir.iterdir()):
            if not day_dir.is_dir():
                continue
            try:
                n = sum(1 for p in day_dir.iterdir() if p.suffix == ".json")
            except OSError:
                continue
            if not n:
                continue
            total_days += 1
            total_events += n
            per_cam_month[cam_dir.name][day_dir.name[:7]] += n
            if n > widest[0]:
                widest = (n, f"{cam_dir.name}/{day_dir.name}")

    if not total_events:
        print("  keine Ereignisse gefunden")
        return

    for cam, months in sorted(per_cam_month.items()):
        cam_total = sum(months.values())
        print(f"\n  {cam}   {cam_total} Ereignisse")
        for month, n in sorted(months.items()):
            bar = "█" * min(40, max(1, n * 40 // max(months.values())))
            print(f"    {month}  {n:6d}  {bar}")

    print(f"\n  Summe:            {total_events} Ereignisse in {total_days} Tagesordnern")
    print(f"  Ø je Tagesordner: {total_events / max(1, total_days):.1f}")
    print(f"  Breitester Tag:   {widest[0]} ({widest[1]})   ← Worst case einer Fensterabfrage")


def _weather(root: Path) -> None:
    """Manifests per category, plus the three non-clip record kinds."""
    base = root / "weather"
    print("\n── Wetter-Archiv " + "─" * 47)
    if not base.exists():
        print(f"  {base} existiert nicht")
        return

    per_kind: dict[str, int] = defaultdict(int)
    per_cam: dict[str, int] = defaultdict(int)
    for cam_dir in sorted(base.iterdir()):
        if not cam_dir.is_dir() or cam_dir.name in ("recaps", "manual_events"):
            continue
        for evt_dir in sorted(cam_dir.iterdir()):
            if not evt_dir.is_dir() or evt_dir.name.startswith("."):
                continue
            try:
                n = sum(1 for p in evt_dir.glob("*.json"))
            except OSError:
                continue
            per_kind[evt_dir.name] += n
            per_cam[cam_dir.name] += n

    for kind, n in sorted(per_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<24s} {n:6d}")
    if per_cam:
        print()
        for cam, n in sorted(per_cam.items()):
            print(f"  {cam:<40s} {n:6d}")

    recaps = len(list((base / "recaps").glob("*.json"))) if (base / "recaps").exists() else 0
    manual = (
        len(list((base / "manual_events").glob("*.json")))
        if (base / "manual_events").exists()
        else 0
    )
    print(f"\n  Recaps: {recaps}    Manuelle Ereignisse: {manual}")

    ledger = root / "weather_episodes.jsonl"
    if ledger.exists():
        try:
            rows = sum(1 for line in ledger.open("r", encoding="utf-8") if line.strip())
        except OSError:
            rows = -1
        print(f"  Gewitter-Ledger: {rows} Zeilen ({_fmt_bytes(ledger.stat().st_size)})")

    for name in ("weather_history.jsonl", "weather_history.json"):
        p = root / name
        if p.exists():
            try:
                n = sum(1 for line in p.open("r", encoding="utf-8") if line.strip())
            except OSError:
                n = -1
            note = "" if name.endswith(".jsonl") else "   (Alt-Format)"
            print(f"  {name}: {n} Zeilen ({_fmt_bytes(p.stat().st_size)}){note}")


def _sizes(root: Path) -> None:
    """Bytes per tree — what the retention rows are actually holding."""
    print("\n── Belegung " + "─" * 52)
    trees = [
        ("motion_detection", "Bewegungs-Clips"),
        ("weather", "Wetter"),
        ("timelapse", "Timelapse-Videos"),
        ("timelapse_frames", "Timelapse-Einzelbilder"),
        ("net_archive", "Netz-Archiv"),
        ("adhoc_clips", "Ad-hoc-Clips"),
        ("logs", "Logs"),
        (".trash", "Papierkorb"),
    ]
    grand = 0
    for name, label in trees:
        b, files = _tree_bytes(root / name)
        grand += b
        if files:
            print(f"  {label:<26s} {_fmt_bytes(b):>10s}   {files:7d} Dateien")
        else:
            print(f"  {label:<26s} {'—':>10s}")
    print(f"  {'Summe':<26s} {_fmt_bytes(grand):>10s}")


def _judged(root: Path) -> None:
    """Judged events are immortal — so they set retention's floor."""
    base = root / "motion_detection"
    if not base.exists():
        return
    judged = 0
    scanned = 0
    for p in base.rglob("*.json"):
        scanned += 1
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if obj.get("confirmed") or obj.get("review") or obj.get("judged"):
            judged += 1
    if scanned:
        pct = 100.0 * judged / scanned
        print(f"\n  Beurteilte Ereignisse: {judged} von {scanned} ({pct:.1f} %)")
        print("  → diese sind von der Aufbewahrung ausgenommen und bleiben dauerhaft.")


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    else:
        try:
            from .. import app_state

            root = Path(app_state.storage_root)
        except Exception:
            root = Path("/app/storage")

    print(f"Archiv-Vermessung · {root}")
    if not root.exists():
        print(f"\nFEHLER: {root} existiert nicht. Pfad als Argument übergeben.")
        return 1

    _motion(root)
    _weather(root)
    _sizes(root)
    _judged(root)
    print("\nFertig. Nichts wurde geschrieben.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
