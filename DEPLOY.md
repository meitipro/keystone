# Deploying Keystone

Everything you need is on this page. Deploy through the Studio web interface at
**studio.genlayer.com** — paste the contract, deploy, and call the methods
through the form. Never put a private key into a file or hand one to a tool.

Seventeen transactions. Two plans: one with a real ordering, one built to
contain a circular dependency, because a single plan cannot demonstrate both --
a plan with a real sequence has no honest answer that closes a loop.

---

## 1 · Get the contract

Open the raw file and copy all of it:

**https://raw.githubusercontent.com/meitipro/keystone/main/contracts/keystone.py**

Take it from that link, not from a local copy. What gets deployed has to be the
file in this repository, byte for byte — the reviewer reads the deployed source
back off the chain and diffs it, and a submission has been rejected for nothing
but a stale address with the fix already sitting in the repo.

Paste it into Studio and deploy. **The constructor takes no arguments.**

---

## 2 · Plan 0 — a plan with a real ordering

This half shows three things: a stored dependency, a pair the contract declines
to order, and a layering derived from the graph with no model involved.

### Open it and add four steps

| # | Method | Field | Value |
|---|---|---|---|
| 1 | `plan` | `title` | `Database cutover, March` |
| 2 | `add` | `plan_id` | `0` |
| | | `text` | `Freeze writes to the primary database and drain the outstanding queue.` |
| 3 | `add` | `plan_id` | `0` |
| | | `text` | `Run the schema migration against the primary database. This cannot start until writes are frozen and the queue is drained.` |
| 4 | `add` | `plan_id` | `0` |
| | | `text` | `Repoint the read replicas at the migrated primary. This cannot start until the schema migration is finished.` |
| 5 | `add` | `plan_id` | `0` |
| | | `text` | `Publish the changelog entry describing the new schema to customers.` |

> **Why the wording is like that.** The prompt asks whether one step has to be
> *finished* before the other can *start*, and it is told to answer `neither`
> unless one genuinely cannot begin until the other is done. Steps 3 and 4 say
> exactly that, in those words. Two earlier drafts of this demo left the
> dependency implied and every pair came back `unrelated` — once on a pair whose
> own stored reason spelled the dependency out. The contract was right both
> times; the demo has to supply a dependency that is unambiguous.
>
> Step 5 deliberately says nothing about waiting. It is there to be `unrelated`,
> and that is an answer rather than a failure.

### Decide three pairs

`order` takes **three** fields.

| # | Method | `plan_id` | `a` | `b` | Expect |
|---|---|---|---|---|---|
| 6 | `order` | `0` | `0` | `1` | dependency: freeze before migrate |
| 7 | `order` | `0` | `1` | `2` | dependency: migrate before replicas |
| 8 | `order` | `0` | `0` | `3` | `unrelated` — the changelog waits on nothing |

**Wait for each to reach `FINALIZED` before reading anything.** An `order` call
runs two prompts, so it takes longer than a plain write, and a read taken while
it is still `ACCEPTED` or `COMMITTING` shows the state from before it.

### Read it back — free, no transaction

| Call | Argument | Expect |
|---|---|---|
| `overview` | `0` | `dependencies 2, unrelated 1, cycles_refused 0` |
| `sequence` | `0` | `0,3\|1\|2` — freeze and the changelog can both start now |
| `blocked_by` | `0`, `2` | `1` |

---

## 3 · Plan 1 — a plan that cannot be ordered at all

Plan 0 has a real ordering, so no honest answer closes a loop on it. The cycle
needs a plan where each step consumes what the next one produces.

### Open it and add three steps

| # | Method | Field | Value |
|---|---|---|---|
| 9 | `plan` | `title` | `Vendor selection, Q4` |
| 10 | `add` | `plan_id` | `1` |
| | | `text` | `Assemble the vendor shortlist from the finished risk assessment.` |
| 11 | `add` | `plan_id` | `1` |
| | | `text` | `Complete the risk assessment from the finished pricing sheet.` |
| 12 | `add` | `plan_id` | `1` |
| | | `text` | `Fill in the pricing sheet from the finished vendor shortlist.` |

> ### The one rule that makes this work
>
> **Each step states only its own input. No pair may reveal the cycle.**
>
> Every step names one artifact it consumes, and that artifact is another step's
> output. Read any two of them together and exactly one dependency is visible,
> pointing one way, with the third artifact nowhere in sight. The loop exists
> only across all three.
>
> That is not a stylistic preference, it is the thesis restated as a constraint
> on the data. This contract exists because no single answer is wrong and the
> set is impossible, so a demo where a single pair betrays the loop is testing
> something else.
>
> An earlier attempt wrote every step as *"this cannot start until X is
> finished"*. On the pair that should have closed the loop, the model answered
> **"circular dependency: each step requires the other first, so neither can
> actually start"** and returned `neither`. It refused one layer above the
> refusal this contract is for, and no cycle was ever recorded. That plan is
> still on the live contract as plan 1 of the original run, if you want to read
> the difference.
>
> Avoid famous circular tropes too. API spec, data model and database schema are
> a known interdependent trio and the model has a prior for it; procurement
> artifacts do not.

