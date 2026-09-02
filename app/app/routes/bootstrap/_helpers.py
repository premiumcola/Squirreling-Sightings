"""Pure helpers shared by the bootstrap blueprint's concern modules."""

from __future__ import annotations


def _auto_detect_subnet() -> str:
    """Best-effort detection of the LAN's /24 — fallback to a
    well-known RFC-1918 subnet when the socket trick fails (e.g.
    inside a network-isolated container)."""
    import ipaddress
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return str(ipaddress.IPv4Network(f"{ip}/24", strict=False))
    except Exception:
        return "192.168.1.0/24"


def _mask_pw(pw: str) -> str:
    """Return ``***`` for any password, or ``∅`` for empty — used in
    [discovery] log lines so the audit grep stays clean."""
    if not pw:
        return "∅"
    return "***"
