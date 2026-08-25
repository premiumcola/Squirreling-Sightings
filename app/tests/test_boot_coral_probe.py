"""Boot inventory must recognise a Coral stick in BOTH USB states.

The stick re-enumerates once its firmware is loaded:
  1a6e:089a  Global Unichip Corp.   — uninitialised (fresh plug / cold boot)
  18d1:9302  Google Inc.            — after the first inference

The original probe required "Google" AND "1a6e:089a" in the same lsusb
output, which no single state can satisfy — the Google vendor string only
appears with the 18d1 id. Result: a working, already-initialised TPU was
logged as "not found" on every restart while the detectors were using it,
sending the operator hunting for a hardware fault that did not exist.
"""

from __future__ import annotations

import pytest

from app.lifecycle import classify_coral_usb

INITIALISED = "Bus 003 Device 007: ID 18d1:9302 Google Inc. \n"
UNINITIALISED = "Bus 003 Device 005: ID 1a6e:089a Global Unichip Corp. \n"
OTHER = (
    "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub\n"
    "Bus 002 Device 003: ID 0bda:8153 Realtek USB 10/100/1000 LAN\n"
)


def test_initialised_stick_is_found():
    assert classify_coral_usb(OTHER + INITIALISED) == "found (USB, initialised)"


def test_uninitialised_stick_is_found():
    assert classify_coral_usb(OTHER + UNINITIALISED) == "found (USB, uninitialised)"


def test_absent_stick_reports_not_found():
    assert classify_coral_usb(OTHER) == "not found"


def test_empty_output_reports_not_found():
    assert classify_coral_usb("") == "not found"


@pytest.mark.parametrize("state", [INITIALISED, UNINITIALISED])
def test_both_states_are_reported_as_present(state):
    """The regression in one line: BOTH enumerations mean 'the stick is there'."""
    assert classify_coral_usb(OTHER + state).startswith("found")


def test_the_impossible_conjunction_is_gone():
    """Lock the shipped source, not just the extracted helper."""
    from pathlib import Path

    from app import lifecycle

    src = Path(lifecycle.__file__).read_text(encoding="utf-8")
    assert '"Google" in out and "1a6e:089a"' not in src, (
        "the impossible conjunction is back: the Google vendor string only "
        "ever appears with id 18d1:9302, never with 1a6e:089a"
    )
