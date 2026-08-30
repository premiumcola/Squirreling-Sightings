"""The single secret boundary between settings.json and the browser.

The box serves plain HTTP on the LAN with no authentication and the
dashboard polls ``/api/config`` + ``/api/cameras`` every few seconds.
Anything either response carries is therefore a cleartext secret on the
wire, in every browser cache, and — for a ``type=password`` input — in
Chrome's password manager. So no response body ever carries a secret.

Three shapes leave this module, and only these three:

* ``<key>_set`` booleans instead of the value (``redact_secrets``).
* URLs with the ``:password`` removed from the userinfo
  (``strip_url_password``) — enough for every reader that needs the
  host, the vendor path, or just "is a stream configured?".
* URLs with the password replaced by dots (``mask_url_password``) for
  the backup-restore preview, which is *about* showing the shape.

The way back in is ``merge_camera_secrets``. Three-state contract,
shared verbatim with the Telegram token and the MQTT password:

===============  ==========================================
payload key      meaning
===============  ==========================================
absent           keep whatever is stored (the normal save)
``""``           clear the stored secret (explicit request)
non-empty        replace the stored secret
===============  ==========================================

The browser can no longer rebuild ``rtsp://user:pass@host/path``
because it no longer holds the password, so it sends the
credential-free URL it was given and the server puts the effective
password back. That keeps the round trip lossless without the secret
ever making the round trip.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

# Secrets that must never appear in a camera dict leaving the process.
CAMERA_SECRET_KEYS = ("password",)
# Camera fields that may carry an embedded ``user:password@`` userinfo.
CAMERA_URL_KEYS = ("rtsp_url", "snapshot_url")

# Same three dots the debug-snapshot scrubber and the backup-restore
# preview have always rendered — the mask string is part of a UI
# contract, not an implementation detail.
_MASK = "•••"


def _split_url(url: str) -> tuple[str, str, str, str] | None:
    """``scheme``, ``user``, ``password``, ``host+path`` — or ``None``.

    Deliberately string-level rather than ``urlparse``: an RTSP password
    routinely contains characters ``urlparse`` chokes on or silently
    re-encodes, and every caller here only ever wants to swap the
    userinfo back out again byte-for-byte.
    """
    if not url or "://" not in url or "@" not in url:
        return None
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user, _, password = creds.partition(":")
    return scheme, user, password, host


def _join_url(scheme: str, user: str, password: str, host: str) -> str:
    """Re-assemble, percent-encoding the password.

    THE BUG THIS FIXES: an RTSP password routinely contains ``@``, ``:``
    or ``/``. Written raw into the userinfo those characters ARE the URL
    syntax — ffmpeg parses ``rtsp://admin:p@ss@host/x`` as host ``ss`` and
    fails with "Port missing in uri", so the camera simply never opens.
    Before the redaction refactor the browser sent an already-encoded URL
    (``_rtspEnc`` in camedit/discovery.js); once the server started
    re-inserting the stored password itself, nothing encoded it.

    ``safe=""`` because every reserved character is unsafe HERE — this is
    userinfo, not a path. The mask string is passed through untouched: it
    is display-only and must stay readable as dots.
    """
    if not user:
        return f"{scheme}://{host}"
    if password and password != _MASK:
        password = quote(password, safe="")
    creds = f"{user}:{password}" if password else user
    return f"{scheme}://{creds}@{host}"


def strip_url_password(url: str) -> str:
    """``rtsp://admin:hunter2@cam/x`` → ``rtsp://admin@cam/x``.

    What every browser-side reader of ``rtsp_url`` actually needs: the
    host for the discovery de-dupe, the path for the Reolink check, and
    truthiness for the HD / fullscreen / simulate buttons.
    """
    parts = _split_url(url)
    if parts is None:
        return url
    scheme, user, _, host = parts
    return _join_url(scheme, user, "", host)


def mask_url_password(url: str) -> str:
    """Same, but leaves dots behind — for the backup-restore preview,
    whose whole job is showing the operator what shape they are about
    to restore."""
    parts = _split_url(url)
    if parts is None:
        return url
    scheme, user, password, host = parts
    if not password:
        return url
    return _join_url(scheme, user, _MASK, host)


def set_url_password(url: str, password: str) -> str:
    """Put ``password`` back into a credential-free URL.

    No-op when the URL carries no username (nothing to authenticate) or
    already carries a password of its own — a hand-edited snapshot URL
    with different credentials is honoured, not overwritten.
    """
    parts = _split_url(url)
    if parts is None:
        return url
    scheme, user, existing, host = parts
    if not user or existing:
        return url
    return _join_url(scheme, user, password, host)


def reencode_url_password(url: str, password: str) -> str:
    """Percent-encode an embedded password that was written raw.

    Only touches the URL when its embedded secret IS ``password`` — the
    same credential, merely unencoded. A URL deliberately pointing at a
    DIFFERENT account (a read-only snapshot viewer, say) keeps its own
    credentials: that is a documented, tested behaviour and not something
    a repair pass may quietly overwrite.
    """
    parts = _split_url(url)
    if parts is None:
        return url
    _scheme, user, existing, _host = parts
    if not user or not existing or not password:
        return url
    if unquote(existing) != password:
        return url
    return set_url_password(strip_url_password(url), password)


def url_password(url: str) -> str:
    """The DECODED password embedded in ``url``, or ``""``.

    The inverse of what ``_join_url`` writes, so a round trip through a
    stored URL returns the password the operator actually typed.
    """
    parts = _split_url(url)
    if parts is None:
        return ""
    return unquote(parts[2] or "")


def redact_secrets(section: dict | None, keys: tuple[str, ...]) -> dict:
    """Return a copy of ``section`` with every secret in ``keys`` dropped
    and replaced by a ``<key>_set`` boolean.

    Shipping only "is a value stored?" keeps the UI able to render the
    "unverändert" placeholder without ever handing the browser the
    value. The client must never echo ``<key>_set`` back into a payload
    — ``merge_camera_secrets`` drops those keys defensively because
    several partial-save paths build their payload by spreading a
    cached camera record.
    """
    out = dict(section or {})
    for key in keys:
        val = out.pop(key, None)
        out[f"{key}_set"] = bool(val)
    return out


def redact_camera(cam: dict | None) -> dict:
    """A camera dict safe to put in an HTTP response body.

    Drops ``password`` for ``password_set`` and strips the userinfo
    password out of every credential-bearing URL. Key names are
    otherwise unchanged so the display-only readers (dashboard chrome,
    discovery host de-dupe, sun-timelapse vendor check) keep working
    against the same fields they always read.
    """
    out = redact_secrets(cam, CAMERA_SECRET_KEYS)
    for key in CAMERA_URL_KEYS:
        if key in out:
            out[key] = strip_url_password(out.get(key) or "")
    return out


def merge_camera_secrets(payload: dict, stored: dict | None) -> dict:
    """Fold a redacted-round-trip camera payload back onto its secrets.

    Mutates and returns ``payload`` (the save handler owns it):

    1. every ``<key>_set`` marker is dropped — it is a response-only
       artefact and must never reach settings.json;
    2. an absent ``password`` means "unchanged", so the stored one is
       restored; ``""`` clears it, anything else replaces it;
    3. the effective password is put back into any credential-free URL
       in the payload, which is the shape the browser now sends.

    Runs before the connection-field diff in the save handler, so a
    partial save that merely echoes the redacted record compares equal
    and does not trigger a spurious camera restart.
    """
    stored = stored or {}
    for key in list(payload):
        if key.endswith("_set"):
            payload.pop(key, None)
    if "password" in payload:
        password = payload["password"] or ""
    else:
        password = stored.get("password") or ""
    payload["password"] = password
    for key in CAMERA_URL_KEYS:
        if key in payload:
            url = payload.get(key) or ""
            # Two distinct jobs: put the secret back into the
            # credential-free URL the browser was given, and repair a
            # stored URL whose password was written raw before this was
            # encoded. Neither may disturb a URL carrying a DIFFERENT
            # account's credentials.
            payload[key] = reencode_url_password(set_url_password(url, password), password)
    return payload
