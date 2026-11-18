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
The checkout must be clean and on its recorded branch. Its source branch and
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
creation evidence, including `phase: publishing`. Only its **local attempt**
becomes `state: abandoned`. Its additive `recovery_*` receipt records contract,
reason, actor, time, confirmed revision/source, upstream and optional existing
merged association. It never writes a provider number, URL or first-push head.
JSON reports `creation_reconciled: true`, `publication_outcome: unknown`,
`creation_cancelled: false`, `provider_closed: false`, and
`claim_released: false`.

The existing FinalizeLock, publication authority, metadata/publish locks and
fresh revision-bound record write serialize against current publishers and
late callbacks. A stale writer cannot resurrect the retired attempt. This does
not cancel an independently accepted provider request or make an unknown
transport outcome known; the retained evidence remains historical truth.

Ordinary finalization rechecks receipt/incarnation validity, destination,
all-state provider/remote observations and strict source/ref ancestry. It still
checks all other PRs, dirty content, obligations and cleanup authority.
New effects, unknown observations, new work or drift hold finalization. No
`--force-open-pr` is required or supplied by this recovery path.

Source acceptance is the contained disposable-Git/CLI packet
`tests/test_pr_creation_reconcile.py`, the provider adapter controls
`tests/test_github_head_reconciliation.py`, and unchanged cancellation,
first-push and publication-state regressions. These are not installed-runtime,
native lifecycle, production recovery or deployment evidence.
