# Submission

One submission, under **Builder → Intelligent Contracts**. This repository is one
standalone primitive.

---

## Before you submit, in order

1. **Measure, do not estimate.**

   ```bash
   python scripts/measure.py --write
   ```

   Runs the suite, runs the full mutation pass, and writes both numbers into
   README.md. It refuses to write anything if the suite is red or a mutation
   escapes, so a number in the README is always one that was checked.

2. **Deploy and exercise.** Through the Studio web interface at
   studio.genlayer.com, or `./scripts/deploy.sh studionet` for the CLI route.
   Never put a private key into a file.

3. **Put a refusal on chain, not only a success.** The story the script tells is
   the submission: two dependencies are stored, one pair comes back `neither`,
   and the fourth pair would close a loop — every edge in it agreed by the
   network — so the contract refuses it and records the cycle. A page showing
   only successes proves the file compiles and nothing else.

4. **Prove the address is evidence for this repository.**

   ```bash
   python scripts/verify_deployment.py 0xYourAddress
   ```

   Reads the source back out of the deploy transaction on chain, diffs it against
   `contracts/keystone.py`, and runs `genvm-lint lint` on those bytes. **A
   submission is judged on the deployed source**, so a correct repository proves
   nothing on its own if the address points at an earlier draft. Exits non-zero
   if either check fails.

5. **Open the explorer page and check it.** It must show a Deploy transaction
   **and** method calls with a Consensus Result beside them, and no failed or
   abandoned transaction.

6. **Paste the address** into README.md and into this file, then push.

7. **Upload `brand/social.png`** under Settings → General → Social preview, if
   the repository has one. GitHub has no API for this.

---

## On chain

