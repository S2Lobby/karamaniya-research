"""Place names drawn from the seed (engine 13; run setting world_names = "seeded").

The scenario is public, so a model may have read about Karamaniya before it is asked to govern it, and
names carry associations of their own: "the Union" reads as an echo of a real one. With seeded names,
every text a model sees calls the island, the three countries, the bloc, the League, the regions, the
minority and the currency by names drawn from the run's seed.

Nothing else changes. The engine, the run's records, the report and the control room keep the canonical
names; the translation happens only where a model is asked something (Council._call and the foreign
cabinets' calls): outbound on the system prompt, the prompt and the answer's schema, and back on the answer,
keys and values alike, so a seeded name a model writes is the canonical one the engine reads. The prompts
are logged exactly as they were sent, and the run keeps its table (names.json) so a reader can map one to
the other.

A name matches as a word: letters on either side stop it (Aster is not translated inside "disaster"), while
underscores and digits do not, so the ids inside setting names and belief ids are translated too
(kessel_status, union_attack_soon) and come back whole. Generic words are left alone: highlands, league,
imperial and crown name kinds of thing, not this place.
"""
from __future__ import annotations

import json
import re

from .world import rng_for

MODES = ("fixed", "seeded")

# Invented names, chosen not to be English words or well-known places; a seed draws from each list.
COUNTRIES = [("Ostravia", "Ostravian"), ("Brennovia", "Brennovian"), ("Valdoria", "Valdorian"),
             ("Tarvelia", "Tarvelian"), ("Morvania", "Morvanian"), ("Quessaria", "Quessarian"),
             ("Zarovia", "Zarovian"), ("Ilvaria", "Ilvarian"), ("Drevania", "Drevanian"),
             ("Kastrelia", "Kastrelian"), ("Velmoria", "Velmorian"), ("Halvoria", "Halvorian"),
             ("Mirvelia", "Mirvelian"), ("Lusvaria", "Lusvarian"), ("Nerevia", "Nerevian"),
             ("Rovania", "Rovanian"), ("Stavrenia", "Stavrenian"), ("Ulvaria", "Ulvarian"),
             ("Gredania", "Gredanian"), ("Torvania", "Torvanian"), ("Pravelia", "Pravelian"),
             ("Zhelania", "Zhelanian"), ("Krovania", "Krovanian"), ("Askaria", "Askarian")]
ISLANDS = [("Merova", "Merovan"), ("Tessara", "Tessaran"), ("Calvera", "Calveran"), ("Orvessa", "Orvessan"),
           ("Branova", "Branovan"), ("Ilsara", "Ilsaran"), ("Dunvara", "Dunvaran"), ("Kelvara", "Kelvaran")]
# The bloc's stand-in is translated back wherever a model writes it, prose included, so it must be a word
# no model would use for anything else: "pact" or "accord" would turn a non-aggression pact into a union.
BLOCS = ["Concordat", "Federacy", "Conclave", "Sodality"]
# The League's adjective is only ever translated with "League" after it.
LEAGUES = ["Coral", "Azure", "Tidewater", "Seaboard", "Windward", "Saltwater"]
REGIONS = ["Brannock", "Dunmere", "Halvic", "Oskeld", "Corrow", "Elstan", "Gorran", "Hesketh", "Ivett", "Jorvel",
           "Kilmar", "Mabry", "Norrin", "Pellam", "Rendel", "Tavish", "Ulden", "Varro", "Wendel", "Ardric",
           "Belvane", "Caddor", "Droval", "Essick", "Garvel", "Hollin", "Kerrow", "Lothar", "Morrin", "Starn"]
CANONICAL_REGIONS = ("Kessel", "Aster", "Lissen", "Vell", "Dorran", "Arven", "Tolmar", "Irongate", "Belcor",
                     "Goldfield")


