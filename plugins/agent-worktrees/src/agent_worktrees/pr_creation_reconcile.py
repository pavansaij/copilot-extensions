"""Owner-confirmed retirement of an ambiguous legacy publication attempt.

The original publication evidence remains untouched. Retirement says nothing
about the outcome of its transport, and never creates a provider association.
"""

from __future__ import annotations

import getpass
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from . import config as cfg, git_ops, pr_authority, pr_creation_state as state
from . import pr_publication_state, pr_publish, providers, tracking
from .finalize_lock import FinalizeLock

CONTRACT = "agent-worktrees.pr-creation-reconciliation.v1"
_KEYS = {
    "recovery_contract", "recovery_reason", "recovery_actor", "recovery_at",
    "recovery_revision", "recovery_head", "recovery_upstream", "recovery_merged_pr",
}


def _original(pr: tracking.PRRecord) -> tracking.PRRecord:
    return replace(
        pr, state="creating", closed_at="",
        creation={k: v for k, v in pr.creation.items() if k not in _KEYS},
    )


def _legacy(pr: tracking.PRRecord, record: tracking.WorktreeRecord | None = None) -> bool:
    return bool(
        set(pr.creation) == state._RESERVATION_KEYS
        and state._bound(pr) and pr.creation["phase"] == "publishing"
        and pr_publication_state.unpublished(pr)
        and (record is None or pr.creation["owner"] == state.owner(record))
    )


def retired(pr: tracking.PRRecord) -> bool:
    """Recognize only a complete local receipt, never a provider merge."""
    if not getattr(pr, "creation", None) or not (
        set(pr.creation) == state._RESERVATION_KEYS | _KEYS
        and pr.creation.get("recovery_contract") == CONTRACT
        and pr.state == "abandoned" and pr.closed_at == pr.creation["recovery_at"]
        and _legacy(_original(pr))
        and all(pr.creation[k].strip() for k in _KEYS - {"recovery_merged_pr"})
    ):
        return False
    revision = pr.creation["recovery_revision"]
    return revision.isascii() and revision.isdecimal() and int(revision) + 1 == pr.pr_revision


def _source(record: tracking.WorktreeRecord, repo: Any, *, expected_head: str = "") -> str:
    cwd = record.worktree_path
    if git_ops.git("status", "--porcelain", cwd=cwd, isolated_repository=True).stdout.strip():
        raise ValueError("Dirty source is not eligible; retain the attempt.")
    branch = git_ops.git("symbolic-ref", "--short", "HEAD", cwd=cwd, isolated_repository=True).stdout.strip()
    if branch != record.branch:
        raise ValueError("The owning checkout is not on its recorded branch.")
    head = git_ops.git("rev-parse", "--verify", "HEAD^{commit}", cwd=cwd, isolated_repository=True).stdout.strip()
    if expected_head and head != expected_head:
        raise ValueError("Source HEAD changed from the explicitly confirmed --expected-head.")
    upstream = f"refs/remotes/{repo.remote}/{repo.default_branch}"
    refs = {record.branch, *(p.branch for p in record.prs if p.branch)}
    for ref in refs:
        exists = git_ops.git(
            "show-ref", "--verify", "--quiet", f"refs/heads/{ref}", cwd=cwd,
            check=False, isolated_repository=True,
        )
        if exists.returncode == 1 and ref != record.branch:
            continue
        if exists.returncode or git_ops.git(
            "merge-base", "--is-ancestor", f"refs/heads/{ref}", upstream, cwd=cwd,
            check=False, isolated_repository=True,
        ).returncode:
            raise ValueError(
                "Every owned local source/PR ref must be reachable from upstream. "
                "Preserve useful history and obtain explicit authority before reconciling "
                "a superseded ref; tree equality is not semantic-source proof."
            )
    return head


