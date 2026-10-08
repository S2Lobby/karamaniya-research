"""One-off diagnostic: founding fiscal/unrest paths."""
from karamaniya.world import new_world
from karamaniya import director, engine


def run(w, months, each=None):
    original = director.act
    director.act = lambda world, *_a, **_k: setattr(world.dip, "inbox", [])
    try:
        for _ in range(months):
            if w.ended():
                break
            engine.begin_month(w)
            if each:
                each(w)
            engine.step(w)
    finally:
        director.act = original
    return w


def snap(label, w):
    e = w.econ
    unpaid = e.spending * (1 - e.paid_share)
    print(
        f"{label}: m={w.month} gdp={e.gdp_real/1e6:.1f}M nom={e.gdp_nominal/1e6:.1f}M "
        f"rev={e.revenue/1e6:.1f} spend={e.spending/1e6:.1f} def={e.deficit/1e6:.1f} "
        f"unpaid={unpaid/1e6:.1f} arr={e.arrears/1e6:.1f} gold={e.gold/1e6:.1f} "
        f"conf={e.confidence:.2f} comp={e.compliance:.2f} paid={e.paid_share:.2f} "
        f"unrest={w.avg('unrest'):.3f} appr={w.avg('approval'):.3f} gr={w.avg('grievance'):.3f} "
        f"hung={w.avg('hunger'):.3f} u={e.unemployment:.3f} food={e.food_ratio:.2f} "
        f"int={e.interest_dom/1e6:.1f}+{e.interest_for/1e6:.1f} prem={e.procurement_premium:.3f} "
        f"admin={e.admin_capacity:.2f} tax={w.policy.tax:.2f}"
    )


def consol(x):
    x.policy.tax = 0.28
    x.policy.welfare = 0.030
    x.policy.health_edu = 0.050
    x.policy.military = 0.025


def social(x):
    x.policy.tax = 0.28
    x.policy.welfare = 0.055
    x.policy.health_edu = 0.070


for scenario in ("random", "fiscal-inheritance"):
    for seed in (1, 7, 41):
        w = new_world(seed, 18, founding_scenario=scenario)
        problems = [p["id"] for p in (w.founding or {}).get("problems", [])]
        print(
            f"FOUNDING {scenario} seed{seed} tax={w.policy.tax} arr={w.econ.arrears/1e6:.1f} "
            f"gold={w.econ.gold/1e6:.1f} unrest={w.avg('unrest'):.3f} problems={problems}"
        )
        run(w, 7)
        snap(f"{scenario} seed{seed} m7", w)

w = new_world(1, 24, founding_scenario="fiscal-inheritance")
run(w, 12, each=consol)
snap("consol fiscal-inh m12", w)

w = new_world(1, 24, founding_scenario="fiscal-inheritance")
run(w, 12, each=social)
snap("tax+welfare fiscal-inh m12", w)

w = new_world(1, 24, founding_scenario="fiscal-inheritance")
run(w, 12)
snap("passive fiscal-inh m12", w)

w = new_world(1, 24, founding_scenario="fiscal-inheritance")
run(w, 7)
snap("pre-consol m7", w)
run(w, 8, each=consol)
snap("late consol m15", w)
