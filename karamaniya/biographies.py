"""Each delegate's past (engine 18).

In run 20261010-070501-seed1 the five delegates' private opening positions were only 9-12% alike, yet 27 of 40
votes were five to nothing, and their seeded ambitions were all civic. Each delegate has since been dealt a political
agenda and a red line (agendas.py). Nothing gave a delegate a past: no regiment it brought over, no militia it
buried, no region it grew up in. A politician is partly what it lived through, so each delegate is now also dealt
one of eight pasts that fit the founding. Karamanian regiments of the imperial army and town militias held Port
Aster and the Dorran March against imperial loyalists through a winter of fighting; most Karamanians hold
independence settled, and the Imperial communities of Kessel Valley and the Dorran March mostly opposed it.

A past is a fact about the delegate: what it did, where it grew up, whom it answers to. It never says what to decide,
and the private disposition puts it beside the agenda rather than in its place. Each past names the base that put
the delegate forward (bases.py), which watches its votes.
"""
from __future__ import annotations

from .world import World, rng_for

BIOGRAPHIES = (
    {"id": "dorran_militia", "base": "veterans", "text": (
        "You commanded a town militia that held the Dorran March through the winter of independence, against imperial "
        "loyalists. Eleven of your men are buried there, and most of the families you still hear from live in the "
        "March's market towns.")},
    {"id": "imperial_officer", "base": "officers", "text": (
        "You are a Karamanian officer who served in the imperial army. When the empire broke apart you brought your "
        "regiment over to the independence side, and it held Port Aster through the winter against imperial loyalists.")},
    {"id": "imperial_ministry", "base": "civil_service", "text": (
        "You were a senior official in the old imperial ministry of finance. When the empire broke apart you stayed to "
        "keep the pay rolls, the tax registers and the ledgers running, and the new state still runs on the records "
        "you kept.")},
    {"id": "kessel_engineer", "base": "kessel_labour", "text": (
        "You are a Karamanian engineer who grew up in Kessel Valley among Imperial families, and you have worked in its "
        "coal and steel works most of your life. You were elected shop steward of your union, and most of the men you "
        "represent opposed independence that winter.")},
    {"id": "port_merchant", "base": "merchants", "text": (
        "You run a shipping and trading house in Port Aster. In the winter of independence you paid for the town militias "
        "out of your own warehouses and credit, and your ships still carry the cargo that keeps the port open.")},
    {"id": "lissen_farmer", "base": "farmers", "text": (
        "You lead the farmers' cooperative on the Lissen Coast, which sells grain and dairy through the regional markets. "
        "Your members fed the militias that winter, and their harvests have been requisitioned more than once since.")},
    {"id": "vell_teacher", "base": "vell", "text": (
        "You teach at a village school in the Vell Highlands, where most of your pupils are Vell. You chair the community "
        "council, which has asked the capital for schools, roads and a clinic, and for a fair share of the district budget.")},
    {"id": "charter_lawyer", "base": "lawyers", "text": (
        "You are a lawyer from Port Aster who sat on the drafting committee of the founding conference, which wrote the "
        "first Charter. You still know which clauses were fought over, word by word.")},
)
BY_ID = {spec["id"]: spec for spec in BIOGRAPHIES}


def deal(w: World, mid: str) -> dict | None:
    """This delegate's past: the eight biographies shuffled by the seed, one to a member, indexed by sorted member
    id, as agendas.deal does. Its own seeded stream, so no other draw moves. The base it comes from is kept with it,
    so a later change to the catalogue leaves a saved run's base as it was."""
    members = sorted(m.id for m in w.members)
    if mid not in members:
        return None
    order = list(BIOGRAPHIES)
    rng_for(w.seed, 0, "biography-deal").shuffle(order)
    spec = order[members.index(mid) % len(order)]
    return {"id": spec["id"], "base": spec["base"]}


def text(state: dict) -> str:
    """The past as the delegate reads it, in its private disposition."""
    spec = BY_ID.get((state.get("biography") or {}).get("id"))
    if not spec:
        return ""
    return f"YOUR PAST: {spec['text']}"
