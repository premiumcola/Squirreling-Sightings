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


def hamming_hex(a: str, b: str) -> int:
    # bin().count("1") rather than int.bit_count() — the latter is 3.10+
    # and the Coral image runs Python 3.9. Both operands are non-negative,
    # so the "0b" prefix contributes no "1" and there is no sign char.
    return bin(int(a, 16) ^ int(b, 16)).count("1")


#: Wie viele Ausschnitt-Verweise ein Profil mitführt. Sie sind das
#: Gesicht des Profils in der Oberfläche — der erste ist das Avatar, der
#: Rest der kleine Stapel dahinter. Mehr als eine Handvoll bringt nichts
#: und bläht die Registry auf, die sonst nur Hashes enthält.
MAX_PROFILE_CROPS = 8


class IdentityRegistry:
    def __init__(self, path: str | Path, threshold: int = 10):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.threshold = threshold
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
        self, name: str, *, whitelisted: bool | None = None, notes: str | None = None
    ):
        p = self.get_profile(name)
        if not p:
            return False
        if whitelisted is not None:
            p["whitelisted"] = bool(whitelisted)
        if notes is not None:
            p["notes"] = notes
        self._save()
        return True

    def match_details(self, crop: np.ndarray) -> dict | None:
        h = dhash_bgr(crop)
        if not h:
            return None
        best = None
        best_dist = 999
        for p in self.data.get("profiles", []):
            for sample in p.get("hashes", []):
                try:
                    d = hamming_hex(h, sample)
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
    ):
        """Filed under `name`, creating the profile on the first crop.

        `relpath` is the picture the hash was taken from. It is kept so
        the identity panel has a face to show — without it a profile is
        a name and sixteen hex digits, which is nothing to recognise a
        person by.
        """
        h = dhash_bgr(crop)
        if not h:
            return False
        profiles = self.data.setdefault("profiles", [])
        profile = next((p for p in profiles if p.get("name") == name), None)
        if profile is None:
            profile = {"name": name, "hashes": [], "whitelisted": bool(whitelisted), "notes": notes}
            profiles.append(profile)
        profile.setdefault("hashes", [])
        profile.setdefault("whitelisted", bool(whitelisted))
        if notes:
            profile["notes"] = notes
        if h not in profile["hashes"]:
            profile["hashes"].append(h)
        if relpath:
            crops = profile.setdefault("crops", [])
            if relpath in crops:
                crops.remove(relpath)
            crops.insert(0, relpath)
            del crops[MAX_PROFILE_CROPS:]
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
        else:
            for h in source.get("hashes", []):
                if h not in target.setdefault("hashes", []):
                    target["hashes"].append(h)
            crops = target.setdefault("crops", [])
            for relpath in source.get("crops", []):
                if relpath not in crops:
                    crops.append(relpath)
            del crops[MAX_PROFILE_CROPS:]
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