### Build the chain

| # | Method | `plan_id` | `a` | `b` | Stores |
|---|---|---|---|---|---|
| 13 | `order` | `1` | `0` | `1` | 1 → 0 |
| 14 | `order` | `1` | `1` | `2` | 2 → 1 |

> ### ⛔ Stop here. This is the step everything else depends on.
>
> Wait for both to reach `FINALIZED`, then read `overview` with `plan_id` = `1`.
>
> - **`dependencies` is `2`**, and `sequence(1)` is `2|1|0` — the chain exists.
>   Carry on.
> - **anything less** — **do not run step 15.** Send `edges_of(1)`.
>
> Step 15 closes a loop **only if that chain exists**. Without it there is
> nothing to close: the call stores an ordinary edge, the refusal never happens,
> and the one thing this contract is for is missing from the page.
>
> Count the dependencies, not the pipes. An earlier version of this page said to
> look for a `|` in `sequence`, which is not the same test — a single edge
> anywhere produces a `|` while leaving the chain unformed. That mistake was
> made on a live run: `sequence` read `0,1,3|2`, passed the `|` test, and the
> cycle step then stored a plain dependency instead.

### Close the loop

| # | Method | `plan_id` | `a` | `b` |
|---|---|---|---|---|
| 15 | `order` | `1` | `2` | `0` |

The pricing sheet is filled in from the finished shortlist, so this wants to
store 0 → 2. The graph already holds 2 → 1 → 0, so 0 → 2 would close it.

Every one of those three answers is correct read on its own — the leader's
stored reason for this one does not even mention a cycle, it just says the
shortlist must be finished before the pricing sheet. Together they are not an
ordering. **The contract refuses.**

## 4 · The provenance model, on chain

| # | Method | Field | Value |
|---|---|---|---|
| 16 | `authorise` | `plan_id` | `0` |
| | | `who` | `0x7777777777777777777777777777777777777777` |
| 17 | `revoke` | `plan_id` | `0` |
| | | `who` | `0x7777777777777777777777777777777777777777` |

A revoked delegate keeps its row, so a delegation that existed stays visible.

---

## 5 · The evidence to check before submitting

Read these. None costs a transaction.

| Call | Argument | Expect |
|---|---|---|
| `overview` | `0` | `dependencies 2, unrelated 1, cycles_refused 0` |
| `sequence` | `0` | `0,3\|1\|2` |
| `overview` | `1` | `dependencies 2, unrelated 0, **cycles_refused 1**` |
| `sequence` | `1` | `2\|1\|0` — **unchanged by step 15**, a refused edge constrains nothing |
| `edges_of` | `1` | the third pair reads `outcome: cycle`, `live: false`, and its stored reason does not mention a cycle |
| `delegation` | `0` | the registrar, and one revoked delegate |

**`cycles_refused` on plan 1 must be `1`.** That is the single artifact this
whole contract exists to produce. If it is `0`, the demo has not demonstrated
anything the tests do not already cover, and the page is worth less than the
repository.

Then:

```bash
python scripts/verify_deployment.py 0xYourAddress
```

Reads the source back out of the deploy transaction, diffs it against
`contracts/keystone.py`, and runs `genvm-lint lint` on those bytes. It must
print **"The address is evidence for this repository. Safe to submit."**

Line endings and a missing trailing newline are reported as cosmetic and do not
block: pasting into the Studio editor rewrites both, and nothing runs either.

---

## 6 · Done

This has been run. The contract is live at
[`0x3D9fb402946e4e34DfA9c9D85feFB980033AD33C`](https://explorer-studio.genlayer.com/address/0x3D9fb402946e4e34DfA9c9D85feFB980033AD33C),
twenty-five transactions, every one finalized, and `cycles_refused` on the third
plan is 1. The state read back off the chain is written up in
[SUBMISSION.md](SUBMISSION.md#on-chain).

**The demonstration took three plans to get right, and the reason is worth
carrying forward.** A pair must have an unambiguous direction when read ALONE,
and the loop must appear only when all three are held together. An earlier plan
worded every step as "this cannot start until X is finished", which made the
loop visible from inside a single pair; the model saw it, answered "circular
dependency, both are mutually blocked", and returned neither. Steps that state
only their own input avoid that: each pair reads as one step producing what the
other consumes, and nothing in a pair reveals the cycle.

That constraint is the thesis restated as a rule about the data.

---

One step stays manual: uploading `brand/social.png` under
Settings → General → Social preview. GitHub has no API for it.
