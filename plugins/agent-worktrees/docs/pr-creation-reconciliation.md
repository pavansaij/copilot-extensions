# Retiring an ambiguous legacy local PR attempt

This is **not** never-started cancellation, provider closure or merge. It is an
explicit owner-mediated local disposition for an owner-stamped legacy
`creating` / `creation.phase: publishing` reservation that lacks the durable
prepared first-push source. Its original transport outcome remains **unknown**.
Use ordinary publication recovery when prepared-source evidence exists, and
[cancellation](pr-creation-cancellation.md) only for an eligible never-started
attempt. Neither empty provider fields nor a clean checkout establishes eligibility.

## Discover support from the executing runtime

The selected executable's `pr-status <worktree-id> --all --no-live --json`
advertises
`creation_reconciliation_contract: agent-worktrees.pr-creation-reconciliation.v1`.
It exposes immutable `pr_id`, `pr_revision` and the retained `creation` evidence.
Package versions, newer payload help and another installation do not establish
support. Missing declaration means unknown support: keep the original attempt.
Old executables strictly reject the new arguments; do not retry an effectful
invocation with guessed legacy syntax.

Existing numbered abandonment and `--creation` cancellation are unchanged.
This provider-first expansion does not activate a caller, update an installation
or authorize a live recovery. No old syntax is retired. Compatible readers
preserve the additive string receipt through the existing serialization owner.
A rollback that loses it loses reconciliation proof; retain the record and
select a capable runtime through an independently authorized update, rather
than fabricate provider state or force finalization.

## Prerequisites and scope

Only the unchanged owning worktree incarnation, frozen attribution, immutable
attempt and same-repository GitHub destination are supported in version 1.
The owner may be `active`, `complete` (including legacy `completed`) or `pushed`; closing and finalized owners
are not admitted. Both loaded snapshots must pass the native execution-space
mutation guard.
The checkout must be the exact recorded Git root, share the configured anchor's
common Git directory, and be clean and on its recorded branch. Untracked files
and dirty submodules cannot be hidden by Git configuration. Ancestry checks ignore
replacement objects. Its source branch and
**every existing tracked local PR branch** must be ancestors of the configured
remote default branch. The command never resets, rebases, deletes or archives
source. That tracking ref must match the freshly observed remote tip at the
unchanged destination; unavailable/stale observations require normal sync, not
an inferred landing. Tree equality and an operator's assertion of semantic equivalence are
not substitutes for that Git ancestry check.

If a historical planning/source ref is superseded but not an ancestor, stop.
Preserve useful history and evidence, obtain explicit authority for that exact
local ref reconciliation, and use its existing Git owner before reconsidering
this command. Retirement does not supply that authority or perform the change.

The command requires a successful all-state exact-head provider observation:

* **No PR:** the result must be explicitly empty and the remote head absent.
  This describes the current observation, **not** a historical never-published
  fact or permission to replay an unknown effect.
* **Duplicate reservation:** `--merged-pr <number>` must name a separate proper,
  already tracked merged association for the exact same branch, repository and
  provider. The provider must return exactly that one PR with its exact merged
  head and same-repository source. The remote ref must be absent or equal that
  merged head. The original reservation is not reassigned to that PR.

An open PR, multiple results, unsupported provider, incomplete/failed reads,
changed remote/endpoint, active publisher, prepared-source attempt or authority
drift refuses or waits on the existing bounded locks. Missing owner stamps
cannot be reconstructed from branch names or source equality.

## Confirm one exact attempt

First request the alternatives-first warning; this does not retire anything:

```text
agent-worktrees pr-abandon <worktree-id> --reconcile-creation <pr-id> --reason "<specific reason>"
```

Only after explicit approval for that attempt, revision and source:

```text
agent-worktrees pr-abandon <worktree-id> --reconcile-creation <pr-id> --expected-revision <revision> --expected-head <full-commit> --reason "<specific reason>" --confirm --json
```

Add `--merged-pr <number>` only for the duplicate-reservation case above.
Do not combine this selector with `--creation`, `--pr` or a repository override.
Revision/source drift requires renewed qualification, not an automatic changed
confirmation. An identical retry returns the original receipt without rewriting it.

## Receipt and subsequent safety

The existing record retains its immutable ID, frozen attribution and original
creation evidence, including `phase: publishing`. Its **local disposition**
becomes retired, not merged or provider-closed. The persisted compatibility
hold remains `state: creating` with an empty actionable `branch`; the exact
original branch is retained as `creation.recovery_branch` and is still checked
for source ancestry and ordinary local-branch cleanup. No Git ref is changed by
retirement. The additive `recovery_*` receipt records contract, reason, actor,
time, confirmed revision/source, upstream and optional existing merged
association. It never writes a provider number, URL or first-push head.
JSON reports `creation_reconciled: true`, `publication_outcome: unknown`,
`local_disposition: retired`, `creation_cancelled: false`, `provider_closed: false`, and
`claim_released: false`.

This wire hold is intentional: the prior numberless healer has no actionable
branch to look up, and the prior finalization backup gate still sees a live
creation hold even with PR mode disabled. A capable runtime alone interprets a
complete, requalified receipt as locally settled. Losing some or all receipt
fields keeps the hold; it does not turn the attempt into a merged or untracked
PR. Pre-existing numberless abandoned records are not relabeled by this rule.
Never use an older override or manufacture a provider association to clear it.

The existing lifecycle leases exclude guarded source publication, source
completion and final cleanup throughout qualification. Delegated publication
leases both its caller and any actual managed source owner, in stable order,
and revalidates both. The canonical Git transport retains an exact
destination/head fence through transport and changes that head's opaque
invalidation generation before every attempt, including unknown/failed outcomes.
Unrelated heads retain transport concurrency. That value
is not permission, evidence of a successful push, or a parallel PR ledger.
Reconciliation refuses active or intervening publication. Slow remote
observations hold neither clone-wide publication locks nor installation authority.
The commit boundary acquires authority, then publication, then metadata locks,
rechecks destination/source and both native execution-space snapshots, and
performs a fresh revision-bound record write. A stale writer cannot resurrect
the retired attempt. This does
not cancel an independently accepted provider request or make an unknown
transport outcome known; the retained evidence remains historical truth.

Ordinary finalization, even after PR mode is disabled, collects complete
provider/remote observations before acquiring cleanup locks. An operation-scoped
snapshot is then checked against the unchanged publication generation,
receipt/incarnation, destination and strict source/ref ancestry under the short
cleanup fence. It performs no retirement remote probes under the record or
finalization lock, and never reuses a snapshot from another operation. Source
Git probes are bounded and process-tree-aware. It still
checks all other PRs, dirty content, obligations and cleanup authority.
New effects, unknown observations, new work or drift hold finalization. No
`--force-open-pr` is required or supplied by this recovery path.

Partial recovery fields and stripped compatibility holds remain
qualification-required. Numberless provider healing and ordinary publication
must not replace or replay this local disposition as a different association.
Legitimate later work can use explicit `create-pr --new` with a distinct head;
the original retired attempt remains unchanged and that new work must land
before finalization. A damaged receipt remains held rather than being bypassed
through a fresh publication.

Source acceptance is the contained disposable-Git/CLI packet
`tests/test_pr_creation_reconcile.py`, the provider adapter controls
`tests/test_github_head_reconciliation.py`, and unchanged cancellation,
first-push and publication-state regressions. These are not installed-runtime,
native lifecycle, production recovery or deployment evidence.