def finalization_error(record: tracking.WorktreeRecord, repo: Any) -> str | None:
    """A retained local disposition never waives later source or owner drift."""
    selected = [
        p for p in (getattr(record, "prs", None) or [])
        if "recovery_contract" in getattr(p, "creation", {})
    ]
    if not selected:
        return None
    try:
        for pr in selected:
            if not retired(pr) or pr.creation["owner"] != state.owner(record):
                raise ValueError("Legacy creation retirement proof is invalid for this worktree.")
            if pr.creation["recovery_upstream"] != f"{repo.remote}/{repo.default_branch}":
                raise ValueError("Legacy creation retirement upstream changed.")
            merged = pr.creation["recovery_merged_pr"]
            with pr_publish.publish_lock(record.worktree_path):
                _observe(record, _original(pr), repo, int(merged) if merged else None)
        _source(record, repo)
    except (OSError, ValueError, TimeoutError, providers.ProviderError, git_ops.GitError) as exc:
        return f"Legacy creation retirement requires renewed qualification: {exc}"
    return None


def _observe(record: tracking.WorktreeRecord, pr: tracking.PRRecord, repo: Any, merged_pr: int | None) -> None:
    from .git_push_transport import pinned_destination

    prcfg = repo.pr
    if pr.provider != prcfg.provider:
        raise ValueError("Publication provider changed.")
    provider = providers.get_provider(pr.provider)
    endpoint = provider.authority_endpoint(prcfg.api_base)
    if endpoint != pr.creation["api_base"] or pr.creation["identity"].lower() != f"{endpoint}/{pr.repo}".lower():
        raise ValueError("Only the unchanged same-repository publication destination is supported.")
    confirm = getattr(provider, "confirm_reconciled_head_v1", None)
    if not callable(confirm):
        raise ValueError("Selected provider cannot qualify legacy-attempt reconciliation.")
    merged_head = ""
    if merged_pr is not None:
        matches = [
            p for p in record.prs if p.pr_id != pr.pr_id and p.number == merged_pr
            and p.branch == pr.branch and p.repo == pr.repo and p.provider == pr.provider
            and p.state == "merged" and p.head_sha and p.url
        ]
        if len(matches) != 1:
            raise ValueError("--merged-pr must select one existing, exact-head merged association.")
        merged_head = matches[0].head_sha
    siblings = [
        p for p in record.prs if p.pr_id != pr.pr_id and p.branch == pr.branch
        and not tracking._pr_is_terminal(p)
    ]
    if siblings:
        raise ValueError("Another live association owns this publication head.")
    remote, cwd = pr.creation["remote"], record.worktree_path
    fetch, urls, destination = pr_publish._remote_snapshot(remote, cwd=cwd)
    if destination.head_identity != pr.creation["identity"]:
        raise ValueError("Publication remote changed or is unreadable.")
    settings = pr_publish._transport_settings(remote, cwd=cwd)
    with pinned_destination(remote, tuple(urls.stdout.splitlines()), settings, fetch_url=fetch.stdout.rstrip("\r\n")):
        tip = pr_publish._tip(remote, pr.branch, cwd)
        upstream_tip = pr_publish._tip(remote, repo.default_branch, cwd)
    if tip is None or (tip and (not merged_head or tip != merged_head)):
        raise ValueError("Remote publication head is unknown or not the exact confirmed merged head.")
    cached_tip = git_ops.git(
        "rev-parse", "--verify", f"refs/remotes/{repo.remote}/{repo.default_branch}^{{commit}}",
        cwd=cwd, isolated_repository=True,
    ).stdout.strip()
    if (
        not upstream_tip or upstream_tip != cached_tip
        or pr_publish.push_identity(repo.remote, cwd=cwd) != pr.creation["identity"]
    ):
        raise ValueError("Upstream observation is unavailable or stale; use normal sync before requalification.")
    token = providers.account_token_for_slug(pr.repo, prcfg)
    if confirm(
        pr.repo, pr.branch, number=merged_pr, head_sha=merged_head,
        api_base=prcfg.api_base, token=token,
    ) is not True:
        raise ValueError("All-state exact-head provider observation is incomplete, open or ambiguous.")


