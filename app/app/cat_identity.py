from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .io_utils import atomic_write_json


def dhash_bgr(img: np.ndarray) -> str | None:
    if img is None or img.size == 0:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8))
    diff = small[:, 1:] > small[:, :-1]
    bits = ''.join('1' if v else '0' for v in diff.flatten())
    return f"{int(bits, 2):016x}"


#: Welcher Teil des Personen-Ausschnitts verglichen wird, als Anteil
#: (oben, unten, links, rechts) des Rechtecks.
#:
#: „ich würde sagen du solltest eher auf die köpfe gehen die müssen ja
#: wiedererkannt werden! - komplett weis ich nicht ob das sinn macht!"
#:
#: Der Gedanke stimmt: Kleidung wechselt täglich, ein Kopf nicht. Nur
#: lässt er sich nicht einfach behaupten — es gibt in diesem Projekt KEIN
#: Gesichtsmodell (der Detektor kennt COCO-Klassen, „face" ist keine
#: davon), also ist „Kopf" hier ein geometrischer Ausschnitt und keine
#: Erkennung: das obere Viertel des Personen-Rechtecks, horizontal
#: eingezogen. Bei einer stehenden Person trifft das Kopf und Schultern.
#:
#: Und es gibt ein Gegenargument, das man kennen muss, bevor man
#: umstellt: der dHash ist ein 8×8-Gradient. Ein Kopf, der im Bild 90 px
#: hoch ist, wird dafür auf acht Zeilen heruntergerechnet — vom Gesicht
#: bleiben vier Pixel. Weniger Fläche heißt hier nicht schärfer, sondern
#: gröber. Deshalb wird nicht umgestellt, sondern GEMESSEN: jede Probe
#: bekommt alle drei Hashes, `identity_quality` rechnet die Trefferquote
#: für jeden Bereich getrennt aus, und die Zahl entscheidet.
REGIONS = {
    "full": (0.0, 1.0, 0.0, 1.0),
    "upper": (0.0, 0.45, 0.0, 1.0),
    "head": (0.0, 0.26, 0.20, 0.80),
}

#: Der Bereich, auf dem der Abgleich tatsächlich läuft. Bleibt „full",
#: bis die Messung etwas anderes sagt — eine unbelegte Umstellung wäre
#: genau der Griff, den die Messung überflüssig machen soll.
DEFAULT_REGION = "full"

#: Unter dieser Kantenlänge ist ein Ausschnitt für einen 9×8-Gradienten
#: zu klein; der Hash daraus ist Rauschen.
MIN_REGION_PX = 12


def crop_region(img, region: str):
    """Den benannten Teil eines Ausschnitts, oder None, wenn er zu klein
    wird. Der volle Bereich gibt das Bild unverändert zurück."""
    box = REGIONS.get(region)
    if img is None or box is None:
        return None
    if region == "full":
        return img
    top, bottom, left, right = box
    h, w = img.shape[:2]
    y1, y2 = int(h * top), int(h * bottom)
    x1, x2 = int(w * left), int(w * right)
    if (y2 - y1) < MIN_REGION_PX or (x2 - x1) < MIN_REGION_PX:
        return None
    return img[y1:y2, x1:x2]


def region_hashes(img) -> dict:
    """Alle Bereiche eines Ausschnitts auf einmal, leere ausgelassen."""
    out = {}
    for region in REGIONS:
        part = crop_region(img, region)
        if part is None:
            continue
        h = dhash_bgr(part)
        if h:
            out[region] = h
    return out


def sample_hash(sample: dict, region: str) -> str | None:
    """Der Hash einer Probe für einen Bereich.

    ``full`` liegt weiterhin unter ``h`` — das ist der Schlüssel, auf dem
    der Abgleich seit jeher läuft, und ihn umzubenennen hätte jede
    bestehende Registry entwertet, ohne irgendetwas zu verbessern.
    """
    if region == "full":
        return sample.get("h")
    return (sample.get("hr") or {}).get(region)


def hamming_hex(a: str, b: str) -> int:
    # bin().count("1") rather than int.bit_count() — the latter is 3.10+
    # and the Coral image runs Python 3.9. Both operands are non-negative,
    # so the "0b" prefix contributes no "1" and there is no sign char.
    return bin(int(a, 16) ^ int(b, 16)).count("1")


