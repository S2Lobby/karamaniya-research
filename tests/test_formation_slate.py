"""Government-formation proposals: a slate must be a real government, and must match its own prose.

The engine used to accept any slate whose five values were member ids, so a slate handing every
office to one delegate passed as a complete government, and a partial slate was silently dropped
and replaced by whatever individual appointments the same answer happened to carry. Nothing
compared the prose to the slate, so a proposal could read "B should be Head" while its structured
half appointed A. The vote then went ahead on whichever half the engine happened to read, and a
schema failure looked like political disagreement.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import slate as S  # noqa: E402
from karamaniya.backends import CallResult  # noqa: E402
from karamaniya.council import Council, Seat, _formation_read, _formation_repair_prompt  # noqa: E402
from karamaniya.storage import RunStore  # noqa: E402
from karamaniya.world import OFFICES, new_world  # noqa: E402

IDS = list("ABCDE")
FULL = {"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "E"}
EMPTY = {office: "" for office in OFFICES}


class TheSlateMustBeAGovernment(unittest.TestCase):
    def test_a_delegate_holding_every_office_is_not_a_government(self):
        errors = S.validate({office: "A" for office in OFFICES}, IDS)
        self.assertTrue(any("more than one office" in e for e in errors))
        self.assertEqual(sum("holds no office" in e for e in errors), 4)

    def test_one_office_to_two_delegates_is_impossible_but_a_missing_one_is_not(self):
        partial = {"head": "A", "treasury": "B", "interior": "C", "army": "", "navy": ""}
        errors = S.validate(partial, IDS)
        self.assertTrue(any("ARMY has no holder" in e for e in errors))
        self.assertTrue(any("NAVY has no holder" in e for e in errors))

    def test_a_delegate_left_out_is_named(self):
        errors = S.validate({"head": "A", "treasury": "B", "interior": "C", "army": "D", "navy": "D"}, IDS)
        self.assertTrue(any("E holds no office" in e for e in errors))

    def test_an_unknown_delegate_is_named(self):
        errors = S.validate({**FULL, "navy": "Z"}, IDS)
        self.assertTrue(any("unknown delegate 'Z'" in e for e in errors))

    def test_a_bijection_is_the_only_thing_that_passes(self):
        self.assertEqual(S.validate(FULL, IDS), [])
        self.assertEqual(S.validate({**FULL, "navy": "A"}, IDS),
                         S.validate({**FULL, "navy": "A"}, IDS))
        self.assertTrue(S.validate({**FULL, "navy": "A"}, IDS),
                        "a duplicate slipped through because the delegate count still added up")

    def test_an_all_empty_slate_is_a_refusal_not_a_malformed_government(self):
        self.assertTrue(S.is_empty(EMPTY))
        self.assertEqual(S.assess("I have no slate.", EMPTY, "A", IDS),
                         {"errors": [], "mismatches": [], "no_slate": True, "valid": True})


class TheProseMustMatchTheSlate(unittest.TestCase):
    def test_the_stated_case(self):
        found = S.mismatches("I have thought about it. B should be Head.", FULL, "C", IDS)
        self.assertTrue(found and "HEAD" in found[0] and "B" in found[0])

    def test_one_repair_prompt_carries_the_errors_and_the_rule(self):
        # The slate gives HEAD to A; the statement gives it to B.
        record = _formation_read("A", {"statement": "B should be Head. I also give B the Treasury.",
                                       "nominations": [], "slate": FULL}, IDS)
        prompt = _formation_repair_prompt("CONTEXT\n\nReply with JSON:\n{}", record, {"type": "object"})
        self.assertTrue(any("B" in problem and "HEAD" in problem for problem in record["mismatches"]),
                        "the contradiction was not read at all")
        self.assertIn("HEAD, TREASURY, INTERIOR, ARMY, NAVY", prompt)
        self.assertIn("exactly one office per delegate", prompt)
        # A repair that fixes the structure while writing that someone is left out has only moved
        # the contradiction, so the prompt says which implication of "complete" the delegate must
        # keep its prose consistent with.
        self.assertIn("nobody is left out of one", prompt)
        # The repair keeps the delegate's own context and swaps only the instruction.
        self.assertIn("CONTEXT", prompt)
        self.assertTrue(prompt.count("Reply with JSON:") == 0,
                        "the repair prompt still told the delegate to answer the original question")

    def test_rhetoric_that_merely_mentions_a_delegate_and_an_office_is_not_a_claim(self):
        """Real corpus sentences. Reading these as claims would reject a proposal that was never
        malformed, which is worse than missing a claim: the slate still has to pass the vote."""
        for statement in (
            "Delegate D's payments-and-harvest knowledge suits Treasury perfectly",
            "My border-and-civilian-trust dossier gives me direct intelligence on police treatment",
            "I will vote for any slate that keeps army, navy and police in separate hands",
            "Delegate C should not be Head under any circumstances",
            "A balanced slate matching responsibilities to demonstrated priorities",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(S.mismatches(statement, FULL, "E", IDS), [])

    def test_a_bridge_that_names_another_delegate_is_not_this_pairing(self):
        """The real sentence that caught this: it gives A the navy and C the army, and a naive
        reader took the text between A and "Army Command" as A claiming the army."""
        statement = ("Delegate A, with the shipping dossier, to Navy Command; and myself, "
                     "Delegate C, to Army Command.")
        self.assertEqual(S.mismatches(statement, {"head": "B", "treasury": "D", "interior": "E",
                                                  "army": "C", "navy": "A"}, "C", IDS), [])
        self.assertIn(("army", "C"), S.claims(statement, "C", IDS))


class ExclusionClaims(unittest.TestCase):
    """A full slate is a bijection, so it seats all five delegates: a statement that names a
    delegate as left out contradicts any structurally valid slate it is attached to. The reader
    must therefore be certain it is reading an exclusion of a *person* — the corpus is full of
    sentences that exclude policies, basing rights and naval obligations, and reading one of those
    as a claim would reject a proposal that was never malformed."""

    def test_a_delegate_the_prose_excludes_but_the_slate_seats(self):
        found = S.mismatches("Delegate D is excluded from this slate", FULL, "B", IDS)
        self.assertEqual(len(found), 1)
        self.assertIn("D is excluded", found[0])
        self.assertIn("ARMY", found[0])          # FULL seats D at the army

    def test_the_delegate_can_be_named_on_either_side_of_the_phrase(self):
        self.assertEqual(S.exclusions("This slate excludes Delegate D.", "B", IDS), ["D"])
        self.assertEqual(S.exclusions("Delegate D is left out of the government.", "B", IDS), ["D"])
        self.assertEqual(S.exclusions("There is no office for D here.", "B", IDS), ["D"])
        self.assertEqual(S.exclusions("D holds no office under this arrangement.", "B", IDS), ["D"])

    def test_a_statement_declining_on_its_own_behalf(self):
        self.assertEqual(S.exclusions("I am left out of this government.", "D", IDS), ["D"])

    def test_excluding_a_policy_is_not_excluding_a_delegate(self):
        """Three sentences of this shape occur in the run corpus. Each contains a trigger phrase
        and none of them is about a person."""
        for statement in (
            "I amended it to exclude basing and hidden naval obligations.",
            "Clarify that the trade deal shall exclude military basing and undisclosed obligations.",
            "I will vote for any slate that excludes no delegate.",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(S.exclusions(statement, "C", IDS), [])

    def test_a_delegate_explaining_its_own_repair_is_not_claiming_an_exclusion(self):
        """A repair round asks the delegate what was wrong with its last attempt, so the answer
        talks about the previous proposal. The first real repair the patch produced opened "My
        previous proposal failed to cover all delegates" — the same shape with an exclusion verb is
        one clause away, and reading it as a claim about the current slate would fail a proposal
        that had just been corrected."""
        for statement in (
            "My previous proposal excluded D from the cabinet.",
            "My original proposal omitted D entirely.",
            "The first attempt passed over D, now D holds the navy.",
            "My prior slate left D out.",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(S.exclusions(statement, "B", IDS), [])

    def test_the_real_contradiction_from_the_run_is_still_caught(self):
        """Verbatim from runs/20260930-090535-seed1: the delegate's own repair, which seats D at the
        navy one clause after saying D is excluded. The back-reference guard above must not swallow
        it — its opening sentence mentions a previous proposal, 150 characters earlier."""
        statement = ("My previous proposal failed to cover all delegates and the Head office. "
                     "Delegate A, committed against forceful rule without a mandate, should lead as "
                     "Head of Government. Delegate D is excluded from this slate; their concerns are "
                     "noted but we must fill every seat now.")
        self.assertEqual(S.exclusions(statement, "B", IDS), ["D"])
        slate = {"head": "A", "treasury": "B", "interior": "C", "army": "E", "navy": "D"}
        self.assertTrue(S.mismatches(statement, slate, "B", IDS))

    def test_a_principle_about_exclusion_is_not_a_claim_of_it(self):
        for statement in (
            "No delegate should be excluded from the council.",
            "The army must not be excluded from the budget.",
            "I do not exclude anyone from consideration.",
            "Delegate D should not be left out of the debate.",
            "Nobody is excluded; all five of us serve.",
        ):
            with self.subTest(statement=statement):
                self.assertEqual(S.exclusions(statement, "B", IDS), [])

    def test_prose_and_slate_agreeing_about_an_exclusion_is_not_a_mismatch(self):
        """A statement that excludes D is consistent with a slate that does not seat D."""
        slate = {"head": "A", "treasury": "B", "interior": "C", "army": "E", "navy": "E"}
        found = S.mismatches("Delegate D is excluded from this slate.", slate, "B", IDS)
        self.assertEqual(found, [], "a truthful exclusion was reported as a contradiction")


class TheEngineUsesIt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-slate-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, backend_factory, seed=61):
        world = new_world(seed, member_ids=IDS, founding_scenario="random")
        seats = {mid: Seat(mid, mid, {"provider": "test"}, backend_factory(mid)) for mid in IDS}
        store = RunStore(os.path.join(self.tmp, "r-" + str(len(os.listdir(self.tmp)))))
        council = Council(world, seats, {}, store)
        formation = council.form_government()
        return formation, store, world

    def test_a_malformed_slate_is_repaired_once_and_the_correction_is_what_is_voted_on(self):
        class Backend:
            def __init__(self):
                self.calls = []

            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    self.calls.append(bool(context.get("repair")))
                    if context.get("repair"):
                        return CallResult(data={"statement": "Corrected.", "nominations": [],
                                                "slate": FULL}, raw="(repair)")
                    return CallResult(data={"statement": "Everyone should serve.",
                                            "nominations": [],
                                            "slate": {office: "A" for office in OFFICES}}, raw="(bad)")
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                                        "reasons": {m["id"]: "ok" for m in context["formation_motions"]}})

        made = {}

        def factory(mid):
            made[mid] = Backend()
            return made[mid]

        formation, store, _ = self._run(factory)
        for mid in IDS:
            self.assertEqual(made[mid].calls, [False, True], "not exactly one repair was requested")
        self.assertEqual(formation["offices"], FULL)
        proposal = store.read_log("government_formation")[0]["proposals"]["A"]
        self.assertEqual(proposal["status"], "repaired")
        self.assertEqual(proposal["original"]["slate"], {office: "A" for office in OFFICES},
                         "the malformed answer was not preserved in the audit log")
        self.assertTrue(proposal["original_errors"])

    def test_a_proposal_that_still_fails_is_kept_out_of_the_vote(self):
        class Backend:
            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    return CallResult(data={"statement": "I propose nothing workable.",
                                            "nominations": [{"office": "head", "member": "A"}],
                                            "slate": {"head": "A", "treasury": "A", "interior": "",
                                                      "army": "", "navy": ""}}, raw="(bad)")
                self.voted = context["formation_motions"]
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                                        "reasons": {m["id"]: "ok" for m in context["formation_motions"]}})

        backend = Backend()
        backend.voted = None
        formation, store, _ = self._run(lambda mid: backend)
        self.assertTrue(all(p["status"] == "FORMATION_INVALID" for p in formation["proposals"].values()))
        self.assertEqual(formation["motions"], [],
                         "a malformed proposal reached the vote")
        self.assertIsNone(backend.voted, "the vote was held on an empty ballot")
        self.assertTrue(all(v is None for v in formation["offices"].values()))
        self.assertEqual(len(store.read_log("formation_no_motions")), 1)
        kept = store.read_log("government_formation")[0]["proposals"]["A"]
        self.assertEqual(kept["slate"], None, "an invalid slate was published as if it were a slate")
        self.assertTrue(kept["slate_received"], "what the delegate actually sent was discarded")

    def test_a_reply_with_nothing_in_it_is_a_failed_answer_not_an_abstention(self):
        """An empty object carries no statement, no nominations and no slate. Recording that as a
        deliberate abstention lets a schema failure pass for a political choice, and it never gets
        the repair every other malformed answer gets."""
        class Backend:
            def __init__(self):
                self.asked = 0

            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    self.asked += 1
                    if context.get("repair"):
                        return CallResult(data={"statement": "My apologies — a full slate.",
                                                "nominations": [], "slate": FULL}, raw="(repair)")
                    return CallResult(data={}, raw="")
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                                        "reasons": {m["id"]: "ok" for m in context["formation_motions"]}})

        backend = Backend()
        formation, store, _ = self._run(lambda mid: backend)
        self.assertEqual(backend.asked, 10, "an empty answer was never sent back for repair")
        self.assertEqual(formation["offices"], FULL)

    def test_declining_a_slate_on_purpose_is_still_an_abstention(self):
        """The documented way to decline: a statement and an explicitly empty slate."""
        class Backend:
            def __init__(self):
                self.asked = 0

            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    self.asked += 1
                    return CallResult(data={"statement": "I propose no slate; I will support others.",
                                            "nominations": [], "slate": EMPTY}, raw="{}")
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                                        "reasons": {m["id"]: "ok" for m in context["formation_motions"]}})

        backend = Backend()
        formation, _, _ = self._run(lambda mid: backend)
        self.assertEqual(backend.asked, 5, "a delegate who declined on purpose was sent back to repair")
        self.assertEqual(formation["proposals"]["A"]["status"], "empty")

    def test_a_valid_proposal_is_not_sent_back_for_repair(self):
        class Backend:
            def __init__(self):
                self.asked = 0

            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    self.asked += 1
                    return CallResult(data={"statement": "A balanced government for the country.",
                                            "nominations": [], "slate": FULL}, raw="{}")
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                                        "reasons": {m["id"]: "ok" for m in context["formation_motions"]}})

        backend = Backend()
        formation, store, _ = self._run(lambda mid: backend)
        self.assertEqual(backend.asked, 5, "a valid proposal was repaired anyway")
        self.assertEqual(formation["offices"], FULL)
        self.assertTrue(all(p["status"] == "valid" for p in formation["proposals"].values()))

    def test_a_statement_that_contradicts_its_own_slate_is_sent_back(self):
        class Backend:
            def complete(self, system, user, schema, context):
                if context["phase"] == "formation_proposal":
                    if context.get("repair"):
                        # The delegate settles it the other way and says so consistently.
                        return CallResult(data={"statement": "B should be Head and A should be Treasury.",
                                                "nominations": [],
                                                "slate": {**FULL, "head": "B", "treasury": "A"}}, raw="(repair)")
                    # A structurally perfect slate that its own prose contradicts.
                    return CallResult(data={"statement": "A should be Treasury and B should be Head.",
                                            "nominations": [], "slate": FULL}, raw="(mismatch)")
                return CallResult(data={"votes": {m["id"]: "yes" for m in context["formation_motions"]},
                                        "reasons": {m["id"]: "ok" for m in context["formation_motions"]}})

        formation, store, _ = self._run(lambda mid: Backend())
        proposal = formation["proposals"]["A"]
        self.assertEqual(proposal["status"], "repaired")
        self.assertIn(proposal["errors"], ([],), "the slate was structurally sound; only the prose was not")
        self.assertTrue(proposal["original_mismatches"])
        self.assertTrue(any("HEAD" in clash for clash in proposal["original_mismatches"]))
        self.assertEqual(formation["offices"], {**FULL, "head": "B", "treasury": "A"},
                         "the correction was not the thing voted on")


if __name__ == "__main__":
    unittest.main()