def reconcile(
    worktree_id: str, config: cfg.Config, *, creation_id: str,
    expected_revision: int | None, expected_head: str, merged_pr: int | None,
    reason: str, confirm: bool,
) -> dict[str, Any]:
    base: dict[str, Any] = {"success": False, "worktree_id": worktree_id, "contract": CONTRACT}
    if not reason.strip():
        return {**base, "error": "A specific --reason is required."}
    if not confirm:
        return {**base, "needs_confirm": True, "error": (
            "Retain or resume useful work first. This operation retires only an exact "
            "legacy local attempt with UNKNOWN publication outcome, not a provider PR. "
            "Obtain explicit approval for this attempt, source and revision before --confirm."
        )}
    if (
        not creation_id or type(expected_revision) is not int
        or not 0 <= expected_revision < tracking.MAX_PERSISTED_COUNTER or not expected_head
    ):
        return {**base, "error": "Exact creation ID, --expected-revision and full --expected-head are required."}
    repo = config.default_repo
    path = cfg.tracking_dir(config.repo_name) / f"{worktree_id}.yaml"
    try:
        with FinalizeLock(Path(repo.worktree_root) / ".finalize.lock"), pr_authority.guard(), pr_publish.metadata_lock(
            worktree_id, project=config.repo_name,
        ):
            record = tracking.load_record(path)
            if record.worktree_id != worktree_id or record.repo != config.repo_name:
                raise ValueError("Owning worktree identity differs from the selected project.")
            if record.status != "active":
                raise ValueError("The owning worktree is not active.")
            matches = [p for p in record.prs if p.pr_id == creation_id]
            if len(matches) != 1:
                raise ValueError("Exact immutable creation ID is missing or ambiguous.")
            pr = matches[0]
            if retired(pr):
                if (
                    pr.creation["owner"] != state.owner(record)
                    or pr.creation["recovery_revision"] != str(expected_revision)
                    or pr.creation["recovery_head"] != expected_head
                    or pr.creation["recovery_reason"] != reason.strip()
                    or pr.creation["recovery_merged_pr"] != str(merged_pr or "")
                ):
                    raise ValueError("Existing receipt differs from this confirmation.")
                return _result(base, pr, already=True)
            if pr.pr_revision != expected_revision or not _legacy(pr, record):
                raise ValueError("Expected revision or owner-stamped legacy publication evidence differs; retain the attempt.")
            with pr_publish.publish_lock(record.worktree_path):
                head = _source(record, repo, expected_head=expected_head)
                _observe(record, pr, repo, merged_pr)
                if _source(record, repo, expected_head=expected_head) != head:
                    raise ValueError("Source changed during observation.")
                if pr_publish.push_identity(pr.creation["remote"], cwd=record.worktree_path) != pr.creation["identity"]:
                    raise ValueError("Publication destination changed during observation.")
                with tracking._RecordLock(path, require_sidecar=True):
                    fresh = tracking.load_record(path)
                    current = pr_publish._publication_pr(fresh, pr)
                    if (
                        state.owner(fresh) != state.owner(record) or current is None
                        or current.pr_revision != expected_revision
                        or not pr_publication_state.matches(current, pr)
                        or not _legacy(current, fresh)
                    ):
                        raise ValueError("Publication authority changed during observation.")
                    at = tracking._now_iso()
                    current.creation = {
                        **current.creation, "recovery_contract": CONTRACT,
                        "recovery_reason": reason.strip(), "recovery_at": at,
                        "recovery_actor": os.environ.get("COPILOT_AGENT_SESSION_ID") or f"user:{getpass.getuser()}",
                        "recovery_revision": str(expected_revision), "recovery_head": head,
                        "recovery_upstream": f"{repo.remote}/{repo.default_branch}",
                        "recovery_merged_pr": str(merged_pr or ""),
                    }
                    current.state, current.closed_at = "abandoned", at
                    current.pr_revision += 1
                    tracking.save_record(fresh)
                    return _result(base, current, already=False)
    except (OSError, ValueError, TimeoutError, yaml.YAMLError, providers.ProviderError, git_ops.GitError) as exc:
        detail = exc.stderr if isinstance(exc, git_ops.GitError) else str(exc)
        return {**base, "error": f"Legacy creation reconciliation refused: {detail}"}


def _result(base: dict[str, Any], pr: tracking.PRRecord, *, already: bool) -> dict[str, Any]:
    return {
        **base, "success": True, "pr_id": pr.pr_id, "pr_revision": pr.pr_revision,
        "state": pr.state, "creation_reconciled": True, "already_reconciled": already,
        "publication_outcome": "unknown", "creation_cancelled": False,
        "provider_closed": False, "claim_released": False, "receipt": dict(pr.creation),
    }
