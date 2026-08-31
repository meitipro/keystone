"""Mutation pass: break every safety property on purpose, confirm a test notices.

Passing tests prove nothing on their own. Each entry below is a small edit to
the contract that removes a defence. The suite must fail for every one of them,
and this script records WHICH test caught it, so the table in the README is
measured rather than claimed.

    python scripts/mutate.py            # run them all, print what caught what
    python scripts/mutate.py --md       # emit the markdown table for the README

An escaping mutation is a finding, not a nuisance. It means either a missing
test, or a later defence strict enough to cover a case an earlier test was
supposed to catch -- which leaves that earlier test unable to fail. A test that
cannot fail is worse than no test, because it reports coverage it does not
provide.

Run it with the same interpreter the suite uses. A global genlayer-test install
hijacks plain pytest collection and turns every result here into an unnamed
failure, which looks like success at a glance because everything is "caught".
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = "keystone.py"

MUTATIONS = [
    # -- the two presentation orders. Position bias is invisible to consensus
    # -- on its own, so every way of skipping the mirror produces a graph of
    # -- dependencies that are artefacts of prompt ordering.
    (
        "the mirror accepts an answer that does not invert",
        "    if flip(f) == r:\n        return f\n    return NEITHER",
        "    return f",
    ),
    (
        "flip made an identity, so every pair mirrors itself",
        "    if token == FIRST:\n        return SECOND\n    if token == SECOND:\n        return FIRST",
        "    if token == FIRST:\n        return FIRST\n    if token == SECOND:\n        return SECOND",
    ),
    (
        "the second presentation order never runs",
        "            rev = gl.nondet.exec_prompt(\n"
        "                build_prompt(title, text_b, text_a), response_format=\"json\"\n"
        "            )",
        "            rev = {\"order\": flip(normalise_token(fwd.get(\"order\", \"\")))}",
    ),
    (
        "an unusable answer settled as a real one",
        "    if f == \"\" or r == \"\":\n        return NEITHER",
        "    if f == \"\" or r == \"\":\n        return FIRST",
    ),

    # -- the cycle check, the half no model is involved in
    (
        "the cycle check removed, so the graph can contradict itself",
        "            if would_cycle(live_edges, src, dst, n):",
        "            if False:",
    ),
    (
        "the cycle check reads the wrong direction",
        "    return reaches(edges, b, a, n)",
        "    return reaches(edges, a, b, n)",
    ),
    (
        "reachability stops after one hop, so only direct reversals are caught",
        "        if len(nxt) == 0:\n            return False\n        frontier = nxt",
        "        return False",
    ),
    (
        "a refused edge is stored as live anyway",
        "                outcome, live = CYCLE, False",
        "                outcome, live = CYCLE, True",
    ),
    (
        "an unrelated pair is stored as a dependency",
        "            outcome, src, dst, live = UNRELATED, ai, bi, False",
        "            outcome, src, dst, live = UNRELATED, ai, bi, True",
    ),
    (
        "the live filter dropped, so refusals constrain the ordering",
        "            if int(e.plan_id) == target and bool(e.live):",
        "            if int(e.plan_id) == target:",
    ),
    (
        "the edge direction inverted for a `second` answer",
        "            src, dst = (ai, bi) if token == FIRST else (bi, ai)",
        "            src, dst = (ai, bi)",
    ),

    # -- the layering
    (
        "layers not sorted within a layer",
        "        ready = sorted(nxt)",
        "        ready = nxt",
    ),
    (
        "the first layer not sorted",
        "    ready = sorted([i for i in range(n) if indegree[i] == 0])",
        "    ready = [i for i in range(n) if indegree[i] == 0][::-1]",
    ),
    (
        "a cycle returns a partial order instead of nothing",
        "    if placed != n:\n        return None",
        "    if False:\n        return None",
    ),

    # -- agreement between nodes
    (
        "agreement loosened to \"we both found a dependency\"",
        "    return a == b",
        "    return (a == NEITHER) == (b == NEITHER)",
    ),
    (
        "opposite directions allowed to settle",
        "    return a == b",
        "    return a == b or flip(a) == b",
    ),
    (
        "the free structural layer removed",
        "            if not structurally_sound(theirs.get(\"token\", \"\"),\n"
        "                                      claimed_a, claimed_b, ai, bi):\n"
        "                return False\n",
        "",
    ),
    (
        "the pair check dropped, so an answer about another pair is accepted",
        "    return int(claimed_a) == int(a) and int(claimed_b) == int(b)",
        "    return True",
    ),
    (
        "an illegal token accepted from a prompt",
        "    if s in TOKENS:\n        return s\n    return \"\"",
        "    return s",
    ),
    # NOT listed: "the post-consensus token check dropped". By the time the
    # deterministic half runs, the validator's layer 1 has rejected any token
    # that is not one of the three, and layer 2 normalises both sides again
    # before comparing them. Removing it changes no outcome any single mutation
    # can reach, so no test can catch it and claiming one would be a lie. It
    # stays in the contract as the backstop for the case where both validator
    # layers are wrong at once. See DECISIONS.md.

    # -- the plan and its steps
    (
        "the same pair can be decided twice",
        "        if self._decided(plan_id, ai, bi):\n"
        "            raise gl.vm.UserError(\"this pair has already been decided\")\n",
        "",
    ),
    (
        "a pair only counts as decided in the order it was first asked",
        "            if (src == a and dst == b) or (src == b and dst == a):",
        "            if src == a and dst == b:",
    ),
    (
        "a step allowed to depend on itself",
        "        if ai == bi:\n            raise gl.vm.UserError(\"a step cannot come before itself\")\n",
        "",
    ),
    (
        "step bounds not checked, so a pair can name a step in another plan",
        "        if ai < 0 or bi < 0 or ai >= n or bi >= n:",
        "        if False:",
    ),
    (
        "the plan filter dropped, so every plan shares one step list",
        "            if int(s.plan_id) == target:\n                out.append((i, str(s.text)))",
        "            if True:\n                out.append((i, str(s.text)))",
    ),
    (
        "the step cap removed",
        "        if int(p.n_steps) >= MAX_STEPS:",
        "        if False:",
    ),
    (
        "a sealed plan still accepts steps",
        "        if bool(p.sealed):\n            raise gl.vm.UserError(\"this plan is sealed\")\n",
        "",
    ),

    # -- authority
    (
        "add left unauthenticated, so anyone may write into any plan",
        "        if not self._may_add(plan_id, p, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\n"
        "                \"only the registrar or an authorised delegate may add a step\"\n"
        "            )\n",
        "",
    ),
    (
        "the submitting address not recorded on the step",
        "                by=gl.message.sender_address,\n"
        "                text=body,",
        "                by=p.registrar,\n                text=body,",
    ),
    (
        "a revoked delegate still counted as authorised",
        "            if int(d.plan_id) == target and d.who == who and bool(d.active):",
        "            if int(d.plan_id) == target and d.who == who:",
    ),
    (
        "delegation not scoped to the plan it was granted on",
        "            if int(d.plan_id) == target and d.who == who and bool(d.active):",
        "            if d.who == who and bool(d.active):",
    ),
    (
        "a delegate allowed to appoint further delegates",
        "        if gl.message.sender_address != p.registrar:\n"
        "            raise gl.vm.UserError(\"only the registrar may authorise a delegate\")",
        "        if not self._may_add(plan_id, p, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\"only the registrar may authorise a delegate\")",
    ),
    (
        "a delegate allowed to revoke",
        "        if gl.message.sender_address != p.registrar:\n"
        "            raise gl.vm.UserError(\"only the registrar may revoke a delegate\")",
        "        if not self._may_add(plan_id, p, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\"only the registrar may revoke a delegate\")",
    ),
    (
        "a delegate allowed to seal the plan",
        "        if gl.message.sender_address != p.registrar:\n"
        "            raise gl.vm.UserError(\"only the registrar may seal a plan\")",
        "        if not self._may_add(plan_id, p, gl.message.sender_address):\n"
        "            raise gl.vm.UserError(\"only the registrar may seal a plan\")",
    ),
    (
        "may_add() drifting from the rule add() enforces",
        "        p = self._plan(plan_id)\n"
        "        return self._may_add(plan_id, p, Address(str(who).strip()))",
        "        self._plan(plan_id)\n        return True",
    ),
    (
        "the cap not re-checked when a revoked delegate is reactivated",
        "            if live >= MAX_DELEGATES:\n"
        "                raise gl.vm.UserError(\n"
        "                    f\"a plan is capped at {MAX_DELEGATES} active delegates\"\n"
        "                )\n"
        "            row.active = True",
        "            row.active = True",
    ),
    (
        "the cap counted in the same pass that finds the row",
        "            if d.who == addr:\n                found = i\n",
        "            if d.who == addr:\n                found = i\n                break\n",
    ),
    (
        "a malformed delegate address passed to Address()",
        "        if not looks_like_address(who):\n"
        "            raise gl.vm.UserError(\"that is not a 20 byte hex address\")\n"
        "        addr = Address(str(who).strip())\n"
        "        if addr == p.registrar:",
        "        addr = Address(str(who).strip())\n        if addr == p.registrar:",
    ),

    # -- reads and bounds
    (
        "the plan bounds check removed",
        "        if i < 0 or i >= len(self.plans):\n"
        "            raise gl.vm.UserError(\"no such plan\")\n",
        "",
    ),
    (
        "negative plan ids allowed through to Python list indexing",
        "        if i < 0 or i >= len(self.plans):",
        "        if i >= len(self.plans):",
    ),
    (
        "the reason sanitiser disabled",
        "        if ch in \"<>{}\\\\`\":\n            continue\n",
        "",
    ),
    (
        "control characters left in reasons",
        "        if ord(ch) < 32 or ord(ch) == 127:\n            ch = \" \"\n",
        "",
    ),

    # -- shape rules the runtime enforces and a green suite cannot see
    (
        "a nested mapping returned from the block",
        "                \"because\": sanitise_reason(fwd.get(\"because\", \"\")),",
        "                \"because\": {\"text\": sanitise_reason(fwd.get(\"because\", \"\"))},",
    ),
    (
        "a bool returned from the block",
        "                \"token\": token,",
        "                \"decided\": token != NEITHER,\n                \"token\": token,",
    ),
    (
        "a collection nested back into a storage dataclass",
        "@allow_storage\n@dataclass\nclass Step:\n    plan_id: u256",
        "@allow_storage\n@dataclass\nclass Step:\n    tags: DynArray[str]\n    plan_id: u256",
    ),
    (
        "an int storage field",
        "    plan_id: u256\n    by: Address\n    text: str",
        "    plan_id: int\n    by: Address\n    text: str",
    ),
    (
        "a storage field declared twice",
        "    edges: DynArray[Edge]\n    delegates: DynArray[Delegate]",
        "    edges: DynArray[Edge]\n    delegates: DynArray[Delegate]\n"
        "    delegates: DynArray[Delegate]",
    ),
    (
        "a prompt moved outside the block, which genvm-lint refuses",
        "        def leader_fn():\n            fwd = gl.nondet.exec_prompt(",
        "        fwd = gl.nondet.exec_prompt(\n"
        "            build_prompt(title, text_a, text_b), response_format=\"json\")\n\n"
        "        def leader_fn():\n            fwd = gl.nondet.exec_prompt(",
    ),
]


def run_one(label, find, replace):
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "repo"
        shutil.copytree(
            ROOT, dst,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git",
                                          "artifacts", "*.pyc"),
        )
        target = dst / "contracts" / TARGET
        src = target.read_text(encoding="utf-8")
        if find not in src:
            return "PATTERN NOT FOUND", None
        target.write_text(src.replace(find, replace, 1), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=dst, capture_output=True, text=True,
        )
        if proc.returncode == 0:
            return "ESCAPED", None

        text = proc.stdout + proc.stderr
        # A collection error counts as caught: a contract that will not import
        # is a contract that will not deploy.
        m = re.search(r"^(?:FAILED|ERROR) (\S+?)::(\S+?)(?:\[|\s|$)", text, re.M)
        if m:
            return "caught", m.group(2).split("::")[-1]
        m = re.search(r"^E\s+(\w*(?:Error|Exception))", text, re.M)
        if m:
            return "caught", m.group(1) + " at import"
        return "caught", "unnamed failure"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="emit the README table")
    args = ap.parse_args()

    rows, escaped = [], []
    for label, find, replace in MUTATIONS:
        status, test = run_one(label, find, replace)
        if status == "caught":
            rows.append((label, test))
            if not args.md:
                print("  caught   %-64s %s" % (label, test))
        else:
            escaped.append((label, status))
            print("  %-8s %s" % (status, label), file=sys.stderr)

    if args.md:
        print("| Mutation | Caught by |")
        print("|---|---|")
        for label, test in rows:
            print("| %s | `%s` |" % (label, test))
    else:
        print()
        print("  %d mutations, %d caught, %d escaped"
              % (len(MUTATIONS), len(rows), len(escaped)))

    return 1 if escaped else 0


if __name__ == "__main__":
    sys.exit(main())
