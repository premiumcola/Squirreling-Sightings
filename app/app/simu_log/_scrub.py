"""The last gate before a debug run reaches disk.

The document is built by this process, so in principle it carries only
what :mod:`app.routes._debug_snapshot` chose to put in it — and that
already routes the camera through ``redact_camera``. This runs anyway,
over the whole assembled payload, for two reasons:

* one block of it (``frontend``) is written by the browser, and
* the file exists to be READ — fetched over the LAN, pasted into a chat.
  A redaction that only happens where someone remembered to call it is
  the kind that stops happening the first time a field is added.

So the rule here is positional, not per-field: whatever the shape of the
payload, every string in it is scrubbed and every key that names a secret
is replaced by a ``<key>_set`` boolean. The masking itself is delegated
to :mod:`app.routes._secrets` — one implementation of "hide the
password", shared with the HTTP responses.
"""

from __future__ import annotations

import re

from ..routes._secrets import mask_url_password, redact_secrets

#: Keys whose VALUE is a secret wherever it appears. Replaced by
#: ``<key>_set``: "a password is configured" is a diagnosis; the password
#: itself never is.
SECRET_KEYS = (
    "password",
    "token",
    "bot_token",
    "api_key",
    "secret",
    "chat_id",
    "chat_ids",
)

#: Matched as a SUBSTRING of the key name, case-insensitively, so
#: ``mqtt_password``, ``alert_chat_ids`` or next year's ``api_secret``
#: are covered without anyone having to remember to extend the tuple
#: above. The exact list stays as documentation of the known shapes.
SECRET_KEY_PARTS = (
    "password",
    "passphrase",
    "token",
    "secret",
    "api_key",
    "chat_id",
)

#: Any embedded-credential URL — ``rtsp://admin:hunter2@cam/x``. Same
#: expression the Markdown snapshot's log scrubber uses.
_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"']*@[^\s\"']*")

#: A Telegram bot token, which is a plain string in prose and therefore
#: reaches no ``token`` key at all when it is quoted inside a log line.
_BOT_TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")

#: RFC-1918 IPv4. Not a credential, but the operator's internal topology,
#: and this document's whole purpose is to be pasted somewhere else. The
#: camera stays identifiable through ``camera.id`` / ``camera.name``,
#: which are in the same document, so nothing diagnostic is lost.
_LAN_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)

LAN_IP_MASK = "<lan-ip>"
TOKEN_MASK = "•••"


def scrub_text(text: str) -> str:
    """Mask every secret shape inside one string.

    URLs first: the mask leaves ``admin:•••@host`` behind, and running
    the bot-token pattern over the result cannot re-match it.
    """
    out = _URL_RE.sub(lambda m: mask_url_password(m.group(0)), text or "")
    out = _BOT_TOKEN_RE.sub(TOKEN_MASK, out)
    return _LAN_IP_RE.sub(LAN_IP_MASK, out)


def is_secret_key(key) -> bool:
    """Does this key name a value that must not leave the box?

    ``<key>_set`` is excluded: it is this module's OWN output — a
    boolean marker — and re-redacting it would turn ``password_set``
    into ``password_set_set`` on every pass over an already-scrubbed
    document.
    """
    name = str(key).lower()
    if name.endswith("_set"):
        return False
    return any(part in name for part in SECRET_KEY_PARTS)


def scrub(value):
    """Recursively scrub a JSON-shaped payload. Returns a new value."""
    if isinstance(value, dict):
        # redact_secrets drops each named key and leaves <key>_set behind,
        # so a scrubbed dict still answers "is one configured?".
        present = tuple(k for k in value if is_secret_key(k))
        out = redact_secrets(value, present) if present else dict(value)
        return {scrub_text(str(k)): scrub(v) for k, v in out.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value
