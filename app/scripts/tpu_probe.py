#!/usr/bin/env python3
"""Find out which EdgeTPU model this box can actually run.

`load_delegate` succeeding proves a Coral is present. It proves nothing
about the compiled model matching the installed libedgetpu — and that
gap produced a detector that reported "Coral TPU aktiv" while every
single inference raised:

    Encountered an unresolved custom op. Did you miss a custom op or
    delegate? Node number 8 (EdgeTpuDelegateForCustomOp) failed to invoke.

That error is almost always a version mismatch: a model compiled by a
newer edgetpu_compiler than the runtime library understands. Different
models were compiled at different times, so one may work where another
does not — which this script settles by simply trying each one.

Run it INSIDE the container, with the app STOPPED. An Edge TPU belongs
to one process; probing while the app holds the device gives a
misleading failure (or aborts the probe outright).

    docker compose stop
    docker compose run --rm --entrypoint python3 squirreling-sightings \\
        /app/scripts/tpu_probe.py
    docker compose start

Read-only: loads models, runs one inference each, writes nothing.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

MODELS_DIR = Path("/app/models")
DELEGATE_LIBS = ("libedgetpu.so.1", "libedgetpu.1.dylib", "edgetpu.dll")


def _versions() -> None:
    print("── Umgebung ──")
    print(f"  python           : {sys.version.split()[0]}")
    try:
        import tflite_runtime

        print(f"  tflite_runtime   : {getattr(tflite_runtime, '__version__', 'unbekannt')}")
    except Exception as e:
        print(f"  tflite_runtime   : FEHLT ({e})")
    try:
        import pycoral  # noqa: F401

        print("  pycoral          : vorhanden")
    except Exception:
        print("  pycoral          : fehlt (erwartet auf Python 3.11)")
    for lib in ("/usr/lib/x86_64-linux-gnu/libedgetpu.so.1", "/usr/lib/libedgetpu.so.1"):
        if Path(lib).exists():
            print(f"  libedgetpu       : {lib}")
            break
    else:
        print("  libedgetpu       : nicht in den Standardpfaden gefunden")
    print()


def _probe(tflite, model: Path) -> tuple[bool, str, float]:
    """Load `model` on the TPU and try ONE inference. Returns (ok, note, ms)."""
    import numpy as np

    delegate = None
    for lib in DELEGATE_LIBS:
        try:
            delegate = tflite.load_delegate(lib)
            break
        except Exception:
            continue
    if delegate is None:
        return False, "kein Delegate ladbar (kein Coral sichtbar?)", 0.0

    try:
        interp = tflite.Interpreter(model_path=str(model), experimental_delegates=[delegate])
        interp.allocate_tensors()
    except Exception as e:
        return False, f"allocate_tensors: {e}", 0.0

    inp = interp.get_input_details()[0]
    shape = inp["shape"]
    data = np.zeros(tuple(int(v) for v in shape), dtype=inp["dtype"])
    started = time.perf_counter()
    try:
        interp.set_tensor(inp["index"], data)
        interp.invoke()
    except Exception as e:
        return False, f"invoke: {e}", 0.0
    ms = (time.perf_counter() - started) * 1000.0

    # A second invoke is the honest latency — the first pays the
    # parameter transfer across USB.
    started = time.perf_counter()
    try:
        interp.invoke()
        ms = (time.perf_counter() - started) * 1000.0
    except Exception as e:
        return False, f"zweiter invoke: {e}", 0.0
    return True, f"input={list(shape)}", ms


def main() -> int:
    _versions()
    try:
        import tflite_runtime.interpreter as tflite
    except Exception as e:
        print(f"tflite_runtime nicht importierbar: {e}")
        return 2

    models = sorted(MODELS_DIR.glob("*_edgetpu.tflite"))
    if not models:
        print(f"Keine *_edgetpu.tflite in {MODELS_DIR}")
        return 1

    print("── Modelle ──")
    working = []
    for model in models:
        ok, note, ms = _probe(tflite, model)
        if ok:
            working.append((model.name, ms))
            print(f"  ✔ {model.name}\n      läuft · {ms:.1f} ms/Inferenz · {note}")
        else:
            print(f"  ✗ {model.name}\n      {note}")
    print()

    if working:
        print("── Ergebnis ──")
        print("  Diese Modelle laufen auf der TPU:")
        for name, ms in sorted(working, key=lambda p: p[1]):
            print(f"    {name}  ({ms:.1f} ms)")
        print()
        print("  Trage das schnellste passende in processing.detection.model_path ein.")
        print("  Achte darauf, dass die labels_path zum Modell passt.")
        return 0

    print("── Ergebnis ──")
    print("  KEIN kompiliertes Modell läuft mit dieser libedgetpu.")
    print("  Das ist ein Versions-Mismatch, kein Defekt der Hardware.")
    print("  Verlässlicher Weg: das Python-3.9-Image (docker/Dockerfile.coral)")
    print("  mit pycoral 2.0 + tflite-runtime 2.5.0 — die von Google")
    print("  getestete Kombination.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
