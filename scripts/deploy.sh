#!/usr/bin/env bash
#
# deploy.sh — deploy Keystone and leave real consensus evidence on the explorer.
#
#   ./scripts/deploy.sh studionet
#
# A contract page showing only a deploy transaction proves the file compiles and
# nothing else. This deploys AND exercises the contract, so the explorer shows
# method calls with the leader's proposal and the validators' votes beside them.
#
# It deliberately leaves a REFUSAL on chain. The third edge closes a loop, every
# edge in it was agreed by the network, and the contract declines to store it.
# That refusal is the strongest single artifact this repository can produce.
#
# Deployment can also be done entirely by hand through the Studio web interface
# at studio.genlayer.com, which is the recommended route: paste the contract,
# deploy, and call the methods through the form. Never put a private key into a
# file or hand one to a tool.
#
# Requires: npm i -g genlayer

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NETWORK="${1:-studionet}"
gold() { printf '\033[33m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

gold "Keystone -> $NETWORK"
# `network` is a command group, not a value: `genlayer network studionet`
# answers "unknown command" and exits 1, which under `set -e` kills the script
# on its first line.
genlayer network set "$NETWORK"

dim "linting"
# genvm-lint needs its subcommand, and utf-8 stdout: the linter prints a U+2713
# tick on success and dies encoding it under the cp1252 stdout Windows hands a
# child process, reporting a PASSING contract as failed.
PYTHONIOENCODING=utf-8 genvm-lint lint contracts/keystone.py

ADDR=$(genlayer deploy --contract contracts/keystone.py \
       | grep -oE '0x[0-9a-fA-F]{40}' | head -1)
gold "deployed at $ADDR"

# Real sentences, not placeholders. Steps with no content give the model nothing
# to reason about, so it answers differently on every run, the two presentation
# orders never mirror, and every pair settles to `neither`. A contract that
# refuses everything demonstrates nothing.
FREEZE="Freeze writes to the primary database and drain the outstanding queue."
MIGRATE="Run the schema migration against the primary database."
REPLICA="Repoint the read replicas at the migrated primary and resume traffic."
CHANGELOG="Publish the changelog entry describing the new schema to customers."

# --args is variadic. A JSON array is ONE argument, not the argument list, so
# `--args '[0,1]'` passes a single two-item array where the method wanted two
# parameters. Every value below is a separate token.
dim "plan()      open a plan"
genlayer write "$ADDR" plan --args "Database cutover, March" >/dev/null

dim "add()       four steps, in the order somebody happened to write them"
genlayer write "$ADDR" add --args 0 "$FREEZE"    >/dev/null
genlayer write "$ADDR" add --args 0 "$MIGRATE"   >/dev/null
genlayer write "$ADDR" add --args 0 "$REPLICA"   >/dev/null
genlayer write "$ADDR" add --args 0 "$CHANGELOG" >/dev/null

dim "order(0,1)  freeze before migrate -- expected a stored dependency"
genlayer write "$ADDR" order --args 0 0 1

dim "order(1,2)  migrate before replicas"
genlayer write "$ADDR" order --args 0 1 2

dim "order(0,3)  freeze vs changelog -- expected NEITHER, and that is an answer"
genlayer write "$ADDR" order --args 0 0 3

dim "sequence()  the layering derived from the graph, with no model involved"
genlayer call "$ADDR" sequence --args 0

# --- and now the refusal path, on chain -----------------------------------
dim "order(2,0)  replicas before freeze -- this would close a loop"
genlayer write "$ADDR" order --args 0 2 0
genlayer call  "$ADDR" edges_of --args 0
genlayer call  "$ADDR" overview --args 0

# --- the provenance model, on chain ---------------------------------------
dim "authorise() a delegate, then revoke it"
genlayer write "$ADDR" authorise --args 0 "0x7777777777777777777777777777777777777777" >/dev/null
genlayer call  "$ADDR" delegation --args 0
genlayer write "$ADDR" revoke --args 0 "0x7777777777777777777777777777777777777777" >/dev/null

cat <<TXT

  Contract:  $ADDR
  Explorer:  https://explorer-studio.genlayer.com/address/$ADDR

Before submitting, prove the address is evidence for THIS repository:

  python scripts/verify_deployment.py $ADDR

It reads the source back out of the deploy transaction, diffs it against
contracts/keystone.py, and lints those bytes. A correct repository proves nothing
on its own if the address points at an earlier draft.

The page should show three stored outcomes and one refusal: two dependencies, one
unrelated pair, and a cycle the contract declined to close.

Then paste the address into README.md and SUBMISSION.md where {address} appears.

TXT
