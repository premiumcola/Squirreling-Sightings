"""Deriving the identifying fragments of a legacy folder name.

Candidate-folder match rules (any one is enough):

    1. folder name == camera's current id
    2. folder name == "cam-" + IP-with-dashes  (e.g. "cam-192-0-2-172")
    3. folder name's slug contains both the IP last-octet AND the camera
       name slug — handles the "cam-Werkstatt.rechts.oben" alongside
       "cam-192-0-2-172" dual-folder case
    4. folder name's slug matches the camera name slug exactly
"""

from __future__ import annotations

from ..camera_id import _sanitise


def _extract_host(rtsp_url: str) -> str:
    """Pull the host portion out of an rtsp_url, ignoring optional creds and
    the port. Returns "" when the URL is empty/malformed."""
    if not rtsp_url or "://" not in rtsp_url:
        return ""
    rest = rtsp_url.split("://", 1)[1]
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    host = rest.split("/", 1)[0]
    if ":" in host and not host.count(":") > 1:  # ipv4:port — strip port
        host = host.split(":", 1)[0]
    return host


def _ip_last_octet(host: str) -> str:
    """IPv4 a.b.c.d → 'd'. Empty string for non-IPv4."""
    if not host or "." not in host:
        return ""
    parts = host.split(".")
    if len(parts) != 4:
        return ""
    last = parts[-1]
    return last if last.isdigit() else ""


def _ip_dashes(host: str) -> str:
    """IPv4 a.b.c.d → 'a-b-c-d'. Empty for non-IPv4."""
    if not host or "." not in host:
        return ""
    parts = host.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return ""
    return "-".join(parts)


def _folder_matches(
    folder_name: str, *, current_id: str, ip_dashes: str, ip_octet: str, name_slug: str
) -> bool:
    """Decide whether a sub-folder under one of the storage areas belongs
    to the camera identified by these markers. Conservative — must match
    one of the four rules described in the module docstring."""
    if not folder_name:
        return False
    if current_id and folder_name == current_id:
        return True
    if ip_dashes and folder_name == f"cam-{ip_dashes}":
        return True
    folder_slug = _sanitise(folder_name)
    if not folder_slug:
        return False
    if ip_octet and name_slug and ip_octet in folder_slug and name_slug in folder_slug:
        return True
    if name_slug and (folder_slug == name_slug or folder_slug == f"cam{name_slug}"):
        return True
    return False
