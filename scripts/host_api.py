#!/usr/bin/env python3
"""Reach the RUNNING app from the devbox, so a diagnosis needs no copy-paste.

    scripts/host_api.py /api/cameras
    scripts/host_api.py /api/cameras/<cam_id>/debug-snapshot?format=json
    scripts/host_api.py --post /api/debug/bundle

WHY THIS EXISTS. The devbox has no Docker CLI and cannot see `appdata`,
so for a long time the only way to get a state dump to whoever was
debugging was the operator copying an enormous JSON document out of the
browser and pasting it into a chat — „Debug bitte irgendwie ablegen dass
du es hier am besten direkt selbst einlesen kannst ohne dass ichs
schicken muss den ewigen text!".

It turns out no bridge was needed at all: the devbox is a container on
the same host as the app, so the host is reachable over the container's
own default gateway and the whole HTTP API answers. Measured, not
assumed — `/version.json` and `/api/cameras` both return 200.

NO HARDCODED ADDRESS. The gateway is read out of /proc/net/route at call
time. A written-down 172.x would be wrong on any host with a different
bridge, and CLAUDE.md keeps real addresses out of tracked files for a
reason. `SQ_HOST` overrides everything when the app runs somewhere else.

READ-ONLY BY DEFAULT. A GET cannot change the box; `--post` exists for
the two diagnostic endpoints that need it and has to be asked for.
Never point this at `/api/settings/*` — that endpoint returns tokens and
RTSP passwords unredacted, and this output lands in a transcript.
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import urllib.error
import urllib.request

PORT = int(os.environ.get("SQ_PORT", "8099"))
TIMEOUT_S = 10


def default_gateways() -> list[str]:
    """Every default gateway this container has, best first.

    /proc/net/route stores addresses as little-endian hex, so the bytes
    come out reversed from what they read as.
    """
    out: list[str] = []
    try:
        with open("/proc/net/route", encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    out.append(socket.inet_ntoa(struct.pack("<L", int(parts[2], 16))))
    except OSError:
        pass
    # The Docker default bridge, as a last resort for a host whose
    # routing table does not name it.
    if "172.17.0.1" not in out:
        out.append("172.17.0.1")
    return out


def candidates() -> list[str]:
    forced = os.environ.get("SQ_HOST", "").strip()
    return [forced] if forced else default_gateways()


def fetch(path: str, post: bool = False) -> tuple[str, str]:
    """``(body, base)`` from the first host that answers. Raises on none."""
    if not path.startswith("/"):
        path = "/" + path
    errors = []
    for host in candidates():
        base = f"http://{host}:{PORT}"
        req = urllib.request.Request(base + path, method="POST" if post else "GET")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return r.read().decode("utf-8", errors="replace"), base
        except Exception as e:  # noqa: BLE001 - report every candidate
            errors.append(f"{base}: {e}")
    raise SystemExit(
        "kein erreichbarer Host.\n  " + "\n  ".join(errors) + "\n"
        "SQ_HOST=<adresse> setzen, wenn die App woanders läuft."
    )


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--post"]
    if not args:
        print(__doc__)
        return 2
    body, base = fetch(args[0], post="--post" in sys.argv[1:])
    print(f"# {base}{args[0]}", file=sys.stderr)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