#: Wie viele Ausschnitt-Verweise die Oberfläche je Profil bekommt — der
#: erste ist das Avatar, der Rest der kleine Stapel dahinter. Abgeleitet
#: aus den Proben, nicht getrennt geführt.
MAX_PROFILE_CROPS = 8

#: Obergrenze der Proben je Profil. Jede kostet rund 150 Byte; fünfhundert
#: sind also 75 KB und mehr Material, als die Güteprüfung braucht. Die
#: ältesten fallen hinten heraus.
MAX_PROFILE_SAMPLES = 500


def profile_samples(profile: dict) -> list[dict]:
    """Die Proben eines Profils, neueste zuerst.

    EIN Ort für die Wahrheit, mit einer Rückfallschiene: Profile, die vor
    dem 2026-09-13 geschrieben wurden, haben nur eine flache
    ``hashes``-Liste ohne Herkunft. Die werden hier als Proben ohne
    Ereignis nachgereicht, damit der Abgleich sie weiter findet — für die
    Güteprüfung taugen sie nicht, weil man ohne Ereignis nicht trennen
    kann, was aus demselben Moment stammt.
    """
    out = [s for s in (profile.get("samples") or []) if isinstance(s, dict) and s.get("h")]
    known = {s["h"] for s in out}
    for h in profile.get("hashes") or []:
        if h not in known:
            out.append({"h": h, "relpath": "", "event_id": ""})
    return out


def profile_crops(profile: dict) -> list[str]:
    """Die Bilder, die die Oberfläche als Gesicht des Profils zeigt."""
    seen = []
    for s in profile_samples(profile):
        rel = s.get("relpath")
        if rel and rel not in seen:
            seen.append(rel)
        if len(seen) >= MAX_PROFILE_CROPS:
            break
    return seen


