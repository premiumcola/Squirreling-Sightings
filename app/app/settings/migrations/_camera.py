"""Per-camera key backfills.

``migrate_camera_defaults`` chains ``migrate_threshold_keys`` at its
end — the threshold/NETZ/storage keys are additive and order-free, so
they ride along rather than taking their own slot in the boot
sequence.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from .._consts import (
    ALARM_PROFILE_TO_SEVERITY,
    CAMERA_NET_KEY_DEFAULTS,
    CAMERA_THRESHOLD_KEY_DEFAULTS,
    STORAGE_DEFAULTS,
)
from ..defaults import default_camera

log = logging.getLogger("app.settings.migrations")


def migrate_camera_defaults(data: dict, base_config: dict) -> None:
    cameras = data.setdefault("cameras", [])
    by_id = {c.get("id"): c for c in cameras}
    # Also index by display name so a seed cam that was renamed by the
    # storage_migration (e.g. "cam-Werkstatt.rechts.oben" →
    # "unknown_unknown_werkstatt_172") isn't blindly re-added under its
    # original id on the next boot. Two cams sharing the same name is
    # already handled elsewhere — this just stops the migration from
    # silently un-doing itself.
    by_name = {(c.get("name") or "").strip().lower(): c for c in cameras if c.get("name")}
    for c in base_config.get("cameras", []):
        base_name = (c.get("name") or "").strip().lower()
        if c["id"] in by_id:
            target = by_id[c["id"]]
        elif base_name and base_name in by_name:
            target = by_name[base_name]
        else:
            cameras.append(default_camera(c))
            continue
        # Only add missing keys; never overwrite user-saved values.
        defaults = default_camera(c)
        for key, val in defaults.items():
            target.setdefault(key, val)
    # The loop above only reaches cameras that also exist in
    # config.yaml — user-added cams never pass through it. THR-1's keys
    # have to land on EVERY camera, so the pass runs on its own below.
    migrate_threshold_keys(data)


def migrate_threshold_keys(data: dict) -> None:
    """THR-1 · additively land the new threshold-related keys.

    Purely additive: `setdefault` per key, so a value the operator
    already stored is never touched. Runs for every camera, including
    ones that only exist in settings.json.

    Chained from migrate_camera_defaults rather than registered as its
    own step in store.load() — the call sequence there belongs to a
    different package's file scope. Order is irrelevant: none of these
    keys is read by another migration.
    """
    touched_cams = 0
    for cam in data.get("cameras", []):
        if not isinstance(cam, dict):
            continue
        added = [k for k in CAMERA_THRESHOLD_KEY_DEFAULTS if k not in cam]
        for key in added:
            cam[key] = deepcopy(CAMERA_THRESHOLD_KEY_DEFAULTS[key])
        # NETZ · same additive rule, separate map. `net_auto` is a
        # boolean whose False is meaningful, so it must never travel
        # through an `or default` merge — setdefault is the only
        # correct operator here.
        net_added = [k for k in CAMERA_NET_KEY_DEFAULTS if k not in cam]
        for key in net_added:
            cam[key] = deepcopy(CAMERA_NET_KEY_DEFAULTS[key])
        if added or net_added:
            touched_cams += 1
    storage = data.setdefault("storage", {})
    if not isinstance(storage, dict):
        storage = {}
        data["storage"] = storage
    for key, val in STORAGE_DEFAULTS.items():
        storage.setdefault(key, val)
    if touched_cams:
        log.info("[migration] threshold-keys: %d Kameras nachgerüstet", touched_cams)


def migrate_class_severity(data: dict) -> None:
    """One-time migration: derive class_severity dict from the legacy
    alarm_profile when class_severity is empty. The legacy alarm_profile
    field stays in storage so older code paths still read it;
    class_severity becomes the new source of truth. Idempotent —
    cameras that already carry a non-empty class_severity dict are
    left untouched.
    """
    migrated = 0
    for cam in data.get("cameras", []):
        if cam.get("class_severity"):
            continue
        profile = (cam.get("alarm_profile") or "soft").strip() or "soft"
        mapping = ALARM_PROFILE_TO_SEVERITY.get(profile, ALARM_PROFILE_TO_SEVERITY["soft"])
        cam["class_severity"] = dict(mapping)
        migrated += 1
        log.info(
            "[migration] class_severity: %s ← alarm_profile=%s → %s",
            cam.get("id", "?"),
            profile,
            mapping,
        )
    if migrated:
        log.info("[migration] class_severity: %d Kameras migriert", migrated)


def migrate_label_thresholds(data: dict) -> None:
    """Rewrite the legacy person threshold default 0.65 → 0.45.

    A live test (user standing arms-out in frame) had Coral score
    person 0.28 and 0.44; both were rejected by the 0.65 floor and
    the user saw "Person wird nicht erkannt". 0.65 was the previous
    LABEL_THRESHOLD_DEFAULTS["person"], i.e. a value that landed
    in storage purely because it was the default at write time, not
    because the operator chose it. We rewrite ONLY that exact 0.65
    value — any other stored threshold (e.g. a deliberately raised
    0.55 or 0.80) is left untouched. Idempotent: cameras already on
    0.45 (or any non-0.65 value) skip the touch path.
    """
    touched = 0
    for cam in data.get("cameras", []):
        thrs = cam.get("label_thresholds")
        if not isinstance(thrs, dict):
            continue
        person = thrs.get("person")
        if not isinstance(person, (int, float)):
            continue
        if abs(float(person) - 0.65) < 1e-9:
            thrs["person"] = 0.45
            touched += 1
    if touched:
        log.info(
            "[migration] label-thresholds: rewrote stale person=0.65 → 0.45 " "on %d Kameras",
            touched,
        )


def migrate_rtsp_password_encoding(data: dict) -> None:
    """Percent-encode passwords sitting raw inside stored camera URLs.

    An RTSP password routinely contains ``@``, ``:`` or ``/``. Written raw
    into a URL's userinfo those characters ARE the syntax: ffmpeg reads
    ``rtsp://admin:p@ss@host/x`` as host ``ss`` and refuses the stream
    with "Port missing in uri", so the camera never opens and the live
    tile shows KEIN SIGNAL. The browser used to send an already-encoded
    URL; when the credential-redaction refactor moved URL assembly to the
    server, nothing encoded it any more and every camera whose password
    held a reserved character stopped connecting.

    Rewrites only the userinfo, only when re-encoding actually changes the
    string, and only when the camera has a stored password to put back —
    so a correctly-encoded URL, a credential-free one and a camera with no
    password are all left exactly as they are.
    """
    from ...routes._secrets import CAMERA_URL_KEYS, reencode_url_password

    fixed = 0
    for cam in data.get("cameras") or []:
        if not isinstance(cam, dict):
            continue
        password = cam.get("password") or ""
        if not password:
            continue
        for key in CAMERA_URL_KEYS:
            url = cam.get(key) or ""
            if not url:
                continue
            repaired = reencode_url_password(url, password)
            if repaired != url:
                cam[key] = repaired
                fixed += 1
    if fixed:
        log.info("[migration] %d Kamera-URL(s) mit kodiertem Passwort neu geschrieben", fixed)
