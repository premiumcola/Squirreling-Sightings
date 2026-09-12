"""K5 · der Splitter-Filter, gegen die Zahlen aus dem echten Debug-Bundle.

„Bitte schau dir an, wieso die eine Person immer wieder splittet auf
jetzt in dem Fall eben drei Personen. Wenn ich einfach nur ganz ruhig
hin- und herlaufe."

Die Werte in `_WERKSTATT` sind keine erfundenen Beispiele: sie stehen so
im Bundle vom 2026-09-12 (`whole_clip.detections` der acht
Werkstatt-Clips vom 2026-09-11, 09:29–09:35), und `_OUTDOOR` sind echte
Spuren derselben Ausspielung von den beiden Außenkameras. Der Filter
muss die eine Menge treffen und die andere in Ruhe lassen — das ist die
ganze Prüfung, und sie ist deshalb aussagekräftig, weil beide Mengen aus
demselben Lauf stammen.
"""

from __future__ import annotations

from app.tracker_core import Track, TrackerState
from app.tracking_worker._clean import clean_tracks
from app.tracking_worker._splinters import (
    anchor_height_by_label,
    is_splinter,
    prune_splinter_tracks,
    track_height,
)

#: Die Spuren der acht Werkstatt-Clips: (Clip, Klasse, Beobachtungen,
#: Boxhöhe px, Splitter?). Bildhöhe 1440 px.
_WERKSTATT = [
    ("092909", "person", 9, 840, False),
    ("092909", "person", 18, 968, False),
    ("092955", "person", 2, 227, True),
    ("092955", "person", 1, 117, True),
    ("092955", "person", 72, 672, False),
    ("093052", "person", 23, 792, False),
    ("093052", "cat", 1, 128, False),  # einzige Katze im Clip — kein Anker
    ("093143", "person", 9, 619, False),
    ("093143", "person", 2, 128, True),
    ("093143", "person", 2, 227, True),
    ("093231", "person", 34, 872, False),
    ("093231", "person", 1, 173, True),
    ("093333", "person", 1, 728, False),  # dieselbe Person am Clip-Anfang
    ("093333", "person", 1, 151, True),
    ("093333", "person", 23, 824, False),
    ("093333", "person", 1, 215, True),
    ("093404", "person", 98, 840, False),
]

#: Dieselbe Ausspielung, die beiden Außenkameras. Die Garten-Kamera
#: blickt weit: ihre echten Personen sind 111–480 px hoch, also selbst
#: schon um den Faktor 4 auseinander. Nichts davon darf fallen.
#:
#: Die Höhen sind echt, die Zusammenstellung je Clip ist BEWUSST
#: schärfer als die Wirklichkeit: im Bundle steht das schlimmste
#: unschuldige Verhältnis bei ×1,72, hier bei ×2,31 („garten-a": 111 px
#: neben einem Anker von 256 px). Wer die Schwelle senkt, sieht es hier
#: zuerst — und nicht erst an einer verschwundenen Sichtung.
_OUTDOOR = [
    ("garten-a", "person", 1, 111),
    ("garten-a", "person", 6, 184),
    ("garten-a", "person", 31, 256),
    ("garten-b", "person", 1, 270),
    ("garten-b", "person", 3, 397),
    ("garten-b", "person", 53, 464),
    ("nutbar-a", "bird", 1, 311),
    ("nutbar-a", "bird", 13, 655),
    ("nutbar-b", "bird", 2, 366),
    ("nutbar-b", "bird", 6, 482),
    ("nutbar-c", "person", 1, 912),
    ("nutbar-c", "person", 14, 531),
]


