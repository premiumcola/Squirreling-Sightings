"""Kein relativer Import darf über die Paketwurzel hinausklettern.

Ein `from ....x import y` in einem dreistufigen Paket ist keine Stilfrage
und kein Grenzfall — es ist immer ein ``ImportError``. Python zählt einen
Punkt für das eigene Paket und je einen weiteren nach oben; sind die
Punkte alle, gibt es nichts mehr zu verlassen.

Warum das hier einen eigenen Wächter bekommt: Der Fehler ist unsichtbar,
wenn der Import in einem ``try``-Block mit ``log.debug`` steht. Genau so
lag er in ``camera_runtime/_recording/_publish.py`` — drei Importe, alle
eine Ebene zu tief, alle abgefangen und weggeloggt. Die Folge waren drei
Funktionen, die seit ihrer Einführung **nie** gelaufen sind: der Marker
für Erstsichtungen, die Quest-Neubewertung nach jedem Ereignis und das
Anlegen der Vogelsteckbriefe. Kein Absturz, keine Fehlermeldung, nur
Stille.

``scripts/check_import_graph.py`` fängt das nicht: es prüft ausschließlich
JavaScript, wie sein eigener Docstring sagt. Und ein Test, der die Module
nur importiert, fängt es ebenfalls nicht, weil ein Import im
Funktionsrumpf erst beim Aufruf ausgeführt wird. Deshalb statisch über den
Syntaxbaum, der auch in Funktionen hineinsieht.
"""

from __future__ import annotations

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"


def _package_depth(path: Path) -> int:
    """Wie viele Punkte dieses Modul höchstens tragen darf.

    Ein Modul ``app/camera_runtime/_recording/_publish.py`` sitzt im Paket
    ``app.camera_runtime._recording``. Ein Punkt meint dieses Paket, jeder
    weitere eine Ebene darüber — bei ``app`` ist Schluss. Also: Anzahl der
    Paketebenen unter (und einschließlich) ``app``.
    """
    rel = path.relative_to(_APP.parent)
    # rel == app/camera_runtime/_recording/_publish.py → 3 Ebenen
    parts = rel.parts[:-1]
    if path.name == "__init__.py":
        # Ein __init__ IST sein Paket, nicht ein Modul darin.
        return len(parts)
    return len(parts)


def test_no_relative_import_climbs_past_the_package_root():
    offenders: list[str] = []
    for path in sorted(_APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as err:  # pragma: no cover - wäre ein eigener Fehler
            offenders.append(f"{path}: nicht parsebar ({err})")
            continue
        allowed = _package_depth(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            if node.level > allowed:
                target = node.module or "<paket>"
                offenders.append(
                    f"{path.relative_to(_APP.parent)}:{node.lineno} "
                    f"'from {'.' * node.level}{target}' — {node.level} Punkte, "
                    f"höchstens {allowed} möglich"
                )
    assert not offenders, "relative Importe über der Paketwurzel:\n  " + "\n  ".join(offenders)