Deployed and exercised on studionet at
[`0x3D9fb402946e4e34DfA9c9D85feFB980033AD33C`](https://explorer-studio.genlayer.com/address/0x3D9fb402946e4e34DfA9c9D85feFB980033AD33C).
Twenty-five transactions, every one `FINALIZED`, no failed or abandoned
transaction on the page. Every value below was read back from the chain with
view calls afterwards, not copied from a local run.

Three plans, because one plan cannot demonstrate both a working ordering and a
refusal: a plan with a real sequence has no honest answer that closes a loop.

### Plan 0 — a database cutover, ordered

Four steps, three pairs asked.

| Pair | Outcome | Stored |
|---|---|---|
| freeze, migrate | dependency | freeze before migrate |
| migrate, replicas | dependency | migrate before replicas |
| freeze, changelog | `unrelated` | nothing |

`sequence(0)` is `0,3|1|2`: freeze and the changelog can both start now, the
migration waits on the freeze, the replicas wait on the migration.

The changelog pair is not a failure. The contract is built to answer `neither`
unless one step genuinely cannot begin until the other is done, so a pair that
is merely thematically related gets no edge. A primitive that invented one to
look decisive would be worse than useless here.

### Plan 2 — a vendor selection that cannot be sequenced

Three steps, each naming another step's output as its own input.

```
[0] Assemble the vendor shortlist from the finished risk assessment.
[1] Complete the risk assessment from the finished pricing sheet.
[2] Fill in the pricing sheet from the finished vendor shortlist.
```

| Pair | Outcome | Leader's stored reason |
|---|---|---|
| 0, 1 | `after`, live | "the first step requires a finished risk assessment, which is the output produced by the second step" |
| 1, 2 | `after`, live | "the pricing sheet must be filled in first before a risk assessment can be completed from it" |
| 2, 0 | **`cycle`**, dead | "pricing sheet needs the finished vendor shortlist, so assembling the shortlist must be completed before pricing can start" |

**Read the third reason again. It does not mention a cycle.** The model was
asked about two steps, answered the question it was asked, and was right: read
alone, that pair really does run the shortlist before the pricing sheet. Each of
the three answers is correct on its own. The three together are not an ordering.

Only the contract holds all of them at once, which is the entire argument for
putting `would_cycle()` in the contract rather than in a client. Consensus on
each pair separately cannot see it — five nodes agreeing on each edge produce
exactly the same impossible loop, with more confidence.

The refused edge is stored with `live: false` and constrains nothing.
`sequence(2)` is still `2|1|0`, unchanged by the third pair, and `overview(2)`
reads `cycles_refused: 1`.

### Plan 1 — what it cost to get there, and why it is worth reading

Plan 1 was an earlier attempt at the same demonstration and it failed. Its steps
each said *"This cannot start until X is finished"*, and on the pair that should
have closed the loop the model answered:

> "Circular dependency: each step requires the other first, so neither can
> actually start. Both are mutually blocked."

So it returned `neither`, the contract stored `unrelated`, and no cycle was
recorded. The wording made the loop visible from inside a single pair, and the
model refused a direction rather than giving one.

That is the opposite of what this primitive is for, and it is left on the
contract deliberately. Plan 1 and plan 2 encode the same circular dependency.
The difference is that plan 2's steps state only their own input, so each pair
has an unambiguous direction and the loop appears only when all three are held
together. **The demonstration requires that no single pair reveals the cycle** —
which is the thesis restated as a constraint on the data.

### The provenance model

`delegation(0)` returns the registrar plus one revoked delegate. A revoked row is
kept rather than deleted, so a delegation that existed stays visible, and every
step and every pair stores the account that submitted it.

### Reproducing the check

```bash
python scripts/verify_deployment.py 0x3D9fb402946e4e34DfA9c9D85feFB980033AD33C
```

Reads the source out of the deploy transaction, compares it to
`contracts/keystone.py`, and runs `genvm-lint lint` on those bytes. It reports
the deployed source as identical: pasting into the Studio editor rewrote the
line endings and dropped the final newline, and nothing runs either of those.

---

## Title

```
Keystone: an ordering built one pair at a time, that cannot contradict itself
```

## Notes

```
Keystone accumulates "this must come before that" from prose, one pair at a time, and refuses any judgment that would contradict the ones it already holds. Ask a model to sort a plan and it returns a confident sequence, a different one each run, and nothing checks whether the sequence is even possible; ask it about every pair independently and it will tell you a before b, b before c, and c before a. No single answer is wrong and the set is impossible, and consensus on each pair separately cannot see it, because five nodes agreeing on each edge produce exactly the same loop. So the block answers one of three tokens about two rows the contract holds, asked in both presentation orders so that position bias is stored as neither rather than forgiven at comparison time, and the contract runs the cycle check, the layering and the refusal with no model involved at all.
```

## Links

```
GitHub:   https://github.com/meitipro/keystone
Contract: https://github.com/meitipro/keystone/blob/main/contracts/keystone.py
Spec:     https://github.com/meitipro/keystone/blob/main/CONTRACTS.md
Decisions https://github.com/meitipro/keystone/blob/main/DECISIONS.md
Tests:    https://github.com/meitipro/keystone/tree/main/tests
Explorer: https://explorer-studio.genlayer.com/address/0x3D9fb402946e4e34DfA9c9D85feFB980033AD33C
```

---

## What clears the bar, line by line

The category rejects "thin LLM wrappers" and "generic AI decides X demos".

- **The model never produces an ordering.** It answers three-way multiple choice
  about two rows, twice. The graph, the reachability search, the cycle
  detection, the refusal, and the layering with its tie-break are deterministic
  and involve no model at all.
- **The contract can overrule a thing the network agreed to.** Every edge in a
  refused cycle passed consensus. Agreement is not consistency, and only the
  contract holds enough state to tell the difference. That is the strongest
  single claim in this repository.
- **Uncertainty is in the value, not the comparison.** A pair whose two
  presentation orders disagree is stored as `unrelated`. There is no tolerance
  anywhere in the agreement rule.
- **The validator function is the contribution.** A free structural check that
  also confirms the answer is about the pair that was asked, then exact equality
  on the token. Explained in [CONTRACTS.md](CONTRACTS.md) with the code.
- **Refusing is designed.** `neither` and `cycle` are the outputs this primitive
  exists to produce, and a refusal is kept rather than deleted.
- **Every write is bound to an address.** A static test asserts it for the
  methods nobody has written yet.
- **The tests have teeth.** The mutation table in the README is generated by a
  script that refuses to emit a table if anything escapes, and the simulator can
  model a leader that lies, which is the only way to exercise the checks a
  validator runs against a peer it does not trust.
- **It runs with nothing installed.** `pip install pytest && pytest tests/ -q`.
  A reviewer with two minutes can verify the whole thing.

## The one line worth putting first

**Consensus agreed to every edge, and the set of them was still impossible.**
Everything else in the design follows from that sentence.
