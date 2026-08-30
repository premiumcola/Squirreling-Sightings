"""A password with a reserved character must survive the trip into a URL.

An RTSP password routinely contains ``@``, ``:`` or ``/``. Written raw
into a URL's userinfo those characters ARE the syntax — ffmpeg reads
``rtsp://admin:p@ss@host/x`` as host ``ss`` and rejects the stream with
"Port missing in uri". The camera then never opens, and the only visible
symptom is a live tile saying KEIN SIGNAL.

This regressed when credential redaction moved URL assembly from the
browser (which encoded, via ``_rtspEnc``) to the server (which did not).
Two cameras stopped connecting; the third kept working only because its
password happened to hold no character that breaks a URL.
"""

from __future__ import annotations

import pytest

from app.routes._secrets import (
    merge_camera_secrets,
    set_url_password,
    strip_url_password,
    url_password,
)
from app.settings.migrations import migrate_rtsp_password_encoding

BASE = "rtsp://admin@192.0.2.10:554/h265Preview_01_main"

# Every one of these breaks a URL if written raw into the userinfo.
NASTY = ["p@ssword1", "pa:ss/word", "a/b@c:d", "pw#1?x", "plain123"]


@pytest.mark.parametrize("pw", NASTY)
def test_the_password_survives_a_round_trip(pw):
    built = set_url_password(BASE, pw)
    assert url_password(built) == pw


@pytest.mark.parametrize("pw", NASTY)
def test_the_host_is_never_swallowed_by_the_password(pw):
    """THE failure. With a raw '@' the parser takes the host from inside
    the password and the port disappears with it."""
    built = set_url_password(BASE, pw)
    assert built.endswith("@192.0.2.10:554/h265Preview_01_main")
    assert strip_url_password(built) == BASE


def test_an_url_that_already_carries_a_password_is_left_alone():
    """Hand-typed credentials are the operator's business."""
    manual = "rtsp://admin:other@192.0.2.10/x"
    assert set_url_password(manual, "p@ss") == manual


def test_a_url_without_a_username_gains_nothing():
    assert set_url_password("rtsp://192.0.2.10/x", "p@ss") == "rtsp://192.0.2.10/x"


def test_saving_heals_a_url_that_still_holds_a_raw_password():
    """Without the strip-first step the broken URL satisfies the
    "already has a password" guard and never repairs itself."""
    broken = "rtsp://admin:p@ss@192.0.2.10:554/x"
    out = merge_camera_secrets({"rtsp_url": broken}, {"password": "p@ss"})
    assert out["rtsp_url"] == "rtsp://admin:p%40ss@192.0.2.10:554/x"
    assert url_password(out["rtsp_url"]) == "p@ss"


def test_the_migration_repairs_stored_cameras():
    data = {
        "cameras": [
            {
                "id": "cam_broken",
                "password": "p@ss1",
                "rtsp_url": "rtsp://admin:p@ss1@192.0.2.10:554/main",
                "snapshot_url": "http://admin:p@ss1@192.0.2.10/cgi-bin/snapshot.cgi",
            },
        ]
    }
    migrate_rtsp_password_encoding(data)
    cam = data["cameras"][0]
    assert cam["rtsp_url"] == "rtsp://admin:p%40ss1@192.0.2.10:554/main"
    assert cam["snapshot_url"] == "http://admin:p%40ss1@192.0.2.10/cgi-bin/snapshot.cgi"
    assert cam["password"] == "p@ss1", "the stored password itself must stay raw"


def test_the_migration_leaves_a_correct_url_untouched():
    good = "rtsp://admin:p%40ss@192.0.2.10:554/main"
    data = {"cameras": [{"id": "c", "password": "p@ss", "rtsp_url": good}]}
    migrate_rtsp_password_encoding(data)
    assert data["cameras"][0]["rtsp_url"] == good


def test_the_migration_skips_a_camera_with_no_password():
    url = "rtsp://admin@192.0.2.10:554/main"
    data = {"cameras": [{"id": "c", "password": "", "rtsp_url": url}]}
    migrate_rtsp_password_encoding(data)
    assert data["cameras"][0]["rtsp_url"] == url


def test_the_migration_is_idempotent():
    data = {
        "cameras": [
            {"id": "c", "password": "p@ss", "rtsp_url": "rtsp://admin:p@ss@192.0.2.10:554/main"}
        ]
    }
    migrate_rtsp_password_encoding(data)
    once = data["cameras"][0]["rtsp_url"]
    migrate_rtsp_password_encoding(data)
    assert data["cameras"][0]["rtsp_url"] == once


def test_a_url_pointing_at_a_different_account_is_never_rewritten():
    """The repair must not become a credential clobber. A snapshot URL
    deliberately using a second, read-only account keeps it — the same
    guarantee test_secret_redaction pins for the save path."""
    from app.routes._secrets import reencode_url_password

    other = "http://viewer:andere@192.0.2.10/cgi-bin/snapshot.cgi"
    assert reencode_url_password(other, "p@ss") == other

    data = {"cameras": [{"id": "c", "password": "p@ss", "snapshot_url": other}]}
    migrate_rtsp_password_encoding(data)
    assert data["cameras"][0]["snapshot_url"] == other
