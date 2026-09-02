<p align="left"><img src="brand/lockup.svg" alt="keystone" height="64"></p>

# Keystone — an ordering built one pair at a time, that cannot contradict itself

A reusable GenLayer primitive that accumulates "this must come before that" from
prose, one pair at a time, and **refuses any judgment that would contradict the
ones it already holds**. The model answers the easiest question there is. The
contract owns the graph and does the hard part with no model at all.

- **Contract:** [`contracts/keystone.py`](contracts/keystone.py)
- **Tests:** `pip install pytest && pytest tests/ -q` — nothing else to install
- **Deployed:** `{address}` on studionet ([explorer](https://explorer-studio.genlayer.com/address/{address}))
- **Deploying it yourself:** [DEPLOY.md](DEPLOY.md) — the contract, the demo, and the check to run before submitting
- **Verify a deployment:** `python scripts/verify_deployment.py 0x…` — diffs the
  on-chain source against this file
- **Specification:** [CONTRACTS.md](CONTRACTS.md)
- **Decisions:** [DECISIONS.md](DECISIONS.md)
- **License:** MIT. Copy the agreement rule; that is what it is for.

---

## The problem

A plan arrives as prose. Migrate the database. Freeze writes. Cut over the read
replicas. Publish the changelog. Nothing states an order, and **the order is the
whole plan**.

Ask a model to sort the list and it returns a confident sequence, a different one
each time, and nothing anywhere checks whether the sequence is even possible.

Ask it about one pair and it is reliable. Ask it about every pair independently
and it will happily tell you:

```
freeze  before  migrate
migrate before  replicas
replicas before freeze
```

**No single answer is wrong. The set of them is impossible.** That is not a
failure of the model, it is a failure of the assembly: nothing ever forced it to
hold all three at once, and consensus on each pair separately cannot see it
either — five nodes agreeing on each edge produces exactly the same loop.

## How consensus is used

Consensus decides **one pairwise question at a time**, and the answer is one of
three tokens: `first`, `second`, `neither`.

> The judgment is hard. Read two pieces of prose, work out what each actually
> requires, and decide whether one genuinely depends on the other or merely
> sounds earlier.
>
> **The thing that crosses consensus is one token out of three, about two rows
> the contract already holds.**

### The leader resolves its own position bias first

The block asks the same pair **twice**, once in each presentation order, and the
answers must mirror: an item that wins when shown first must still win when shown
second.

```python
def settle(forward, reverse):
    f, r = normalise_token(forward), normalise_token(reverse)
    if f == "" or r == "":
        return NEITHER
    if flip(f) == r:
        return f
    return NEITHER          # <- the stored value, not a forgiven difference
```

Position bias is invisible to consensus on its own, because every validator
builds the prompt the same way and every validator leans the same way. Two
orderings inside one block is the only place it can be caught, and the
uncertainty lands in **the stored value** rather than in a tolerance in the
agreement rule.

### Then the contract does the part no model is involved in

It holds every edge agreed so far and, before storing a new one, runs a cycle
check:

```python
def would_cycle(edges, a, b, n):
    return reaches(edges, b, a, n)      # can b already get back to a?
```

If it can, storing `a -> b` would close a loop. The contract refuses the edge,
records the refusal as a `cycle`, and leaves the ordering it already had intact.

**That refusal is the most valuable thing this contract produces**, because it is
a finding about the *plan* rather than about the pair — and every edge involved
in it was agreed by the network.

### The validator, in two layers

```python
# LAYER 1 -- structural honesty. Costs nothing, runs before any prompt.
#   The token must be one of the three, and the answer must be about the pair
#   that was asked. Without the second half, a leader could answer an easy pair
#   and have it recorded against a hard one.

# LAYER 2 -- exact equality on the token.
#   Not "we both found a dependency". The same direction. Two nodes that order a
#   pair opposite ways have agreed about nothing, and `neither` against `first`
#   is a real disagreement about whether a dependency exists at all.
```

## The answer is layers, not a line

```
0        freeze writes
1,2      run the migration  |  publish the changelog
3        repoint the replicas
```

A plan of n steps has n(n-1)/2 pairs and most of them do not matter. Keystone
stores only the ones somebody asked about, answers `neither` freely, and reports
the order as layers: everything in layer 0 can start now, everything in layer 1
waits only for layer 0.

**A total order would be a lie about a plan that is genuinely partly parallel.**

Indices are sorted within each layer, so two nodes computing the same layering
produce the same string. Without that, deriving the answer deterministically
achieves nothing.

## Why this is not a thin LLM wrapper

The model never produces an ordering. **It answers three-way multiple choice
about two rows, twice.** The graph, the transitive closure, the cycle detection,
the refusal, and the layering with its tie-break are all deterministic and none
of them involve a model.

Swap in a worse model and the mechanism still works. It produces more `neither`,
which yields a weaker partial order rather than a wrong one.

## Who may write to a plan

Every write is bound to an address, and the registrar is the identity: `title` is
a display string that anybody could have typed.

| Call | Who |
|---|---|
| `plan` | anyone. The caller becomes the registrar of the new plan |
| `add` | the registrar, or an address the registrar has authorised |
| `authorise` / `revoke` | the registrar alone |
| `seal` | the registrar alone |
| `order` | anyone, deliberately |

`add()` is the load-bearing one: every step enters every later pairwise question,
takes a position in the published layering, and is read as part of somebody
else's plan.

**A delegate may write into a plan but not own it.** It cannot authorise, revoke,
or seal. Every step and every edge stores the address that submitted it.

`order()` is open on purpose. A plan's ordering is a public claim about the plan,
and an author who could decide which pairs got examined would only ever examine
the ones that suited the sequence they wanted — which would make the cycle count
meaningless.

## The API

```python
plan(title)                        # anyone. caller becomes registrar
add(plan_id, text)                 # registrar or authorised delegate
authorise(plan_id, who)            # registrar only
revoke(plan_id, who)               # registrar only
seal(plan_id)                      # registrar only
order(plan_id, a, b)               # anyone, deliberately

sequence(plan_id)        -> str    # the layering: "0|1,2|3"
blocked_by(plan_id, i)   -> str    # the steps that must finish first
overview(plan_id)        -> dict   # steps, pairs decided, cycles refused
edges_of(plan_id)        -> dict   # every pair ever decided, refusals included
step(plan_id, index)     -> dict   # the text, and who added it
step_count(plan_id)      -> u256
registrar(plan_id)       -> str    # the address that owns it
may_add(plan_id, who)    -> bool   # could that address write to it right now
delegation(plan_id)      -> dict   # every address authorised, revoked ones too
```

## Using it from another contract

```python
@gl.contract_interface
class Keystone:
    class View:
        def blocked_by(self, plan_id: int, index: int) -> str: ...
        def registrar(self, plan_id: int) -> str: ...

k = Keystone(KEYSTONE_ADDR).view()

# bind to the address, never to the title
if k.registrar(pid) != expected_owner:
    raise ...

# start a step only when nothing is in front of it
if k.blocked_by(pid, step) == "":
    self._begin(step)
```

`blocked_by()` returns direct dependencies, not the transitive closure: a caller
asking what is in the way wants the things it can act on.

---

## Running the tests

```bash
pip install pytest
pytest tests/ -q
```

Nothing else is needed. `tests/glsim.py` is a small GenVM stand-in, so the unit
and end-to-end suites run with no Studio and no network.

The integration suite is **opt in**, and deliberately so. It skips when
`genlayer-test` is absent, and it also skips when `genlayer-test` is present
without a Studio to talk to — otherwise anybody who reviews GenLayer contracts,
and therefore has the plugin installed, would see a wall of connection errors on
a repository that promises an offline run. To run it against a live Studio:

```bash
pip install genlayer-test
GENLAYER_STUDIO=1 gltest --network studionet tests/test_integration.py
```

<!-- measured:tests -->
`pytest tests/ -q` reports **162 passed, 1 skipped**, and every one of the **54** mutations below is caught.
<!-- /measured:tests -->

### The tests have teeth

A passing count is a claim. The table below is evidence: every row is a real edit
to the contract that removes a defence, and the test named beside it is the one
that failed. It is generated by `scripts/mutate.py`, which refuses to emit a
table if anything escapes.

<!-- measured:mutations -->
| Mutation | Caught by |
|---|---|
| the mirror accepts an answer that does not invert | `test_a_step_that_always_wins_from_the_front_settles_to_neither` |
| flip made an identity, so every pair mirrors itself | `test_a_dependency_that_survives_both_orders_is_stored` |
| the second presentation order never runs | `test_a_step_that_always_wins_from_the_front_settles_to_neither` |
| an unusable answer settled as a real one | `test_a_garbage_answer_is_not_read_as_neither_by_accident` |
| the cycle check removed, so the graph can contradict itself | `test_the_third_edge_that_closes_a_loop_is_refused` |
| the cycle check reads the wrong direction | `test_the_third_edge_that_closes_a_loop_is_refused` |
| reachability stops after one hop, so only direct reversals are caught | `test_the_third_edge_that_closes_a_loop_is_refused` |
| a refused edge is stored as live anyway | `test_the_third_edge_that_closes_a_loop_is_refused` |
| an unrelated pair is stored as a dependency | `test_unrelated_steps_stay_in_the_same_layer` |
| the live filter dropped, so refusals constrain the ordering | `test_unrelated_steps_stay_in_the_same_layer` |
| the edge direction inverted for a `second` answer | `test_the_direction_is_recorded_not_the_argument_order` |
| layers not sorted within a layer | `test_every_lifted_function_is_identical_to_the_contract` |
| the first layer not sorted | `test_an_unordered_plan_is_one_layer` |
| a cycle returns a partial order instead of nothing | `test_a_cycle_returns_none_rather_than_a_partial_order` |
| agreement loosened to "we both found a dependency" | `test_nodes_ordering_a_pair_opposite_ways_do_not_agree` |
| opposite directions allowed to settle | `test_nodes_ordering_a_pair_opposite_ways_do_not_agree` |
| the free structural layer removed | `test_a_leader_answering_a_different_pair_is_rejected` |
| the pair check dropped, so an answer about another pair is accepted | `test_a_leader_answering_a_different_pair_is_rejected` |
| an illegal token accepted from a prompt | `test_the_free_layer_is_actually_free` |
| the same pair can be decided twice | `test_a_pair_is_only_decided_once` |
| a pair only counts as decided in the order it was first asked | `test_the_same_pair_the_other_way_round_is_the_same_pair` |
| a step allowed to depend on itself | `test_a_step_cannot_come_before_itself` |
| step bounds not checked, so a pair can name a step in another plan | `test_ordering_a_step_that_is_not_in_the_plan_is_refused` |
| the plan filter dropped, so every plan shares one step list | `test_the_owner_can_carry_the_work_into_a_fresh_plan` |
| two identical steps allowed, so a pair can never be mirrored | `test_two_identical_steps_are_refused` |
| the step cap removed | `test_the_step_cap_is_enforced` |
| a sealed plan still accepts steps | `test_a_sealed_plan_takes_no_new_steps` |
| a cycle refusal seals the plan, so no further work is possible | `test_a_plan_is_still_usable_after_a_cycle_refusal` |
| add left unauthenticated, so anyone may write into any plan | `test_a_stranger_cannot_add_steps_to_someone_elses_plan` |
| the submitting address not recorded on the step | `test_a_delegate_may_add_and_the_record_names_them` |
| a revoked delegate still counted as authorised | `test_a_revoked_delegate_cannot_add` |
| delegation not scoped to the plan it was granted on | `test_delegation_is_scoped_to_one_plan` |
| a delegate allowed to appoint further delegates | `test_a_delegate_may_not_authorise_revoke_or_seal` |
| a delegate allowed to revoke | `test_a_delegate_may_not_authorise_revoke_or_seal` |
| a delegate allowed to seal the plan | `test_a_delegate_may_not_authorise_revoke_or_seal` |
| may_add() drifting from the rule add() enforces | `test_may_add_answers_what_add_enforces` |
| the cap not re-checked when a revoked delegate is reactivated | `test_the_cap_survives_a_revoke_and_reauthorise_cycle` |
| the cap counted in the same pass that finds the row | `test_the_cap_survives_a_revoke_and_reauthorise_cycle` |
| a malformed delegate address passed to Address() | `test_a_malformed_delegate_address_is_refused_cleanly` |
| the plan bounds check removed | `test_a_read_with_a_nonexistent_id_is_a_user_error` |
| negative plan ids allowed through to Python list indexing | `test_a_read_with_a_negative_id_does_not_return_the_last_row` |
| the reason sanitiser disabled | `test_the_reason_is_sanitised_on_the_way_in` |
| control characters left in reasons | `test_control_characters_become_spaces` |
| the prompt fence removed, so a caller can forge a block | `test_the_plan_title_is_fenced_too` |
| the fence deletes instead of replacing | `test_fence_replaces_rather_than_deletes` |
| only the opening bracket fenced | `test_fence_replaces_rather_than_deletes` |
| the second step reaches the model unfenced | `test_every_lifted_function_is_identical_to_the_contract` |
| the plan title reaches the model unfenced | `test_every_lifted_function_is_identical_to_the_contract` |
| a nested mapping returned from the block | `test_a_dependency_that_survives_both_orders_is_stored` |
| a bool returned from the block | `test_a_dependency_that_survives_both_orders_is_stored` |
| a collection nested back into a storage dataclass | `TypeError at import` |
| an int storage field | `TypeError at import` |
| a storage field declared twice | `test_no_storage_field_is_declared_twice` |
| a prompt moved outside the block, which genvm-lint refuses | `test_a_dependency_that_survives_both_orders_is_stored` |
<!-- /measured:mutations -->

The simulator can also model **a leader that lies**: `set_leader_payload()` puts a
value on the wire that `leader_fn` would never return, which is the only way to
exercise the checks a validator runs against a peer it does not trust. Without
it, every one of those checks is unreachable in testing and a defence that cannot
be exercised looks identical to one that is not there.

## Design rules

- **The block returns one token, never an ordering.** Three legal words about two
  rows the contract already holds.
- **Uncertainty enters the stored value.** A pair the leader answers two
  different ways is stored as `unrelated`, never forgiven at comparison time.
- **Exact equality between nodes.** No tolerance, in either direction.
- **Agreement is not consistency.** Every edge in a refused cycle was agreed by
  the network. Only the contract holds enough state to tell the difference.
- **Untrusted text is fenced at the prompt boundary.** Tagging it and telling the
  model it is data is not a fence on its own: `fence()` neutralises the
  characters that can close a tag, so a caller cannot forge a block. Replace,
  never delete, and at the boundary only — storage keeps what was written.
- **A refusal is kept.** A cycle found once stays findable; deleting it would
  throw away the finding.
- **Every write is bound to an address**, and a static test asserts it for the
  methods nobody has written yet.
- **No web access.** Every input is text the caller supplies, which removes an
  entire class of deployment failure.

## Further reading in this repository

- [CONTRACTS.md](CONTRACTS.md) — the full specification: purpose, consensus,
  state model, API, reuse
- [DECISIONS.md](DECISIONS.md) — engineering decisions and what they cost
- [lib/keystone_consensus.py](lib/keystone_consensus.py) — the agreement rules
- [brand/](brand/) — the mark, the lockup, the palette, and the social card
  and the graph functions on their own, to be copied. Generated by
  `scripts/lift.py` and checked for drift by the suite

## Related work

Separate primitives, built to the same standard and submitted independently:
[Ratchet](https://github.com/meitipro/ratchet) — a published commitment that can
only ever be tightened.
[Recant](https://github.com/meitipro/recant) — self-consistency across a record
of statements.

They share an author and a discipline, not a codebase. Each deploys, tests and is
used entirely on its own.

---

Published by [InferNode](https://x.com/Infer_node).
