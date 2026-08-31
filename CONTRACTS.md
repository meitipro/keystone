# Keystone — specification

One standalone GenLayer Intelligent Contract.
[`contracts/keystone.py`](contracts/keystone.py), deployed exactly as written, no
build step.

Runner pinned in the header:
`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`

---

## Purpose

Accumulate "this must come before that" from prose, one pair at a time, and
refuse any judgment that would contradict the ones already held. Report the
result as **layers** rather than as a single sequence.

The failure it catches is not a wrong answer. It is a set of individually
reasonable answers that cannot all be true:

```
a before b      agreed by the network
b before c      agreed by the network
c before a      agreed by the network
```

Nothing here is a model failure. It is a failure of **assembly**: no single
question ever forced the model to hold all three at once, and consensus on each
pair separately produces exactly the same loop, five nodes at a time.

## Consensus

`gl.vm.run_nondet_unsafe`. **Two prompts in one block**, the same pair in both
presentation orders.

The block receives the two step texts and returns one of three tokens:

| Token | Meaning |
|---|---|
| `first` | the first item shown must be finished before the second can start |
| `second` | the second item shown must be finished before the first |
| `neither` | either order works, or they can run at once |

### The mirror

`settle()` requires the two passes to invert: an item that wins when shown first
must still win when shown second. `flip(first) == second`, and `neither` is its
own mirror, so a stable `neither` requires **both** passes to say it.

A pair whose passes do not mirror settles to `neither`, and that is **the value
that gets stored**. Position bias is invisible to consensus on its own, because
every validator builds the prompt the same way and leans the same way.

### The validator

1. **Structural honesty, free.** The token must be one of the three, and the
   claimed pair must be the pair this transaction is deciding. Without the
   second half a leader could answer an easy pair and have it recorded against a
   hard one.
2. **Exact equality on the token.** `neither` against `first` is a real
   disagreement about whether a dependency exists at all.

`keystone_agrees(a, b) == keystone_agrees(b, a)`, by construction.

## The deterministic half

This is the part with no model in it, and it is where the value is.

```python
def reaches(edges, start, goal, n)     # breadth first, bounded by n
def would_cycle(edges, a, b, n)        # can b already get back to a?
def layers(edges, n)                   # Kahn, sorted within each layer
```

`would_cycle` runs **before** the edge is appended — a static test asserts the
ordering, because an edge already in the list would make every edge look like a
cycle.

### Four outcomes per pair

| Outcome | Stored | `live` | Constrains the ordering |
|---|---|---|---|
| `before` | a -> b | yes | yes |
| `after` | b -> a | yes | yes |
| `unrelated` | the pair, as decided | no | no |
| `cycle` | the edge that was **refused** | no | no |

A refused pair is kept, not deleted. A cycle found once stays findable, and it is
a fact about the plan rather than a failed call.

### Layers, not a line

`layers()` returns lists of indices: everything in layer 0 can start now,
everything in layer 1 waits only for layer 0. Indices are **sorted within each
layer**, so two nodes computing the same layering produce the same string.

A total order would state dependencies nobody agreed to. It returns `None` on a
cyclic graph, which should be unreachable because every edge was checked before
storage — `None` there means something upstream is broken and the caller should
hear that rather than receive an ordering with steps missing from it.

## State

Every collection is a **top level contract field**. No storage dataclass contains
a collection, because GenVM cannot construct one. Children carry a parent id.

| Field | Type | Note |
|---|---|---|
| `plans` | `DynArray[Plan]` | append only |
| `steps` | `DynArray[Step]` | flat, each carries `plan_id` |
| `edges` | `DynArray[Edge]` | flat, refusals kept |
| `delegates` | `DynArray[Delegate]` | flat, each carries `plan_id` |
| `Plan.registrar` | `Address` | owns it. The identity, not the title |
| `Step.by` | `Address` | the account that added this step |
| `Edge.src` / `dst` | `u256` | **local** indices within the plan |
| `Edge.live` | `bool` | false for `unrelated` and for `cycle` |
| `Edge.why` | `str` | leader supplied, sanitised, **not** consensus |
| `Delegate.active` | `bool` | cleared on revoke, the row is kept |

Steps live in one flat array and the **local index** — the position within that
plan's filtered list — is what the graph and the layering speak in. A static test
asserts that `sequence()`, `overview()` and `blocked_by()` read `_live_edges()`
and never `self.edges` directly, because a `cycle` row treated as an edge would
build the very graph the contract declined to build.

Capped at **24** steps per plan, so the layering stays bounded.

## Authority

| Call | Who | Why |
|---|---|---|
| `plan` | anyone | no earlier owner to check against |
| `add` | registrar or active delegate | every step enters every later pairwise question |
| `authorise` / `revoke` | registrar | otherwise one delegation takes the plan over |
| `seal` | registrar | it is the author's plan to close |
| `order` | anyone | an author who chose which pairs got examined would examine only the ones suiting the sequence they wanted |

A delegate may add and may not authorise, revoke, or seal. Delegates are capped
at **16 active** per plan.

Sealing stops new steps and **does not stop ordering**. Fixing the contents is
exactly when working out the sequence becomes worth doing: a pair decided against
a plan that can still grow may be decided against a different plan tomorrow.

## API

```python
plan(title: str)
add(plan_id: u256, text: str)
authorise(plan_id: u256, who: str)
revoke(plan_id: u256, who: str)
seal(plan_id: u256)
order(plan_id: u256, a: u256, b: u256)

sequence(plan_id)             -> str       # "0|1,2|3"
blocked_by(plan_id, index)    -> str       # direct dependencies, pipe joined
overview(plan_id)             -> dict
edges_of(plan_id)             -> dict
step(plan_id, index)          -> dict
step_count(plan_id)           -> u256
registrar(plan_id)            -> str
may_add(plan_id, who: str)    -> bool
delegation(plan_id)           -> dict
count()                       -> u256
```

A pair may be decided **once**, in either presentation order: `_decided()` checks
both directions, so a caller cannot ask twice and keep whichever answer suited
them. Reads with an out-of-range **or negative** id raise a `UserError`.

## Reuse

[`lib/keystone_consensus.py`](lib/keystone_consensus.py) holds the pure rules
with no storage and no contract around them. It is **generated** by
`scripts/lift.py` from the contract, and `tests/test_logic.py` compares the two
parsed trees function by function, so a copied rule is always one a deployed
contract actually runs.

Two ideas are worth lifting. `settle()` folds the leader's own position bias into
the stored value before any node compares anything. `would_cycle()` is the other:
every edge in a loop was agreed by the network, and the set of them is still
impossible. **Agreement is not consistency**, and only the contract holds enough
state to tell the difference.