class IdentityRegistry:
    def __init__(self, path: str | Path, threshold: int = 10, region: str = DEFAULT_REGION):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.threshold = threshold
        self.region = region if region in REGIONS else DEFAULT_REGION
        self.data = {"profiles": []}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {"profiles": []}

    def _save(self):
        atomic_write_json(self.path, self.data)

    def list_profiles(self):
        return self.data.get("profiles", [])

    def get_profile(self, name: str):
        return next((p for p in self.data.get("profiles", []) if p.get("name") == name), None)

    def set_profile_flags(
        self,
        name: str,
        *,
        whitelisted: bool | None = None,
        notes: str | None = None,
        anonymous: bool | None = None,
    ):
        p = self.get_profile(name)
        if not p:
            return False
        if whitelisted is not None:
            p["whitelisted"] = bool(whitelisted)
        if notes is not None:
            p["notes"] = notes
        if anonymous is not None:
            p["anonymous"] = bool(anonymous)
        self._save()
        return True

    def next_anonymous_name(self, prefix: str = "Bekannt") -> str:
        """Der nächste freie neutrale Name.

        „Ich würde gerne bestimmte Personen … auf neutral oder bekannt,
        aber ohne Namensnennung aufnehmen." Ein Profil braucht trotzdem
        einen Schlüssel, sonst lassen sich zwei unbenannte Personen nicht
        auseinanderhalten — also eine Nummer statt eines Namens. Gezählt
        wird über ALLE Profile, nicht nur die neutralen: sonst käme nach
        einer Umbenennung von „Bekannt 2" zu „Anna" ein zweites
        „Bekannt 2" heraus.
        """
        used = {(p.get("name") or "").strip() for p in self.list_profiles()}
        n = 1
        while f"{prefix} {n}" in used:
            n += 1
        return f"{prefix} {n}"

    def match_details(self, crop: np.ndarray) -> dict | None:
        part = crop_region(crop, self.region)
        h = dhash_bgr(part) if part is not None else None
        if not h:
            return None
        best = None
        best_dist = 999
        for p in self.data.get("profiles", []):
            for sample in profile_samples(p):
                other = sample_hash(sample, self.region)
                if not other:
                    continue
                try:
                    d = hamming_hex(h, other)
                except Exception:
                    continue
                if d < best_dist:
                    best_dist = d
                    best = p
        if best is not None and best_dist <= self.threshold:
            return {
                "name": best.get("name"),
                "distance": best_dist,
                "whitelisted": bool(best.get("whitelisted", False)),
                "anonymous": bool(best.get("anonymous", False)),
                "notes": best.get("notes", ""),
            }
        return None

    def match(self, crop: np.ndarray) -> str | None:
        m = self.match_details(crop)
        return m.get("name") if m else None

    def register_crop(
        self,
        name: str,
        crop: np.ndarray,
        *,
        whitelisted: bool = False,
        notes: str = "",
        relpath: str = "",
        event_id: str = "",
        anonymous: bool | None = None,
    ):
        """Filed under `name`, creating the profile on the first crop.

        `relpath` is the picture the hash was taken from and `event_id`
        the clip it came from. Both are kept for a reason beyond showing
        a thumbnail: WITHOUT THE CLIP, THE PROFILE CANNOT BE MEASURED.
        Two crops out of the same clip are the same instant from two
        angles of the same second — testing one against the other would
        report a recognition rate that says nothing. The quality check in
        `identity_quality.py` therefore splits by clip, which it can only
        do if the clip is written down here.

        `anonymous` marks the profile as known-but-unnamed („bekannt,
        aber ohne Namensnennung"). None leaves an existing flag alone.
        """
        hashes = region_hashes(crop)
        h = hashes.get("full")
        if not h:
            return False
        profiles = self.data.setdefault("profiles", [])
        profile = next((p for p in profiles if p.get("name") == name), None)
        if profile is None:
            profile = {
                "name": name,
                "samples": [],
                "whitelisted": bool(whitelisted),
                "anonymous": bool(anonymous),
                "notes": notes,
            }
            profiles.append(profile)
        profile.setdefault("samples", [])
        profile.setdefault("whitelisted", bool(whitelisted))
        if notes:
            profile["notes"] = notes
        if anonymous is not None:
            profile["anonymous"] = bool(anonymous)
        if not any(s.get("h") == h for s in profile_samples(profile)):
            profile["samples"].insert(
                0,
                {
                    "h": h,
                    # Die übrigen Bereiche daneben, damit die Messung sie
                    # vergleichen kann, ohne jedes JPEG erneut zu öffnen.
                    "hr": {k: v for k, v in hashes.items() if k != "full"},
                    "relpath": relpath or "",
                    "event_id": event_id or "",
                },
            )
            del profile["samples"][MAX_PROFILE_SAMPLES:]
        self._save()
        return True

    def rename_profile(self, old: str, new: str) -> bool:
        """Rename — or MERGE, when `new` is already a profile.

        The merge is not a side effect, it is the point: two profiles for
        one person is the normal outcome of naming faces one at a time,
        and renaming one onto the other is how they are put back together.
        """
        new = (new or "").strip()
        source = self.get_profile(old)
        if not source or not new or new == old:
            return False
        target = self.get_profile(new)
        if target is None:
            source["name"] = new
            # Ein Profil, dem man einen echten Namen gibt, ist nicht mehr
            # das namenlose „bekannt" — das ist der natürliche Weg nach
            # oben und braucht keinen zweiten Schalter.
            source["anonymous"] = False
        else:
            known = {s["h"] for s in profile_samples(target)}
            merged = target.setdefault("samples", [])
            for s in profile_samples(source):
                if s["h"] not in known:
                    merged.append(s)
                    known.add(s["h"])
            del merged[MAX_PROFILE_SAMPLES:]
            target["whitelisted"] = bool(target.get("whitelisted")) or bool(
                source.get("whitelisted")
            )
            self.data["profiles"] = [p for p in self.list_profiles() if p is not source]
        self._save()
        return True

    def delete_profile(self, name: str) -> bool:
        """Forget a profile. The crops themselves stay on disk — they go
        back into the unnamed pile and can be filed again."""
        remaining = [p for p in self.list_profiles() if p.get("name") != name]
        if len(remaining) == len(self.list_profiles()):
            return False
        self.data["profiles"] = remaining
        self._save()
        return True


class CatRegistry(IdentityRegistry):
    pass
