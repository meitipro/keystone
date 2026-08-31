"""
End-to-end tests. The real contract file, executed.

tests/test_logic.py covers the pure rules. This file covers everything they
cannot reach: the accumulating graph, the cycle refusal, the two-pass block,
the authority rules, and every branch that only fires when the leader and a
validator see different things.

It runs on tests/glsim.py, a small GenVM stand-in, so it needs no Studio and no
network:

    pytest tests/test_e2e.py -v

The important property is that the leader and the validator get their own
independent mock answers. Every mocking framework feeds both nodes the same
data by default, which is exactly why a contract that quietly assumes both
nodes see identical bytes passes its suite and fails on a real network.
"""

import ast
import pathlib

import pytest

import glsim as S

CONTRACT_PATH = "contracts/keystone.py"

TITLE = "Database cutover, March"

FREEZE = "Freeze writes to the primary database and drain the queue."
MIGRATE = "Run the schema migration against the primary database."
REPLICA = "Repoint the read replicas at the migrated primary."
CHANGELOG = "Publish the changelog entry describing the new schema."


def pair(forward, reverse, because="one cannot start until the other is done"):
    """Mock both presentation orders of one pair.

    The two prompts differ only in which step sits in the first_step block, so the
    mock keys on the text that opens it. Writing them as two separate
    entries is the point: a test that fed both passes the same answer would
    never exercise the mirror, and the mirror is the whole mechanism.
    """
    return {
        "<first_step>\n" + forward[0]: {"order": forward[1], "because": because},
        "<first_step>\n" + reverse[0]: {"order": reverse[1], "because": because},
    }


def stable(step_a, step_b, winner):
    """The common case: a dependency that survives both presentation orders."""
    if winner == "a":
        return pair((step_a, "first"), (step_b, "second"))
    if winner == "b":
        return pair((step_a, "second"), (step_b, "first"))
    return pair((step_a, "neither"), (step_b, "neither"))


