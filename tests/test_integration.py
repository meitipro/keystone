"""Integration tests, run against GenLayer Studio with gltest.

    pip install genlayer-test
    pip install genlayer-test
    GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py

They are opt in: without GENLAYER_STUDIO set they skip, so that
`pytest tests/ -q` stays clean on a machine that has genlayer-test
installed but no Studio to talk to.

These are slower than the other two suites and they prove something different:
that the contract deploys, that storage round-trips, that the deterministic
gates fire, and that the whole leader-plus-validator cycle completes against a
real runtime rather than against tests/glsim.py.

Everything here exercises the deterministic half, which needs no inference: a
plan opens, steps are added, the authority rules fire, and the bounds and
sealing gates refuse what they should. The ordering path costs two prompts per
pair and belongs in a manual Studio run.
"""

import os

import pytest

# gltest is only needed for this file. Skip cleanly when it is absent so that
# `pytest tests/` works out of the box on a machine with nothing installed but
# pytest, and still runs everything in test_logic.py and test_e2e.py.
gltest = pytest.importorskip(
    "gltest",
    reason="integration tests need genlayer-test and a running Studio: "
           "pip install genlayer-test, then GENLAYER_STUDIO=1 gltest",
)
from gltest import get_contract_factory, get_accounts        # noqa: E402
from gltest.assertions import tx_execution_succeeded         # noqa: E402


# The second half of the same guard, and it is the half that bites.
#
# importorskip above covers "genlayer-test is not installed". It does NOT cover
# "genlayer-test IS installed and there is no Studio to talk to", which is the
# common case for anybody who reviews GenLayer contracts: the plugin loads,
# collects this file, and every test in it fails on a connection error rather
# than skipping. `pytest tests/ -q` then reports a wall of ERRORs on a
# repository whose README promises a clean offline run, and the reader cannot
# tell an unreachable network from a broken contract.
#
# Detecting it does not work. A probe was tried first and thrown away: the
# transport failures here are INTERMITTENT rather than a clean threshold, so
# the probe passes and the deploy that follows it still dies. Something that
# answers correctly only most of the time is worse than no gate at all.
#
# So the gate is explicit. These tests need a live Studio, and you say so.
if not os.environ.get("GENLAYER_STUDIO"):
    pytest.skip(
        "integration tests run against a live GenLayer Studio and are opt in: "
        "set GENLAYER_STUDIO=1 to enable them. Everything else runs offline "
        "with pytest tests/ -q",
        allow_module_level=True,
    )


TITLE = "Database cutover, March"
FREEZE = "Freeze writes to the primary database and drain the outstanding queue."
MIGRATE = "Run the schema migration against the primary database."


class TestKeystone:
    @pytest.fixture
    def contract(self):
        factory = get_contract_factory(contract_file_path="keystone.py")
        return factory.deploy(args=[])

    def test_a_plan_opens_and_takes_steps(self, contract):
        assert tx_execution_succeeded(contract.plan(args=[TITLE]))
        assert tx_execution_succeeded(contract.add(args=[0, FREEZE]))
        assert tx_execution_succeeded(contract.add(args=[0, MIGRATE]))
        assert contract.step_count(args=[0]) == 2
        assert contract.step(args=[0, 0])["text"] == FREEZE

    def test_an_unordered_plan_is_one_layer(self, contract):
        """Nothing has been decided, so nothing blocks anything. A contract
        that guessed an order here would be inventing dependencies."""
        contract.plan(args=[TITLE])
        contract.add(args=[0, FREEZE])
        contract.add(args=[0, MIGRATE])
        assert contract.sequence(args=[0]) == "0,1"
        assert contract.blocked_by(args=[0, 1]) == ""

    def test_a_step_cannot_come_before_itself(self, contract):
        contract.plan(args=[TITLE])
        contract.add(args=[0, FREEZE])
        contract.add(args=[0, MIGRATE])
        with pytest.raises(Exception):
            contract.order(args=[0, 0, 0])

    def test_ordering_a_step_that_is_not_in_the_plan_is_refused(self, contract):
        contract.plan(args=[TITLE])
        contract.add(args=[0, FREEZE])
        contract.add(args=[0, MIGRATE])
        with pytest.raises(Exception):
            contract.order(args=[0, 0, 9])

    def test_steps_are_local_to_their_plan(self, contract):
        """Plan 1's step 0 is its own. The flat array is shared and the local
        index is the only thing keeping them apart."""
        contract.plan(args=[TITLE])
        contract.add(args=[0, FREEZE])
        contract.plan(args=["Another plan"])
        contract.add(args=[1, MIGRATE])
        assert contract.step(args=[1, 0])["text"] == MIGRATE
        assert contract.step_count(args=[1]) == 1

    def test_a_sealed_plan_takes_no_new_steps(self, contract):
        contract.plan(args=[TITLE])
        contract.add(args=[0, FREEZE])
        assert tx_execution_succeeded(contract.seal(args=[0]))
        with pytest.raises(Exception):
            contract.add(args=[0, MIGRATE])

    def test_sealing_twice_is_refused(self, contract):
        contract.plan(args=[TITLE])
        contract.seal(args=[0])
        with pytest.raises(Exception):
            contract.seal(args=[0])

    def test_a_short_step_is_refused(self, contract):
        contract.plan(args=[TITLE])
        with pytest.raises(Exception):
            contract.add(args=[0, "short"])

    def test_an_unknown_plan_is_refused(self, contract):
        contract.plan(args=[TITLE])
        with pytest.raises(Exception):
            contract.overview(args=[9])

    def test_a_negative_id_does_not_return_the_newest_row(self, contract):
        # Python accepts -1 and hands back the last row, correctly formatted,
        # with nothing failing anywhere.
        contract.plan(args=[TITLE])
        with pytest.raises(Exception):
            contract.overview(args=[-1])


