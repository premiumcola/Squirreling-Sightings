"""Das Filmstreifen-Blatt hinter der Scrub-Vorschau.

Gepinnt wird die Geometrie, nicht das Aussehen: der Player rechnet eine
Ziehposition über ``interval_s`` in einen Kachel-Index um und adressiert
die Kachel über ``cols``/``tile_w``/``tile_h``. Stimmt eine dieser Zahlen
nicht mit dem Blatt überein, zeigt die Vorschau stillschweigend das
falsche Einzelbild — ein Fehler, den niemand als Fehler erkennt, weil ein
Bild ja da ist.

Und die Deckungsregel: ein langer Clip bekommt einen GRÖSSEREN Abstand,
nicht einen abgeschnittenen Streifen. Ein Filmstreifen, der bei der
Hälfte des Clips aufhört, ist schlimmer als ein gröberer, der ihn ganz
abdeckt — beim Ziehen ans Ende käme sonst gar keine Vorschau.
"""

from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from app.scrub_sprite import (  # noqa: E402
    MAX_TILES,
    _plan,
    build_scrub_sprite,
    sprite_path_for,
)


def _write_clip(path: Path, *, frames: int, fps: int = 12, w: int = 320, h: int = 180) -> None:
    """A real decodable mp4 — the helper reads it with cv2, not a stub."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for i in range(frames):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # A moving block, so two tiles are never identical by accident.
        x = int((i / max(1, frames - 1)) * (w - 40))
        frame[60:120, x : x + 40] = (40, 200, 90)
        writer.write(frame)
    writer.release()


def test_der_pfad_folgt_der_sidecar_konvention():
    # Alles zu einem Event teilt einen Stamm — <id>.mp4, <id>.tracks.json,
    # <id>.scrub.jpg —, sonst behandelt der Storage-Abgleich sie nicht
    # mehr als eine Einheit.
    assert sprite_path_for(Path("/x/y/evt_1.mp4")).name == "evt_1.scrub.jpg"


def test_zwei_kacheln_pro_sekunde_bei_normaler_laenge():
    # 12 fps, Ziel 2/s → jeder 6. Frame.
    stride, count = _plan(total_frames=120, src_fps=12.0, fps=2.0)
    assert stride == 6
    assert count == 20


def test_ein_langer_clip_wird_groeber_statt_kuerzer():
    # 120 s bei 12 fps wären bei 2/s 240 Kacheln. Der Abstand wächst,
    # die Abdeckung bleibt vollständig.
    stride, count = _plan(total_frames=1440, src_fps=12.0, fps=2.0)
    assert count <= MAX_TILES
    assert stride * count >= 1440, "sonst endet der Streifen vor dem Clip"


def test_unlesbare_eingaben_sind_kein_absturz():
    assert _plan(0, 12.0, 2.0) == (0, 0)
    assert _plan(120, 0.0, 2.0) == (0, 0)
    assert build_scrub_sprite(Path("/nicht/vorhanden.mp4")) is None


def test_das_blatt_passt_zu_seiner_geometrie(tmp_path):
    clip = tmp_path / "evt_geo.mp4"
    _write_clip(clip, frames=60, fps=12)
    geo = build_scrub_sprite(clip)
    assert geo is not None, "der Testclip muss lesbar sein"

    sheet = cv2.imread(str(sprite_path_for(clip)))
    assert sheet is not None
    # DIE Zusicherung: das Bild ist genau so groß, wie die Geometrie
    # behauptet. Weicht das ab, adressiert der Player daneben.
    assert sheet.shape[1] == geo["cols"] * geo["tile_w"]
    assert sheet.shape[0] == geo["rows"] * geo["tile_h"]
    assert geo["count"] <= geo["cols"] * geo["rows"]
    assert geo["interval_s"] == pytest.approx(0.5, abs=0.05)


def test_die_kacheln_behalten_das_seitenverhaeltnis(tmp_path):
    clip = tmp_path / "evt_ar.mp4"
    _write_clip(clip, frames=24, fps=12, w=640, h=360)
    geo = build_scrub_sprite(clip)
    assert geo is not None
    assert geo["tile_w"] / geo["tile_h"] == pytest.approx(640 / 360, abs=0.02)