class TestKeystone:
    REGISTRAR = "0x" + "11" * 20
    AGENT = "0x" + "77" * 20
    STRANGER = "0x" + "99" * 20

    def deploy(self, *steps):
        c = S.deploy(CONTRACT_PATH)
        S.call(c, "plan", TITLE)
        for s in steps:
            S.call(c, "add", 0, s)
        return c

    def mocks(self, prompts, v_prompts=None):
        S.set_mocks(leader_pages={}, leader_prompts=prompts,
                    validator_pages={},
                    validator_prompts=v_prompts if v_prompts is not None else prompts)

    # -- the plan -----------------------------------------------------------

    def test_a_plan_opens_and_takes_steps(self):
        c = self.deploy(FREEZE, MIGRATE)
        assert c.step_count(0) == 2
        assert c.step(0, 0)["text"] == FREEZE
        assert c.overview(0)["title"] == TITLE

    def test_an_unordered_plan_is_one_layer(self):
        """Nothing has been decided, so nothing blocks anything. A contract
        that guessed an order here would be inventing dependencies."""
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        assert c.sequence(0) == "0,1,2"
        assert c.overview(0)["pairs_decided"] == 0

    # -- one pair at a time -------------------------------------------------

    def test_a_dependency_that_survives_both_orders_is_stored(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        assert c.sequence(0) == "0|1"
        assert c.blocked_by(0, 1) == "0"
        assert c.edges_of(0)["pairs"][0]["outcome"] == "before"

    def test_the_direction_is_recorded_not_the_argument_order(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "b"))
        S.call(c, "order", 0, 0, 1)
        assert c.sequence(0) == "1|0"
        assert c.blocked_by(0, 0) == "1"
        assert c.edges_of(0)["pairs"][0]["outcome"] == "after"

    def test_unrelated_steps_stay_in_the_same_layer(self):
        c = self.deploy(FREEZE, CHANGELOG)
        self.mocks(stable(FREEZE, CHANGELOG, "neither"))
        S.call(c, "order", 0, 0, 1)
        assert c.sequence(0) == "0,1"
        assert c.edges_of(0)["pairs"][0]["outcome"] == "unrelated"
        assert c.edges_of(0)["pairs"][0]["live"] is False

    def test_a_pair_is_only_decided_once(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        with pytest.raises(S.UserError, match="already been decided"):
            S.call(c, "order", 0, 0, 1)

    def test_the_same_pair_the_other_way_round_is_the_same_pair(self):
        """Otherwise a caller could ask twice and keep whichever answer suited
        them, which would make the graph a matter of who asked last."""
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        with pytest.raises(S.UserError, match="already been decided"):
            S.call(c, "order", 0, 1, 0)

    # -- position bias, caught inside the leader ----------------------------

    def test_a_step_that_always_wins_from_the_front_settles_to_neither(self):
        """Position bias is invisible to consensus on its own: every validator
        builds the prompt the same way and leans the same way, so five nodes
        agree confidently on an artefact of ordering. Two presentation orders
        inside one block is the only place it can be caught, and the
        uncertainty lands in the STORED value rather than in a tolerance."""
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(pair((FREEZE, "first"), (MIGRATE, "first")))
        S.call(c, "order", 0, 0, 1)
        assert c.edges_of(0)["pairs"][0]["outcome"] == "unrelated"
        assert c.sequence(0) == "0,1"

    def test_one_pass_finding_a_dependency_and_one_not_is_not_a_dependency(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(pair((FREEZE, "first"), (MIGRATE, "neither")))
        S.call(c, "order", 0, 0, 1)
        assert c.edges_of(0)["pairs"][0]["outcome"] == "unrelated"

    def test_a_garbage_answer_is_not_read_as_neither_by_accident(self):
        """It settles to `neither` because settle() refuses it, not because the
        parser guessed. The distinction matters: a parser that read rubbish as
        a real answer would store an invented dependency."""
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(pair((FREEZE, "banana"), (MIGRATE, "second")))
        S.call(c, "order", 0, 0, 1)
        assert c.edges_of(0)["pairs"][0]["outcome"] == "unrelated"

    def test_both_passes_saying_neither_is_a_real_answer(self):
        c = self.deploy(FREEZE, CHANGELOG)
        self.mocks(pair((FREEZE, "neither"), (CHANGELOG, "neither")))
        S.call(c, "order", 0, 0, 1)
        assert c.overview(0)["unrelated"] == 1

    # -- the cycle: the half no model is involved in ------------------------

    def test_the_third_edge_that_closes_a_loop_is_refused(self):
        """Every edge here was agreed by the network. Together they are not an
        ordering, and no single answer was wrong. This is the finding the whole
        contract exists to produce."""
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        self.mocks(stable(MIGRATE, REPLICA, "a"))
        S.call(c, "order", 0, 1, 2)
        self.mocks(stable(REPLICA, FREEZE, "a"))
        S.call(c, "order", 0, 2, 0)

        rows = c.edges_of(0)["pairs"]
        assert rows[2]["outcome"] == "cycle"
        assert rows[2]["live"] is False
        assert c.overview(0)["cycles_refused"] == 1
        # the plan still orders, on the two edges that survived
        assert c.sequence(0) == "0|1|2"

    def test_a_refused_edge_does_not_constrain_the_layering(self):
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        for a, b, first in ((0, 1, FREEZE), (1, 2, MIGRATE)):
            self.mocks(stable(first, (MIGRATE if a == 0 else REPLICA), "a"))
            S.call(c, "order", 0, a, b)
        self.mocks(stable(REPLICA, FREEZE, "a"))
        S.call(c, "order", 0, 2, 0)
        assert c.blocked_by(0, 0) == ""

    def test_the_immediate_reverse_of_a_stored_edge_is_a_cycle(self):
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        # a fresh pair that happens to point back the other way
        self.mocks(stable(MIGRATE, REPLICA, "a"))
        S.call(c, "order", 0, 1, 2)
        self.mocks(stable(FREEZE, REPLICA, "b"))     # replica before freeze
        S.call(c, "order", 0, 0, 2)
        assert c.edges_of(0)["pairs"][2]["outcome"] == "cycle"

    def test_an_edge_that_only_shortens_a_path_is_kept(self):
        """a before c is already implied by a before b before c. Storing it
        again is redundant, not contradictory, and a contract that refused it
        would be treating redundancy as a conflict."""
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        self.mocks(stable(MIGRATE, REPLICA, "a"))
        S.call(c, "order", 0, 1, 2)
        self.mocks(stable(FREEZE, REPLICA, "a"))
        S.call(c, "order", 0, 0, 2)
        assert c.edges_of(0)["pairs"][2]["outcome"] == "before"
        assert c.sequence(0) == "0|1|2"

    def test_a_plan_can_be_partly_parallel(self):
        """A total order would be a lie about a plan that genuinely is not
        one."""
        c = self.deploy(FREEZE, MIGRATE, REPLICA, CHANGELOG)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        self.mocks(stable(FREEZE, REPLICA, "a"))
        S.call(c, "order", 0, 0, 2)
        self.mocks(stable(MIGRATE, CHANGELOG, "a"))
        S.call(c, "order", 0, 1, 3)
        self.mocks(stable(REPLICA, CHANGELOG, "a"))
        S.call(c, "order", 0, 2, 3)
        assert c.sequence(0) == "0|1,2|3"
        assert c.overview(0)["layers"] == 3

    # -- consensus ----------------------------------------------------------

    def test_nodes_ordering_a_pair_opposite_ways_do_not_agree(self):
        """Recording 'these two are related' would be worse than recording
        nothing, so this must fail rather than settle."""
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"),
                   v_prompts=stable(FREEZE, MIGRATE, "b"))
        with pytest.raises(S.UserError):
            S.call(c, "order", 0, 0, 1)
        assert c.edges_of(0)["pairs"] == []

    def test_neither_against_a_dependency_is_a_disagreement(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"),
                   v_prompts=stable(FREEZE, MIGRATE, "neither"))
        with pytest.raises(S.UserError):
            S.call(c, "order", 0, 0, 1)

    def test_two_nodes_that_both_reach_neither_have_agreed(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(pair((FREEZE, "first"), (MIGRATE, "first")),
                   v_prompts=pair((FREEZE, "second"), (MIGRATE, "second")))
        S.call(c, "order", 0, 0, 1)
        assert c.edges_of(0)["pairs"][0]["outcome"] == "unrelated"

    def test_nothing_is_written_when_a_pair_fails(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"),
                   v_prompts=stable(FREEZE, MIGRATE, "b"))
        with pytest.raises(S.UserError):
            S.call(c, "order", 0, 0, 1)
        assert c.overview(0)["pairs_decided"] == 0
        # and the pair is still open, because nothing was recorded
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        assert c.sequence(0) == "0|1"

    # -- a leader that does not play by its own rules ------------------------
    #
    # What reaches a validator is whatever the leader put on the wire, and that
    # need not be anything the leader's own code could produce: a patched node,
    # a different build, a deliberate lie. Every shape check in validator_fn
    # exists for this case and no other.

    def test_a_leader_answering_a_different_pair_is_rejected(self):
        """Without the pair check a leader could answer an easy pair and have
        it recorded against a hard one."""
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.set_leader_payload({"token": "first", "a": "0", "b": "2", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "order", 0, 0, 1)
        finally:
            S.set_leader_payload(None)
        assert c.edges_of(0)["pairs"] == []

    def test_a_leader_sending_an_invented_token_is_rejected(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.set_leader_payload({"token": "before", "a": "0", "b": "1", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "order", 0, 0, 1)
        finally:
            S.set_leader_payload(None)

    def test_a_leader_sending_a_non_numeric_pair_is_rejected(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.set_leader_payload({"token": "first", "a": "zero", "b": "1", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "order", 0, 0, 1)
        finally:
            S.set_leader_payload(None)

    def test_the_free_layer_is_actually_free(self):
        """Layer 1 rejects a malformed proposal BEFORE the validator spends two
        prompts on it. Remove it and the contract still refuses, because the
        agreement rule normalises the token too, so the only difference the
        removal makes is the cost -- and the cost IS what layer 1 is for."""
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.set_leader_payload({"token": "nonsense", "a": "0", "b": "1", "because": "x"})
        try:
            with pytest.raises(S.UserError):
                S.call(c, "order", 0, 0, 1)
        finally:
            S.set_leader_payload(None)
        assert S.validator_prompt_calls() == 0

        # for contrast: a well formed proposal it disagrees with DOES cost the
        # validator both prompts, because there is no way to know without asking
        self.mocks(stable(FREEZE, MIGRATE, "a"),
                   v_prompts=stable(FREEZE, MIGRATE, "b"))
        with pytest.raises(S.UserError):
            S.call(c, "order", 0, 0, 1)
        assert S.validator_prompt_calls() == 2

    # -- authority ----------------------------------------------------------

    def test_a_stranger_cannot_add_steps_to_someone_elses_plan(self):
        """A planted step enters every later pairwise question, takes a
        position in the published layering, and is read as part of somebody
        else's plan."""
        c = self.deploy(FREEZE)
        S.set_sender(self.STRANGER)
        try:
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "add", 0, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.step_count(0) == 1

    def test_holding_a_plan_grants_nothing_over_another_one(self):
        c = self.deploy(FREEZE)
        S.set_sender(self.STRANGER)
        try:
            S.call(c, "plan", "Impostor plan")
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "add", 0, MIGRATE)
            S.call(c, "add", 1, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.step_count(0) == 1 and c.step_count(1) == 1

    def test_a_delegate_may_add_and_the_record_names_them(self):
        c = self.deploy(FREEZE)
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            S.call(c, "add", 0, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.step(0, 1)["by"].lower() == self.AGENT
        assert c.registrar(0).lower() == self.REGISTRAR

    def test_a_revoked_delegate_cannot_add(self):
        c = self.deploy(FREEZE)
        S.call(c, "authorise", 0, self.AGENT)
        S.call(c, "revoke", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "add", 0, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)

    def test_revoking_does_not_erase_what_was_already_added(self):
        c = self.deploy(FREEZE)
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            S.call(c, "add", 0, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)
        S.call(c, "revoke", 0, self.AGENT)
        assert c.step(0, 1)["text"] == MIGRATE
        assert c.step(0, 1)["by"].lower() == self.AGENT

    def test_only_the_registrar_may_authorise_revoke_or_seal(self):
        c = self.deploy(FREEZE)
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.STRANGER)
        try:
            for call, args in (("authorise", (0, self.STRANGER)),
                               ("revoke", (0, self.AGENT)),
                               ("seal", (0,))):
                with pytest.raises(S.UserError, match="registrar"):
                    S.call(c, call, *args)
        finally:
            S.set_sender(self.REGISTRAR)

    def test_a_delegate_may_not_authorise_revoke_or_seal(self):
        """A delegate writes into the plan. It does not own it, and a delegate
        able to revoke could remove every other delegate and become the only
        voice on a plan it does not own."""
        c = self.deploy(FREEZE)
        other = "0x" + "55" * 20
        S.call(c, "authorise", 0, self.AGENT)
        S.call(c, "authorise", 0, other)
        S.set_sender(self.AGENT)
        try:
            for call, args in (("authorise", (0, self.STRANGER)),
                               ("revoke", (0, other)),
                               ("revoke", (0, self.AGENT)),
                               ("seal", (0,))):
                with pytest.raises(S.UserError, match="registrar"):
                    S.call(c, call, *args)
        finally:
            S.set_sender(self.REGISTRAR)
        assert [d["active"] for d in c.delegation(0)["delegates"]] == [True, True]

    def test_an_address_is_matched_by_value_not_by_spelling(self):
        """On chain an Address is 20 raw bytes and case carries no meaning."""
        c = self.deploy(FREEZE)
        S.call(c, "authorise", 0, "0x" + "AB" * 20)
        S.set_sender("0x" + "ab" * 20)
        try:
            S.call(c, "add", 0, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.step_count(0) == 2

    def test_may_add_answers_what_add_enforces(self):
        c = self.deploy(FREEZE)
        S.call(c, "authorise", 0, self.AGENT)
        assert c.may_add(0, self.REGISTRAR) is True
        assert c.may_add(0, self.AGENT) is True
        assert c.may_add(0, self.STRANGER) is False
        assert c.may_add(0, "not-an-address") is False
        # A distinct text per sender. Reusing one would hit the duplicate rule
        # on the second caller and mask the authority result being checked, so
        # the test would pass for the wrong reason.
        for i, who in enumerate((self.REGISTRAR, self.AGENT, self.STRANGER)):
            text = "Step number %d, which does a distinct thing." % i
            S.set_sender(who)
            try:
                if c.may_add(0, who):
                    S.call(c, "add", 0, text)
                else:
                    with pytest.raises(S.UserError, match="registrar or an authorised"):
                        S.call(c, "add", 0, text)
            finally:
                S.set_sender(self.REGISTRAR)

    @pytest.mark.parametrize("bad", ["", "0x", "not-an-address", "0x" + "z" * 40,
                                     "0x" + "11" * 19, "0x" + "11" * 21])
    def test_a_malformed_delegate_address_is_refused_cleanly(self, bad):
        c = self.deploy(FREEZE)
        with pytest.raises(S.UserError, match="not a 20 byte hex address"):
            S.call(c, "authorise", 0, bad)

    def test_the_delegate_cap_counts_active_rows(self):
        c = self.deploy(FREEZE)
        addrs = ["0x" + ("%02x" % (i + 32)) * 20 for i in range(16)]
        for a in addrs:
            S.call(c, "authorise", 0, a)
        with pytest.raises(S.UserError, match="capped at 16"):
            S.call(c, "authorise", 0, self.AGENT)
        S.call(c, "revoke", 0, addrs[0])
        S.call(c, "authorise", 0, self.AGENT)

    def test_the_cap_survives_a_revoke_and_reauthorise_cycle(self):
        """Counting and matching in one pass looks equivalent to counting first
        and is not: the match can be found before the count is finished."""
        c = self.deploy(FREEZE)
        addrs = ["0x" + ("%02x" % (i + 32)) * 20 for i in range(16)]
        for a in addrs:
            S.call(c, "authorise", 0, a)
        S.call(c, "revoke", 0, addrs[0])
        S.call(c, "authorise", 0, self.AGENT)
        with pytest.raises(S.UserError, match="capped at 16"):
            S.call(c, "authorise", 0, addrs[0])
        assert len([d for d in c.delegation(0)["delegates"] if d["active"]]) == 16

    def test_re_authorising_reuses_the_row(self):
        c = self.deploy(FREEZE)
        for _ in range(3):
            S.call(c, "authorise", 0, self.AGENT)
            S.call(c, "revoke", 0, self.AGENT)
        assert len(c.delegation(0)["delegates"]) == 1
        with pytest.raises(S.UserError, match="already revoked"):
            S.call(c, "revoke", 0, self.AGENT)

    def test_delegation_is_scoped_to_one_plan(self):
        c = self.deploy(FREEZE)
        S.call(c, "plan", "Another plan")
        S.call(c, "authorise", 0, self.AGENT)
        S.set_sender(self.AGENT)
        try:
            S.call(c, "add", 0, MIGRATE)
            with pytest.raises(S.UserError, match="registrar or an authorised delegate"):
                S.call(c, "add", 1, MIGRATE)
        finally:
            S.set_sender(self.REGISTRAR)

    def test_anyone_may_order_and_that_is_deliberate(self):
        """A plan's ordering is a public claim about the plan. An author who
        could decide which pairs got examined would examine only the ones that
        suited the sequence they wanted, and the cycle count would mean
        nothing."""
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.set_sender(self.STRANGER)
        try:
            S.call(c, "order", 0, 0, 1)
        finally:
            S.set_sender(self.REGISTRAR)
        assert c.sequence(0) == "0|1"
        assert c.step(0, 0)["by"].lower() == self.REGISTRAR

    # -- sealing ------------------------------------------------------------

    def test_a_sealed_plan_takes_no_new_steps(self):
        c = self.deploy(FREEZE)
        S.call(c, "seal", 0)
        with pytest.raises(S.UserError, match="sealed"):
            S.call(c, "add", 0, MIGRATE)

    def test_ordering_carries_on_after_sealing(self):
        """Sealing fixes the CONTENTS, which is exactly when working out the
        sequence becomes worth doing: a pair decided against a plan that can
        still grow may be decided against a different plan tomorrow."""
        c = self.deploy(FREEZE, MIGRATE)
        S.call(c, "seal", 0)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        assert c.sequence(0) == "0|1"

    def test_sealing_twice_is_refused(self):
        c = self.deploy(FREEZE)
        S.call(c, "seal", 0)
        with pytest.raises(S.UserError, match="already sealed"):
            S.call(c, "seal", 0)

    # -- validation ---------------------------------------------------------

    def test_a_step_cannot_come_before_itself(self):
        c = self.deploy(FREEZE, MIGRATE)
        with pytest.raises(S.UserError, match="before itself"):
            S.call(c, "order", 0, 0, 0)

    def test_ordering_a_step_that_is_not_in_the_plan_is_refused(self):
        c = self.deploy(FREEZE, MIGRATE)
        for a, b in ((0, 5), (5, 0), (0, -1), (-1, 0)):
            with pytest.raises(S.UserError, match="no such step"):
                S.call(c, "order", 0, a, b)

    def test_steps_are_local_to_their_plan(self):
        """Plan 1's step 0 is its own, not plan 0's. The flat array is shared
        and the local index is the only thing keeping them apart."""
        c = self.deploy(FREEZE, MIGRATE)
        S.call(c, "plan", "Another plan")
        S.call(c, "add", 1, CHANGELOG)
        assert c.step(1, 0)["text"] == CHANGELOG
        assert c.step_count(1) == 1
        with pytest.raises(S.UserError, match="no such step"):
            c.step(1, 1)

    @pytest.mark.parametrize("text", ["", "   ", "short", "x" * 400])
    def test_bad_step_text_is_refused(self, text):
        c = self.deploy()
        with pytest.raises(S.UserError):
            S.call(c, "add", 0, text)
        assert c.step_count(0) == 0

    @pytest.mark.parametrize("title", ["", "x", "y" * 200])
    def test_bad_titles_are_refused(self, title):
        c = S.deploy(CONTRACT_PATH)
        with pytest.raises(S.UserError):
            S.call(c, "plan", title)
        assert c.count() == 0

    def test_two_identical_steps_are_refused(self):
        """They make the two presentation orders the SAME prompt, so the mirror
        compares one answer against itself and settle() can only ever return
        `neither`. The pair becomes permanently undecidable and the mirror --
        the whole reason the block runs twice -- silently does nothing."""
        c = self.deploy(FREEZE)
        with pytest.raises(S.UserError, match="already in the plan"):
            S.call(c, "add", 0, FREEZE)
        assert c.step_count(0) == 1

    def test_the_same_text_in_a_different_plan_is_fine(self):
        """The rule is about one plan's own steps. Two plans may legitimately
        share a step, and they are never compared against each other."""
        c = self.deploy(FREEZE)
        S.call(c, "plan", "Another plan")
        S.call(c, "add", 1, FREEZE)
        assert c.step_count(0) == 1 and c.step_count(1) == 1

    def test_the_step_cap_is_enforced(self):
        c = self.deploy()
        for i in range(24):
            S.call(c, "add", 0, "Step number %d, which does a thing." % i)
        with pytest.raises(S.UserError, match="capped at 24"):
            S.call(c, "add", 0, "One step too many, which does a thing.")
        assert c.step_count(0) == 24

    def test_the_reason_is_sanitised_on_the_way_in(self):
        c = self.deploy(FREEZE, MIGRATE)
        self.mocks(pair((FREEZE, "first"), (MIGRATE, "second"),
                        because="<script>alert(1)</script> `x` {y}"))
        S.call(c, "order", 0, 0, 1)
        why = c.edges_of(0)["pairs"][0]["why"]
        for ch in "<>{}`\\":
            assert ch not in why

    def test_a_read_with_a_nonexistent_id_is_a_user_error(self):
        """Not a raw IndexError. GenVM reports an uncaught Python exception as
        a contract error, which tells a caller nothing about what went wrong."""
        c = self.deploy(FREEZE)
        for m in ("sequence", "registrar", "overview", "edges_of", "step_count",
                  "delegation"):
            with pytest.raises(S.UserError, match="no such plan"):
                getattr(c, m)(99)

    def test_a_read_with_a_negative_id_does_not_return_the_last_row(self):
        """The dangerous half. Python list indexing accepts -1 and returns the
        newest row, so a caller asking for -1 would silently receive a
        different one and never know."""
        c = self.deploy(FREEZE)
        S.call(c, "plan", "Another plan")
        for m in ("sequence", "registrar", "overview", "edges_of", "step_count",
                  "delegation"):
            with pytest.raises(S.UserError, match="no such plan"):
                getattr(c, m)(-1)
        with pytest.raises(S.UserError, match="no such step"):
            c.step(0, -1)
        with pytest.raises(S.UserError, match="no such step"):
            c.blocked_by(0, -1)

    def test_the_overview_counts_what_the_contract_publishes(self):
        c = self.deploy(FREEZE, MIGRATE, REPLICA)
        self.mocks(stable(FREEZE, MIGRATE, "a"))
        S.call(c, "order", 0, 0, 1)
        self.mocks(stable(MIGRATE, REPLICA, "a"))
        S.call(c, "order", 0, 1, 2)
        self.mocks(stable(REPLICA, FREEZE, "a"))
        S.call(c, "order", 0, 2, 0)
        got = c.overview(0)
        assert got["steps"] == 3 and got["pairs_possible"] == 3
        assert got["pairs_decided"] == 3 and got["dependencies"] == 2
        assert got["cycles_refused"] == 1 and got["settled_pct"] == 100


# ===========================================================================
# GenVM storage and boundary rules, by static analysis.
#
# Not tests of behaviour. Tests of SHAPE, and each corresponds to a real
# failure that behaviour tests cannot see.
# ===========================================================================

def contract_writes():
    """The public write methods of the contract, by name."""
    tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
    cls = [x for x in tree.body if isinstance(x, ast.ClassDef)
           and any("gl.Contract" in ast.unparse(b) for b in x.bases)][0]
    return {m.name: m for m in cls.body if isinstance(m, ast.FunctionDef)
            and any("gl.public.write" in ast.unparse(d) for d in m.decorator_list)}


class TestShape:
    def test_the_contract_imports_under_genvm_storage_rules(self):
        mod = S.load_contract(CONTRACT_PATH)
        assert hasattr(mod, "Contract")

    def test_no_storage_dataclass_holds_a_collection(self):
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            if "allow_storage" not in " ".join(
                    ast.unparse(d) for d in cls.decorator_list):
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert "DynArray" not in ann and "TreeMap" not in ann

    def test_no_forbidden_storage_types(self):
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            decs = " ".join(ast.unparse(d) for d in cls.decorator_list)
            is_contract = any("gl.Contract" in ast.unparse(b) for b in cls.bases)
            if "allow_storage" not in decs and not is_contract:
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign):
                    ann = ast.unparse(st.annotation)
                    assert ann not in ("int", "float", "list", "dict", "tuple")
                    assert not ann.startswith(("list[", "dict[", "tuple["))

    def test_no_storage_field_is_declared_twice(self):
        import collections
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            names = [st.target.id for st in cls.body
                     if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)]
            dupes = [n for n, c in collections.Counter(names).items() if c > 1]
            assert not dupes, f"{cls.name} declares {dupes} more than once"

    def test_no_method_is_defined_twice(self):
        """A duplicated method silently shadows the first one. Python allows it
        and says nothing at all."""
        import collections
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        for cls in [x for x in tree.body if isinstance(x, ast.ClassDef)]:
            names = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
            dupes = [n for n, c in collections.Counter(names).items() if c > 1]
            assert not dupes, f"{cls.name} defines {dupes} more than once"
        names = [x.name for x in tree.body
                 if isinstance(x, (ast.FunctionDef, ast.ClassDef))]
        dupes = [n for n, c in collections.Counter(names).items() if c > 1]
        assert not dupes

    def test_every_persistent_field_is_declared_in_the_class_body(self):
        """A field created with self.x = value and never declared is NOT
        persistent. It is silently discarded when execution ends."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        cls = [x for x in tree.body if isinstance(x, ast.ClassDef)
               and any("gl.Contract" in ast.unparse(b) for b in x.bases)][0]
        declared = {st.target.id for st in cls.body if isinstance(st, ast.AnnAssign)}
        for m in [x for x in cls.body if isinstance(x, ast.FunctionDef)]:
            for node in ast.walk(m):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target] if isinstance(node, ast.AugAssign) else [])
                for tg in targets:
                    if (isinstance(tg, ast.Attribute)
                            and isinstance(tg.value, ast.Name)
                            and tg.value.id == "self"):
                        assert tg.attr in declared, (
                            f"{m.name} assigns self.{tg.attr}, undeclared, will not persist")

    def test_the_block_boundary_carries_flat_strings_only(self):
        """A nested mapping or a bool here fails inside the calldata encoder,
        which is OUTSIDE the contract, so it produces Result Code <unknown>
        with no stderr and no traceback at all."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        blocks = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                  and x.name == "leader_fn"]
        assert blocks
        for blk in blocks:
            returns = [n for n in ast.walk(blk) if isinstance(n, ast.Return)]
            assert returns
            for r in returns:
                assert isinstance(r.value, ast.Dict)
                for k, v in zip(r.value.keys, r.value.values):
                    assert isinstance(k, ast.Constant) and isinstance(k.value, str)
                    assert not isinstance(v, (ast.Dict, ast.List, ast.Set, ast.Tuple))
                    assert not isinstance(v, (ast.Compare, ast.BoolOp))
                    if isinstance(v, ast.UnaryOp):
                        assert not isinstance(v.op, ast.Not)

    def test_every_nondet_call_sits_inside_a_block(self):
        """gl.nondet.* outside a closure the consensus flow recognises fails
        genvm-lint with 'not reachable from equivalence principle block'. A
        GenLayer submission has been rejected for having this in its DEPLOYED
        source while the repository version was clean."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        inner = set()
        for fn in [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                   and x.name in ("leader_fn", "validator_fn")]:
            for n in ast.walk(fn):
                inner.add(id(n))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and ast.unparse(node).startswith("gl.nondet"):
                assert id(node) in inner, (
                    f"{ast.unparse(node)} is outside leader_fn/validator_fn")

    def test_every_write_that_touches_a_plan_checks_the_sender(self):
        """This covers the methods nobody has written yet: a new public write
        added later without an authority check fails here, and the only way to
        pass is to gate it or to add it to the list below on purpose, which is
        a decision somebody has to make in a diff rather than by omission.

          plan   creates the plan and becomes its registrar, so there is no
                 earlier owner to check against
          order  deliberately open. A plan's ordering is a public claim about
                 the plan, and an author who chose which pairs got examined
                 would examine only the ones suiting the sequence they wanted.
                 It adds no text and can reach only the answer the two stored
                 steps and the accumulated graph already imply.
        """
        UNGATED = {"plan", "order"}
        gated = contract_writes()
        assert gated, "no public writes found, the walk is broken"
        for name, m in gated.items():
            if name in UNGATED:
                continue
            body = ast.unparse(m)
            assert "sender_address" in body or "_may_add" in body, (
                f"{name} is a public write with no authority check")

    def test_the_cycle_check_runs_before_any_edge_is_stored(self):
        """An edge appended before the check would already be in the graph the
        check reads, so every edge would look like a cycle -- or, with the
        check reading a stale list, none of them would."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        order = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                 and x.name == "order"][0]
        body = ast.unparse(order)
        assert body.index("would_cycle") < body.index("self.edges.append")

    def test_only_a_live_edge_constrains_the_layering(self):
        """A `cycle` row records that an edge was REFUSED. Treating it as an
        edge would build the very graph the contract declined to build."""
        tree = ast.parse(pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8"))
        fn = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
              and x.name == "_live_edges"][0]
        assert "e.live" in ast.unparse(fn)
        src = pathlib.Path(CONTRACT_PATH).read_text(encoding="utf-8")
        # the layering and the cycle test must read the filtered list, never
        # self.edges directly
        for name in ("sequence", "overview", "blocked_by"):
            f = [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                 and x.name == name][0]
            body = ast.unparse(f)
            assert "_live_edges" in body
            assert "self.edges" not in body
