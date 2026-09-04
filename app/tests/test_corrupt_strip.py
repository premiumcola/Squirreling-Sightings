"""Der Streifentest muss die Wiese behalten und den Flush verwerfen.

Der Befund, den diese Datei festnagelt, stand im Log des Betreibers:

    14:47:48 DEBUG runtime [reolink_cx810_gartendachterrasse_181]
             corrupt strip detected, frame skipped        (x ~3 pro Sekunde,
             durchgehend, über Minuten)

Die Kamera zeigt eine sonnenbeschienene, gemähte Wiese, die genau die
unteren 60 Zeilen füllt. Die alte Prüfung fragte nur, ob dieser Streifen
gesättigt UND variabel ist — was eine Wiese exakt beschreibt. Ergebnis:
auf dieser Kamera lief gar keine Bewegungserkennung mehr, und der einzige
Hinweis war eine DEBUG-Zeile pro Frame.

Dass es ein Fehlalarm war und kein echter Artefakt, beweist dasselbe Log:
die Timelapse-Aufnahmen derselben Kamera, aus demselben Stream in
denselben Sekunden, gingen mit `attempt=1` durch — ein unabhängiger
Validator fand nichts. Ein Chroma-Flush ist außerdem stoßweise; einer,
der minutenlang ununterbrochen anliegt, ist keiner.

Deshalb ist der Test jetzt ein DIFFERENZTEST: der Streifen muss dem Bild
ÜBER ihm unähnlich sein. Beide Richtungen sind hier gepinnt — sonst
wandert die Schwelle beim nächsten Mal einfach in die andere Grube.
"""

from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.frame_helpers._anomaly_bands import has_corrupt_strip  # noqa: E402

_W, _H = 320, 240
_STRIP = 60


#: Saturation jitter applied to the WHOLE frame. Two things depend on it
#: and both matter. The absolute pre-gate demands std > 60, so a frame
#: built from flat colours never reaches the differential logic at all —
#: a "lawn is kept" test on a flat lawn would pass for the wrong reason
#: and would still pass with the fix reverted. And the base saturation
#: has to stay low enough that the jitter is not clipped away at 255,
#: which is what silently flattened the first two attempts at this
#: fixture back under the gate.
_SAT_BASE = 150
_SAT_JITTER = 120


def _hsv_frame(top_hsv, strip_hsv, hue_noise=0):
    """A frame with one HSV colour above and another in the bottom strip.

    `hue_noise` scatters the strip's hues around the wheel, which is what
    separates a rainbow flush from a band that is merely vivid.
    """
    rng = np.random.default_rng(7)
    img = np.zeros((_H, _W, 3), dtype=np.uint8)
    img[:, :] = top_hsv
    img[-_STRIP:, :] = strip_hsv
    sat = img[:, :, 1].astype(np.int16) + rng.integers(-_SAT_JITTER, _SAT_JITTER, (_H, _W))
    img[:, :, 1] = np.clip(sat, 0, 255).astype(np.uint8)
    if hue_noise:
        img[-_STRIP:, :, 0] = rng.integers(0, hue_noise, (_STRIP, _W)) % 180
    return cv2.cvtColor(img, cv2.COLOR_HSV2BGR)


def _passes_absolute_gate(frame) -> bool:
    """Does this frame reach the differential logic at all?

    Asserted in every case below. Without it a test could pass simply
    because the cheap first gate rejected the frame, and would keep
    passing with the whole fix removed.
    """
    hsv = cv2.cvtColor(frame[-_STRIP:], cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    return float(sat.mean()) > 120 and float(sat.std()) > 60


def test_eine_sonnige_wiese_ist_kein_defekt():
    """Der gemeldete Fall: kräftiges Grün, unten wie oben.

    DAS ist die Regression. Der Streifen ist gesättigt und variabel — die
    alte Prüfung hat hier jeden einzelnen Frame verworfen, ~3 pro Sekunde,
    solange die Sonne schien. Er geht durch die Vorprüfung (siehe
    assert unten) und wird trotzdem behalten, weil er dem Bild über ihm
    gleicht. Ohne den Differenztest fällt dieser Test um.
    """
    lawn = _hsv_frame((60, _SAT_BASE, 150), (60, _SAT_BASE, 150))
    assert _passes_absolute_gate(lawn), "sonst prüft dieser Test die Differenzlogik gar nicht"
    assert has_corrupt_strip(lawn) is False


def test_ein_flush_ueber_einer_stumpfen_szene_faellt_auf():
    """Grauer Hof oben, knallbunter Streifen unten — der Sättigungssprung."""
    frame = _hsv_frame((20, 25, 110), (170, _SAT_BASE, 200))
    assert _passes_absolute_gate(frame)
    assert has_corrupt_strip(frame) is True


def test_ein_flush_ueber_einer_kraeftigen_szene_faellt_auch_auf():
    """Wiese oben, Regenbogen unten — hier trägt die Farbstreuung.

    Der Fall, den ein reiner Sättigungsvergleich verpassen würde: beide
    Bänder sind gleich gesättigt, aber das Grün ist einfarbig und der
    Flush verteilt seine Farbtöne über den ganzen Kreis. Genau deshalb
    hat der Detektor zwei Zweige und nicht einen.
    """
    frame = _hsv_frame((60, _SAT_BASE, 150), (0, _SAT_BASE, 200), hue_noise=180)
    assert _passes_absolute_gate(frame)
    assert has_corrupt_strip(frame) is True


def test_ein_stumpfes_bild_kommt_gar_nicht_erst_in_die_pruefung():
    """Die absolute Vorprüfung bleibt der billige erste Filter."""
    frame = _hsv_frame((100, 0, 120), (100, 0, 120))
    assert not _passes_absolute_gate(frame)
    assert has_corrupt_strip(frame) is False


@pytest.mark.parametrize(
    "bad",
    [None, np.zeros((10, 10), dtype=np.uint8), np.zeros((20, 320, 3), dtype=np.uint8)],
)
def test_unbrauchbare_eingaben_sind_kein_absturz(bad):
    """Kein Bild, kein Farbbild, zu flach für Streifen plus Referenzband."""
    assert has_corrupt_strip(bad) is False
