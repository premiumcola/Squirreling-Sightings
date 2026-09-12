"""Wie gut ein Personenprofil schon erkennt — gemessen, nicht geschätzt.

„Wie kannst Du aus den zugeordneten Sachen dann irgendwie errechnen, wie
gut das Profil schon ist? Vielleicht das Halbieren, die Menge, und die
eine Menge mit der anderen erkennen und sagen, wie gut Du's schon
erkennst."

Genau so. Die Proben eines Profils werden in zwei Hälften geteilt, die
eine dient als Gedächtnis, die andere wird vorgelegt, als hätte man sie
nie gesehen — und dann wird gezählt, wie oft die richtige Person
herauskommt. Was dabei zu beachten ist, steht unten; es sind drei Dinge,
und wer eines davon weglässt, bekommt eine schöne Zahl, die nichts
bedeutet.

GETEILT WIRD NACH CLIP, NICHT NACH PROBE. Zwei Ausschnitte aus demselben
Clip sind derselbe Mensch in derselben Sekunde, in derselben Jacke, am
selben Fleck. Den einen mit dem anderen wiederzuerkennen ist keine
Leistung — eine Aufteilung, die sie auf beide Hälften verteilt, meldet
fast 100 % und misst nichts als sich selbst. Getrennt wird deshalb nach
Clip: die Prüfhälfte enthält nur Auftritte, die das Gedächtnis nie
gesehen hat.

GEPRÜFT WIRD GEGEN ALLE, NICHT NUR GEGEN SICH SELBST. „Erkennt das
Profil seine eigenen Bilder wieder" ist die halbe Frage. Die andere
Hälfte ist, ob es sie NUR wiedererkennt — ein Profil, das auf jeden
zeigt, hat eine Trefferquote von 100 % und ist wertlos. Also wird jede
vorgelegte Probe gegen die Gedächtnishälften ALLER Profile gehalten, und
ein Treffer zählt nur, wenn der nächste Nachbar auch wirklich der eigene
ist. Verwechslungen werden getrennt gezählt und ausgewiesen.

WAS HIER GEMESSEN WIRD, IST NICHT DAS GESICHT. Der Vergleich ist ein
dHash über den GANZEN Personen-Ausschnitt — das Rechteck, das der
Detektor um den Menschen gelegt hat, vom Kopf bis zu den Schuhen. Also
Silhouette, Kleidung, Haltung, Hintergrund, Tageslicht. Dieselbe Person
in einer anderen Jacke ist für dieses Verfahren eine andere; zwei
Personen in derselben Arbeitskleidung an derselben Stelle sind dieselbe.
Die Zahl, die hier herauskommt, ist deshalb ehrlicherweise „wie
zuverlässig erkenne ich diesen Auftritt wieder", nicht „wie zuverlässig
erkenne ich diesen Menschen". Sie steigt vor allem dadurch, dass man
Ausschnitte von VERSCHIEDENEN Tagen zuordnet.
"""

from __future__ import annotations

from .cat_identity import hamming_hex, profile_samples

#: Wie viele Proben je Profil höchstens ins Gedächtnis bzw. in die
#: Prüfung gehen. Die Auswertung ist ein Alle-gegen-alle-Vergleich; ohne
#: Deckel wächst sie quadratisch und eine Antwort auf einen Tastendruck
#: wird zu einer Kaffeepause. Die Deckel sind großzügig genug, dass die
#: Quote sich davon praktisch nicht mehr bewegt.
MAX_MEMORY = 120
MAX_PROBE = 40

#: Unter so vielen Clips gibt es nichts zu messen — mit einem einzigen
#: Auftritt lässt sich nicht prüfen, ob ein zweiter wiedererkannt würde.
MIN_EVENTS = 2


def _events_of(samples: list[dict]) -> list[str]:
    """Die Clips, aus denen die Proben stammen, in stabiler Reihenfolge.

    Proben ohne Clip (Altbestand vor 2026-09-13) bekommen keinen eigenen
    Topf — sie landen unter "" und gelten damit als EIN Auftritt, was
    der vorsichtigen Lesart entspricht: sie könnten alle aus demselben
    stammen.
    """
    seen: list[str] = []
    for s in samples:
        eid = s.get("event_id") or ""
        if eid not in seen:
            seen.append(eid)
    return seen


def split_by_event(samples: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(Gedächtnis, Prüfung)`` — halbiert nach CLIP, nicht nach Probe.

    Abwechselnd verteilt statt vorne/hinten geschnitten: die Clips sind
    nach Zeit sortiert, und ein glatter Schnitt legte alle alten Auftritte
    ins Gedächtnis und alle neuen in die Prüfung. Dann misst man den
    Kleiderwechsel zwischen erster und zweiter Hälfte, nicht das Profil.
    """
    events = _events_of(samples)
    if len(events) < MIN_EVENTS:
        return list(samples)[:MAX_MEMORY], []
    memory_events = {e for i, e in enumerate(events) if i % 2 == 0}
    memory, probe = [], []
    for s in samples:
        (memory if (s.get("event_id") or "") in memory_events else probe).append(s)
    return memory[:MAX_MEMORY], probe[:MAX_PROBE]


def _nearest(h: str, memories: dict) -> tuple[str | None, int]:
    """``(Name, Abstand)`` des nächsten Nachbarn über alle Gedächtnisse."""
    best_name, best = None, 999
    for name, hashes in memories.items():
        for other in hashes:
            try:
                d = hamming_hex(h, other)
            except Exception:
                continue
            if d < best:
                best, best_name = d, name
    return best_name, best


def evaluate(profiles: list[dict], threshold: int) -> dict:
    """Je Profil eine Trefferquote, plus eine Gesamtbilanz.

    ``{"profiles": {name: {...}}, "total": {...}}``. Ein Profil, das noch
    nicht geprüft werden kann, bekommt ``state: "zu-wenig"`` und keine
    Quote — eine erfundene 0 % wäre schlimmer als keine Zahl.
    """
    split = {}
    for p in profiles or []:
        name = p.get("name") or ""
        if not name:
            continue
        split[name] = split_by_event(profile_samples(p))
    memories = {name: [s["h"] for s in mem] for name, (mem, _) in split.items()}

    per: dict = {}
    hits = checked = confused = 0
    for name, (mem, probe) in split.items():
        if not probe:
            per[name] = {
                "state": "zu-wenig",
                "events": len(_events_of(mem)),
                "samples": len(mem),
            }
            continue
        own = wrong = 0
        for s in probe:
            who, dist = _nearest(s["h"], memories)
            if dist > threshold:
                continue  # nicht wiedererkannt — weder Treffer noch Verwechslung
            if who == name:
                own += 1
            else:
                wrong += 1
        per[name] = {
            "state": "gemessen",
            "checked": len(probe),
            "hits": own,
            "confused": wrong,
            "rate": round(own / len(probe), 3),
            "events": len(_events_of(mem)) + len(_events_of(probe)),
            "samples": len(mem) + len(probe),
        }
        hits += own
        confused += wrong
        checked += len(probe)

    total = {
        "checked": checked,
        "hits": hits,
        "confused": confused,
        "rate": round(hits / checked, 3) if checked else None,
    }
    return {"profiles": per, "total": total}