class TestAuthority:
    """The authorisation rules, against a real runtime.

    These matter more than the rest of this file. tests/glsim.py models
    gl.message.sender_address with a variable a test can set; a node derives it
    from a signature. A rule that holds in the simulator and not on chain would
    be invisible to every other test here.
    """

    @pytest.fixture
    def two(self):
        accounts = get_accounts()
        if len(accounts) < 2:
            pytest.skip(
                "needs two configured accounts on this network, so that a "
                "refusal is a refusal and not an unfunded sender"
            )
        return accounts[0], accounts[1]

    @pytest.fixture
    def contract(self, two):
        owner, _ = two
        factory = get_contract_factory(contract_file_path="keystone.py")
        return factory.deploy(args=[], account=owner)

    def test_a_stranger_cannot_add_to_someone_elses_plan(self, contract, two):
        _, stranger = two
        contract.plan(args=[TITLE])
        with pytest.raises(Exception):
            contract.connect(stranger).add(args=[0, FREEZE])
        assert contract.step_count(args=[0]) == 0

    def test_a_delegate_may_add_and_the_record_names_them(self, contract, two):
        _, agent = two
        contract.plan(args=[TITLE])
        assert tx_execution_succeeded(contract.authorise(args=[0, agent.address]))
        assert tx_execution_succeeded(contract.connect(agent).add(args=[0, FREEZE]))
        assert contract.step(args=[0, 0])["by"].lower() == agent.address.lower()

    def test_a_revoked_delegate_cannot_add(self, contract, two):
        _, agent = two
        contract.plan(args=[TITLE])
        contract.authorise(args=[0, agent.address])
        assert tx_execution_succeeded(contract.revoke(args=[0, agent.address]))
        with pytest.raises(Exception):
            contract.connect(agent).add(args=[0, FREEZE])

    def test_a_delegate_may_not_authorise_revoke_or_seal(self, contract, two):
        _, agent = two
        contract.plan(args=[TITLE])
        contract.authorise(args=[0, agent.address])
        for call, args in (("authorise", [0, agent.address]),
                           ("revoke", [0, agent.address]),
                           ("seal", [0])):
            with pytest.raises(Exception):
                getattr(contract.connect(agent), call)(args=args)

    def test_may_add_answers_what_add_enforces(self, contract, two):
        owner, agent = two
        contract.plan(args=[TITLE])
        assert contract.may_add(args=[0, owner.address]) is True
        assert contract.may_add(args=[0, agent.address]) is False
        contract.authorise(args=[0, agent.address])
        assert contract.may_add(args=[0, agent.address]) is True

    def test_an_address_is_matched_by_value_not_by_spelling(self, contract, two):
        """An Address is 20 raw bytes on chain, so case carries no meaning."""
        _, agent = two
        contract.plan(args=[TITLE])
        contract.authorise(args=[0, agent.address.lower()])
        upper = "0x" + agent.address[2:].upper()
        assert contract.may_add(args=[0, upper]) is True

    def test_a_malformed_delegate_address_is_refused(self, contract):
        contract.plan(args=[TITLE])
        with pytest.raises(Exception):
            contract.authorise(args=[0, "not-an-address"])
