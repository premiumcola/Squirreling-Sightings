# Coral TPU image — switch-over, verification, rollback

Operator runbook for `ghcr.io/premiumcola/squirreling-sightings:coral`,
the second image built specifically to get the Edge TPU working.

All commands marked `[UNRAID root]` run on the Unraid host shell as
root, in
`/mnt/cache-ssd/appdata/devbox-src/squirreling-sightings`. Nothing here
is ever built locally — images come from ghcr.

---

## Why a second image

The Coral stick is present and `load_delegate` succeeds, but on the
`:latest` image every compiled model fails at the first inference:

    coco_ssd_mobilenet_v2_..._edgetpu.tflite  -> Node 4 failed to invoke
    efficientdet_lite0_edgetpu.tflite         -> Node 8
    inat_bird_quant_edgetpu.tflite            -> Node 1
    mobilenet_v2_1.0_224_quant_edgetpu.tflite -> Node 1

    Encountered an unresolved custom op. Did you miss a custom op or
    delegate? Node number N (EdgeTpuDelegateForCustomOp) failed to invoke.

Four different models failing at four different node numbers rules out
the models. `:latest` runs Python 3.11 with tflite-runtime 2.14.0, which
is far newer than the libedgetpu the Coral project paired it with. The
detector falls back to CPU — roughly 10x the latency.

`:coral` pins the combination Google actually ships and tests:

| | `:latest` | `:coral` |
|---|---|---|
| Base | `python:3.11-slim` | `python:3.9-slim-bookworm` |
| tflite-runtime | 2.14.0 | **2.5.0.post1** |
| pycoral | not installable on 3.11 | **2.0.0** |
| libedgetpu | `libedgetpu1-std`, best-effort | `libedgetpu1-std`, hard requirement |
| TPU path | delegate only (currently broken) | pycoral (tier 1) |

The build fails loudly if pycoral or libedgetpu are missing, so a
`:coral` image that exists at all has the stack in it. What it cannot
prove is that the *models* run — that is what the probe below is for.

---

## 1 · Switch over

Edit `docker-compose.yml` on the host. Change **only** the `image:` line
of the running service; every volume, device, port and environment entry
stays as it is:

```yaml
services:
  squirreling-sightings:
-   image: ghcr.io/premiumcola/squirreling-sightings:latest
+   image: ghcr.io/premiumcola/squirreling-sightings:coral
```

Keep `devices: - /dev/bus/usb:/dev/bus/usb` — without the USB
passthrough the TPU is invisible inside the container and `:coral` is
just a slower `:latest`.

Note the pin: `:coral` is a floating tag that Watchtower will keep
updating, same as `:latest`. To freeze a known-good build instead, use
the immutable per-commit tag `:coral-<short-sha>`.

```bash
# [UNRAID root]
cd /mnt/cache-ssd/appdata/devbox-src/squirreling-sightings
docker compose pull
docker compose up -d
```

---

## 2 · Verify the TPU is genuinely in use

Two checks. Do them in this order — the probe is the one that proves
inference, the log line only proves initialisation.

### 2a · Probe every model, with the app STOPPED

An Edge TPU belongs to exactly one process. Probing while the app holds
the device gives a misleading failure, so stop the app first:

```bash
# [UNRAID root]
docker compose stop
docker compose run --rm --entrypoint python3 squirreling-sightings \
    /app/scripts/tpu_probe.py
docker compose start
```

`tpu_probe.py` is read-only: it loads each `*_edgetpu.tflite` in
`/app/models`, runs two inferences, and reports the second one's latency
(the first pays the parameter transfer across USB).

What success looks like on `:coral`:

```
── Umgebung ──
  python           : 3.9.x
  tflite_runtime   : 2.5.0
  pycoral          : vorhanden
  libedgetpu       : /usr/lib/x86_64-linux-gnu/libedgetpu.so.1

── Modelle ──
  ✔ coco_ssd_mobilenet_v2_..._edgetpu.tflite
      läuft · 3.4 ms/Inferenz · input=[1, 300, 300, 3]
```

Read it like this:

- `pycoral : vorhanden` — you are on `:coral`. On `:latest` this line
  reads `fehlt`. If it still says `fehlt`, the image did not actually
  switch: re-check the `image:` line and that `docker compose pull`
  fetched something.