def _track(label: str, n: int, height: int, track_id: str = "t") -> Track:
    tr = Track(track_id, label, 0)
    tr.samples = [
        {
            "f": i * 25,
            "t": float(i),
            "bbox": {"x1": 100, "y1": 200, "x2": 100 + height // 2, "y2": 200 + height},
            "score": 0.7,
            "source": "detect",
        }
        for i in range(n)
    ]
    tr.first_frame, tr.last_frame = 0, max(0, (n - 1) * 25)
    tr.best_score = 0.7
    return tr


def _state(rows) -> TrackerState:
    st = TrackerState()
    st.closed = [_track(lbl, n, h, track_id=f"{i}") for i, (lbl, n, h) in enumerate(rows)]
    return st


def _by_clip(table):
    clips: dict[str, list] = {}
    for row in table:
        clips.setdefault(row[0], []).append(row[1:])
    return clips


# ── die Bausteine ───────────────────────────────────────────────────────


def test_the_height_of_a_track_is_the_median_of_its_observations():
    """Median und nicht Maximum: ein einzelnes ausgefranstes Rechteck am
    Bildrand soll die Spur weder groß noch klein rechnen."""
    tr = _track("person", 3, 600)
    tr.samples[1]["bbox"]["y2"] = tr.samples[1]["bbox"]["y1"] + 60
    assert track_height(tr) == 600


def test_a_track_without_observations_has_no_height():
    tr = _track("person", 0, 600)
    assert track_height(tr) == 0.0


def test_only_established_tracks_may_serve_as_the_yardstick():
    """Sonst könnten sich zwei Splitter gegenseitig als Maßstab dienen
    und der Filter fräße sich an seinem eigenen Rauschen fest."""
    st = _state([("person", 2, 600), ("person", 1, 100)])
    assert anchor_height_by_label(st.closed) == {}
    assert prune_splinter_tracks(st, camera_id="cam") == 0


def test_the_yardstick_is_per_class():
    st = _state([("person", 9, 800), ("cat", 1, 120)])
    assert anchor_height_by_label(st.closed) == {"person": 800}
    # Die Katze hat keinen Anker ihrer eigenen Klasse und bleibt.
    assert prune_splinter_tracks(st, camera_id="cam") == 0


def test_a_long_but_small_track_is_never_a_splinter():
    """Die Kürze ist die halbe Bedingung. Wer zwanzig Mal gesehen wurde,
    ist ein Subjekt, egal wie klein er im Bild steht."""
    anchor = _track("person", 20, 800)
    small = _track("person", 20, 100)
    drop, _ = is_splinter(small, track_height(anchor))
    assert drop is False


def test_a_brief_but_similar_sized_track_is_never_a_splinter():
    """Die Größe ist die andere Hälfte. Zwei Personen nebeneinander, eine
    davon kurz im Bild, sind zwei Personen."""
    drop, _ = is_splinter(_track("person", 1, 700), 800)
    assert drop is False


# ── an den echten Zahlen ────────────────────────────────────────────────


def test_it_drops_exactly_the_werkstatt_splinters():
    for clip, rows in _by_clip(_WERKSTATT).items():
        st = _state([(lbl, n, h) for lbl, n, h, _ in rows])
        expected = [lbl for lbl, n, h, splinter in rows if not splinter]
        prune_splinter_tracks(st, camera_id="cam")
        assert [t.label for t in st.closed] == expected, f"Clip {clip}"


def test_the_complained_about_clip_ends_up_with_one_person():
    """093143 — die drei Spuren, die der Betreiber als drei Personen
    gesehen hat: eine echte über 9 Bilder (619 px) und zwei Aufblitzen
    über je 2 Bilder (128 und 227 px)."""
    rows = [r[1:4] for r in _WERKSTATT if r[0] == "093143"]
    st = _state(rows)
    assert prune_splinter_tracks(st, camera_id="cam") == 2
    assert len(st.closed) == 1
    assert track_height(st.closed[0]) == 619


def test_it_leaves_every_outdoor_track_alone():
    """Die Garten-Kamera blickt weit — dort ist eine Person mit 111 px
    neben einer mit 480 px völlig normal. Der Filter misst relativ zum
    größten Fund DESSELBEN Clips und darf hier nichts anfassen."""
    for clip, rows in _by_clip(_OUTDOOR).items():
        st = _state(rows)
        before = len(st.closed)
        assert prune_splinter_tracks(st, camera_id="cam") == 0, f"Clip {clip}"
        assert len(st.closed) == before


# ── Verdrahtung ─────────────────────────────────────────────────────────


def test_the_sweep_runs_as_part_of_the_clean_pass():
    st = _state([r[1:4] for r in _WERKSTATT if r[0] == "093143"])
    clean_tracks(st, camera_id="cam", cam_cfg={}, spawn_score=0.5)
    assert len(st.closed) == 1


def test_a_camera_can_switch_it_off():
    """Für eine Kamera mit echter Tiefenstaffelung, bei der ein Subjekt
    zu Recht ein Viertel so hoch sein darf wie ein anderes."""
    st = _state([r[1:4] for r in _WERKSTATT if r[0] == "093143"])
    clean_tracks(st, camera_id="cam", cam_cfg={"track_filter_splinters": False}, spawn_score=0.5)
    assert len(st.closed) == 3


def test_running_it_twice_changes_nothing():
    st = _state([r[1:4] for r in _WERKSTATT if r[0] == "093333"])
    first = prune_splinter_tracks(st, camera_id="cam")
    assert first == 2
    assert prune_splinter_tracks(st, camera_id="cam") == 0


def test_an_empty_state_is_a_no_op():
    assert prune_splinter_tracks(TrackerState(), camera_id="cam") == 0
