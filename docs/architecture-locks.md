# Threading Lock Inventory

Snapshot of every `threading.Lock` / `RLock` in the codebase as of the
O19 audit. Each entry documents:
- **File** — where the lock is defined
- **Guards** — what state it protects
- **Order** — if it has to be taken in a specific sequence relative to
  other locks (to avoid deadlocks)
- **IO inside lock?** — flag for any blocking IO (network, disk
  subprocess) that happens while the lock is held. These are the
  highest-risk sites for live-view stalls and should be migrated to
  the "compute outside, mutate inside" pattern.

Update this file when you add a lock OR change the lock-ordering
contract.

## Module-level locks

| File | Lock | Guards | Order | IO inside? |
|------|------|--------|-------|------------|
| `bird_dossiers.py` | `_rate_lock` | rate-limit window state | bottom (leaf) | no |
| `first_since.py` | `_records_lock` | first-sighting records dict | bottom (leaf) | no |
| `hls_streamer.py` | `_registry_lock` | global streamer registry dict | take BEFORE per-streamer `_proc_lock` | no |
| `server.py` | `_telegram_reload_lock` | single-flight telegram restart | top (only one thread ever takes it) | yes — telegram service start (3 s slot wait) |
| `tracking_worker.py` | `_worker_lock` | singleton worker construction | top | no |
| `routes/weather.py` | `_weather_thumb_regen_lock` | thumbnail regen single-flight | bottom | yes — disk ffmpeg subprocess |
| `weather_service/_sun_tl.py` | `_test_session_lock` | sun-tl test-session singleton | top | no |

## Per-instance locks

| File | Class.lock | Guards | Order | IO inside? |
|------|------------|--------|-------|------------|
| `bird_dossiers.py` | `BirdDossierStore._lock` | in-memory + JSON file | bottom | yes — atomic_write_json (disk) |
| `bird_dossiers.py` | `BirdDossierStore._inflight_lock` | in-flight dossier-build IDs | take INSIDE `_lock` | no |
| `hls_streamer.py` | `HlsStreamer._proc_lock` | per-streamer ffmpeg PID handle | take INSIDE `_registry_lock` | yes — subprocess.Popen/terminate |
| `logging_setup.py` | `BurstFilter._lock` | burst-window dedup state | bottom | no |
| `tracking_worker.py` | `TrackingWorker._failures_lock` | recent-failures ring buffer | bottom | no |
| `camera_runtime/runtime.py` | `Camera._lock` | reconnect-state coordination | top (capture path) | no |
| `camera_runtime/runtime.py` | `Camera.lock` | latest frame + frame_ts | bottom (frame buffer) | no |
| `camera_runtime/runtime.py` | `Camera._preview_cap_lock` | preview-substream capture handle | INSIDE `Camera._lock` | yes — cv2 VideoCapture |
| `camera_runtime/runtime.py` | `Camera._ach_lock` | achievement queue | bottom | no |
| `camera_runtime/runtime.py` | `Camera._viewers_lock` | MJPEG viewer count | bottom | no |
| `detectors/coral_object.py` | `CoralObjectDetector._infer_lock` | model invoke (TPU/CPU) | bottom | no (compute, not IO) |
| `settings/store.py` | `SettingsStore._runtime_lock` (RLock) | runtime.* sub-dict + save | top (UI path) | yes — settings.save() writes disk |
| `weather_service/service.py` | `WeatherService._lock` | shared snapshot state | top | no |
| `weather_service/service.py` | `WeatherService._history_lock` | history JSON file | INSIDE `_lock` | yes — atomic_write_json |
| `weather_service/_consts.py` | `WindowCache._lock` | sliding-window cache | bottom | no |
| `weather_service/_consts.py` | `ManifestStore._lock` | manifest JSON file | bottom | yes — atomic_write_json |
| `weather_service/_sun_tl.py` | `_SunTLTestSession.lock` | per-session state | bottom | no |

## Lock-order graph

```
top:    SettingsStore._runtime_lock
        WeatherService._lock
        Camera._lock
        _telegram_reload_lock
            ↓
mid:    HlsStreamer registry lock → per-streamer proc lock
        BirdDossierStore._lock → _inflight_lock
        WeatherService._lock → _history_lock
        Camera._lock → _preview_cap_lock
            ↓
bottom: leaf locks (rate, records, viewers, achievement, infer,
        burst-filter, failures, window-cache, manifest, sun-tl)
```

When a code path takes two locks, it MUST take them top-to-bottom
in the diagram above. Adding a new lock? Place it in the graph
explicitly here before merging.

## Known IO-in-lock sites (to migrate)

These are the highest-priority "compute outside, mutate inside"
candidates — every blocking call below holds the lock for the
duration of the IO, which is the root cause of the live-view
stall pattern the user reports periodically.

1. **SettingsStore._runtime_lock + save() on disk** — every
   runtime_set call writes settings.json under the lock. Most
   callers don't need atomicity beyond "the value lands"; the
   `runtime_alert_index_set` helper already shows the pattern.
   Long-tail fix: defer disk write to a debounced flush thread.

2. **WeatherService._history_lock + atomic_write_json** — sliding-
   window history rewrite holds the lock while disk-fsync runs.
   Could swap to copy-then-rename outside the lock.

3. **HlsStreamer._proc_lock + subprocess.terminate** — terminate
   blocks for SIGTERM grace period. Future: do the .kill() outside
   the lock once the handle is captured locally.

4. **Camera._preview_cap_lock + cv2.VideoCapture** — opening a
   substream takes 1-5 s on Reolink cams; that's a long hold for
   any code path that tries to peek at `preview_cap` simultaneously.

5. **BirdDossierStore._lock + atomic_write_json** — same shape as
   SettingsStore. Single-writer pattern means the lock is rarely
   contended in practice, but the contract is still "the lock is
   held for disk-fsync duration".

Migration is out of scope for the audit itself; this list is the
input to a follow-up "IO-in-lock removal" pass.