def draw(seed: int) -> dict:
    """The seed's names: each canonical name (as written in Title case) -> its stand-in."""
    rng = rng_for(seed, 0, "world-names")
    countries = rng.sample(COUNTRIES, 3)
    island = rng.choice(ISLANDS)
    regions = rng.sample(REGIONS, len(CANONICAL_REGIONS))
    names = {}
    for (canon, adjectives), (name, adj) in zip((("Karamaniya", ("Karamanian", "Karamaniyan")),
                                                ("Veleria", ("Velerian",)), ("Dorsania", ("Dorsanian",))),
                                               countries):
        names[canon] = name
        for a in adjectives:
            names[a] = adj
            names[a + "s"] = adj + "s"
    names["Solvara"], names["Solvaran"] = island
    names["Union"] = rng.choice(BLOCS)
    names["Maritime League"] = rng.choice(LEAGUES) + " League"
    for canon, name in zip(CANONICAL_REGIONS, regions):
        names[canon] = name
    names["Vellmark"] = names["Vell"] + "mark"
    # The currency is named after the country, as the karam is after Karamaniya.
    names["karam"] = names["Karamaniya"][:5].lower()
    # A plural is a word of its own to the matcher (a letter follows the name), and models write amounts
    # in the plural: "500 karams" has to come back as karams for the amount to be read.
    names["karams"] = names["karam"] + "s"
    return names


def forms(names: dict) -> dict:
    """Every written form a name takes: as given, lower case (ids) and upper case (headings)."""
    out = {}
    for canon, seeded in names.items():
        out[canon] = seeded
        out[canon.lower()] = seeded.lower()
        out[canon.upper()] = seeded.upper()
        if canon.islower():                      # the currency is written "Karam" at a sentence start
            out[canon.capitalize()] = seeded.capitalize()
    return out


def _pattern(words) -> re.Pattern:
    alternatives = "|".join(re.escape(x) for x in sorted(words, key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z])(" + alternatives + r")(?![A-Za-z])")


class Names:
    """Canonical <-> seeded, for texts and for JSON-like values (dict keys included)."""

    def __init__(self, names: dict):
        self.names = dict(names)
        self.out_map = forms(names)
        # Two spellings share one stand-in (Karamanian and Karamaniyan); the first is the one that comes
        # back, so the identity id karamanian is always returned as it is written in the engine.
        self.back_map = {}
        for canon, seeded in self.out_map.items():
            self.back_map.setdefault(seeded, canon)
        self._out = _pattern(self.out_map)
        self._back = _pattern(self.back_map)

    def out(self, text: str) -> str:
        return self._out.sub(lambda m: self.out_map[m.group(1)], text) if isinstance(text, str) else text

    def back(self, text: str) -> str:
        return self._back.sub(lambda m: self.back_map[m.group(1)], text) if isinstance(text, str) else text

    def _walk(self, value, fn):
        if isinstance(value, str):
            return fn(value)
        if isinstance(value, dict):
            return {fn(k) if isinstance(k, str) else k: self._walk(v, fn) for k, v in value.items()}
        if isinstance(value, list):
            return [self._walk(v, fn) for v in value]
        if isinstance(value, tuple):
            return tuple(self._walk(v, fn) for v in value)
        return value

    def out_obj(self, value):
        return self._walk(value, self.out)

    def back_obj(self, value):
        return self._walk(value, self.back)


def for_run(seed: int, mode: str) -> Names | None:
    """The translator a run uses, or None for the canonical names."""
    return Names(draw(seed)) if mode == "seeded" else None


def legend(names: dict) -> list:
    """canonical, seeded pairs for a reader, the places first."""
    order = ["Karamaniya", "Veleria", "Dorsania", "Solvara", "Union", "Maritime League", *CANONICAL_REGIONS, "karam"]
    return [[k, names[k]] for k in order if k in names]


def save(store, names: Names) -> None:
    store._write_json("names.json", {"mode": "seeded", "names": names.names, "legend": legend(names.names)})


def load(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