- `✔ … läuft · <n> ms` — the TPU ran a real inference. **This is the
  proof.** Single-digit milliseconds means TPU; tens to hundreds of
  milliseconds means you are looking at a CPU fallback wearing a
  checkmark.
- `✗ … invoke: … failed to invoke` — the original failure survived the
  version change. See "What can still go wrong" below.
- `kein Delegate ladbar (kein Coral sichtbar?)` — not a version problem
  at all: the container cannot see the stick. Check the `devices:`
  passthrough and `lsusb | grep 1a6e:089a` on the host.

### 2b · Confirm the running app took the pycoral path

```bash
# [UNRAID root]
docker logs squirreling-sightings --tail 50 | grep -i coral
```

The detector has three tiers and each logs a distinct line:

| Log line | Meaning |
|---|---|
| `[det] Coral TPU aktiv: <model>` | tier 1, pycoral — **what `:coral` should produce** |
| `[det] Coral TPU aktiv (EdgeTPU-Delegate): <model>` | tier 1b, delegate without pycoral — expected on `:latest`, means pycoral failed to load here |
| `[det] pycoral nicht verfügbar (…)` | tier 1 failed; the parenthesised reason is the real error |
| `[det] Kein Detektor verfügbar (…)` | all tiers failed; motion detection only |

On `:coral` the line must be the first one, with no `(EdgeTPU-Delegate)`
suffix. If you get the suffix, pycoral is present but did not
initialise — the `pycoral nicht verfügbar` warning immediately above it
names the reason.

---

## 3 · Roll back to `:latest`

Rollback is a tag change and a restart. Nothing in `:coral` writes a
different on-disk format, so `storage/`, `models/` and `settings.json`
carry over untouched in both directions.

```yaml
services:
  squirreling-sightings:
-   image: ghcr.io/premiumcola/squirreling-sightings:coral
+   image: ghcr.io/premiumcola/squirreling-sightings:latest
```

```bash
# [UNRAID root]
cd /mnt/cache-ssd/appdata/devbox-src/squirreling-sightings
docker compose pull
docker compose up -d
docker logs squirreling-sightings --tail 50
```

The old image is still in the local store, so if ghcr is unreachable
`docker compose up -d` will start it from cache.

---

## 4 · What can still go wrong

This image has never been built. The pins were verified against the
Coral package index by hand — wheel names, cp39 availability, and the
dependency metadata all check out — but only a real build on the box
settles the rest.

**At build time (CI turns red):**

- `libedgetpu1-std` not installable. `packages.cloud.google.com` is
  reachable and the package resolves on Debian 12, but this is an
  external repo the project does not control. Deliberately a hard
  failure — the alternative is an image that boots on CPU and looks
  healthy.
- The `import pycoral` smoke test in the Dockerfile fails. That means
  either a NumPy ABI break or `_pywrap_coral.so` not finding
  `libedgetpu.so.1`. Read the actual traceback in the CI log rather
  than guessing; both produce very different messages.
- A transitive dependency drops Python 3.9. pycoral pulls Pillow, which
  is unpinned; pip filters by `requires_python`, so this resolves
  today, but it is the most likely source of future drift.

**At runtime (build green, TPU still not used):**

- **The models are also too new.** This is the real residual risk. The
  fix targets the runtime/library mismatch, which the evidence points
  at squarely — but if `edgetpu_compiler` produced a model requiring a
  newer runtime than `libedgetpu1-std` provides, the same
  `failed to invoke` error appears on this image too. The probe in step
  2a is what distinguishes the two, and it distinguishes them
  per-model: a mixed result (some ✔, some ✗) is strong evidence the
  remaining failures are compiler-version problems in those specific
  files, and the fix is to re-download them from
  `google-coral/test_data` rather than to change the image again.
- **USB throughput on the Unraid host.** The stick needs USB 3 to hit
  single-digit-millisecond latency. A ✔ with 40–60 ms is a working TPU
  on a USB 2 port, not a broken install.
- **Python 3.9 language floor.** `:coral` runs three minor versions
  behind `:latest`. Any `datetime.UTC` (3.11+), `zip(strict=)` (3.10+)
  or match statement reaching `app/app/` will `ImportError` or
  `SyntaxError` on this image while `:latest` stays green. If `:coral`
  crashes on boot with a traceback but `:latest` does not, this is the
  first thing to check — and the fix belongs in the app code, not here.
