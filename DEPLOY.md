# Deploying Keystone

Everything you need is on this page. Deploy through the Studio web interface at
**studio.genlayer.com** — paste the contract, deploy, and call the methods
through the form. Never put a private key into a file or hand one to a tool.

**Do this one last.** It is the one most likely to need a fix before it is worth
submitting, and the checkpoint below is the reason.

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

## 2 · Run the demo

Eleven writes.

### Open a plan and add four steps

| # | Method | Field | Value |
|---|---|---|---|
| 1 | `plan` | `title` | `Database cutover, March` |
| 2 | `add` | `plan_id` | `0` |
| | | `text` | `Freeze writes to the primary database and drain the outstanding queue.` |
| 3 | `add` | `plan_id` | `0` |
| | | `text` | `Run the schema migration against the primary database.` |
| 4 | `add` | `plan_id` | `0` |
| | | `text` | `Repoint the read replicas at the migrated primary and resume traffic.` |
| 5 | `add` | `plan_id` | `0` |
| | | `text` | `Publish the changelog entry describing the new schema to customers.` |

### Three pairs — `order` takes **three** fields

| # | `plan_id` | `a` | `b` | meaning |
|---|---|---|---|---|
| 6 | `0` | `0` | `1` | freeze before migrate |
| 7 | `0` | `1` | `2` | migrate before replicas |
| 8 | `0` | `0` | `3` | freeze before changelog |

> ### ⛔ Stop here. This is the highest-risk step in all three contracts.
>
> Read `sequence(0)`.
>
> - **`0|1|2,3`** or anything with a `|` in it — edges were stored. Carry on to
>   step 9.
> - **`0,1,2,3`** — **stop, and do not run step 9.** Nothing was stored: every
>   pair came back `neither`. Send me `edges_of(0)` and I will fix the prompt or
>   the demo data before you go further.
>
> Step 9 only produces a cycle if steps 6 and 7 actually stored edges. Run
> against an empty graph it stores an ordinary dependency, and the whole point
> of the demo disappears.

### The refusal

| # | Method | `plan_id` | `a` | `b` |
|---|---|---|---|---|
| 9 | `order` | `0` | `2` | `0` |

This says "replicas before freeze", which closes the loop 0 → 1 → 2 → 0. Every
one of those three edges was agreed by the network; together they are not an
ordering. No single answer was wrong, and the contract refuses anyway. That is
the finding this whole contract exists to produce.

### The provenance model, on chain

| # | Method | Field | Value |
|---|---|---|---|
| 10 | `authorise` | `plan_id` | `0` |
| | | `who` | `0x7777777777777777777777777777777777777777` |
| 11 | `revoke` | `plan_id` | `0` |
| | | `who` | `0x7777777777777777777777777777777777777777` |

---

## 3 · Reads — free, no transaction

| Call | Argument | Expect |
|---|---|---|
| `sequence` | `0` | unchanged by step 9 — a refused edge constrains nothing |
| `edges_of` | `0` | the fourth pair reads `outcome: cycle`, `live: false` |
| `overview` | `0` | `dependencies 2, unrelated 1, cycles_refused 1` |
| `blocked_by` | `0`, `1` | `0` |
| `delegation` | `0` | the registrar, and one revoked delegate |

---

## 4 · Before the portal

```bash
python scripts/verify_deployment.py 0xYourAddress
```

Reads the source back out of the deploy transaction, diffs it against
`contracts/keystone.py`, and runs `genvm-lint lint` on those bytes. It must
print **"The address is evidence for this repository. Safe to submit."**

If it prints anything else, do not submit that address.

---

## 5 · Send the address

Send it over and I will read the state back off the chain, confirm the outcomes
above, fill the `{address}` placeholders, write the on-chain section from what
the chain actually returned, and push.

**Nothing goes near the portal until that check is green.**
