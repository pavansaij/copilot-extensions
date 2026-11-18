"""Explicit legacy-attempt retirement is not cancellation or provider closure."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from agent_worktrees import __main__ as cli
from agent_worktrees import finalize, finalize_open_pr_gate, git_ops, tracking
from agent_worktrees import pr_creation_state as state
from test_pr_creation_cancel import reservation as reservation, source_snapshot

pytestmark = pytest.mark.contract("agent_worktrees.pr_publish.publication_state")


@pytest.fixture
def legacy(reservation):
    config, wid, wt, remote, path, _record, provider = reservation
    record = tracking.load_record(path)
    record.pr.creation["phase"] = "publishing"
    record.pr.pr_revision += 1
    tracking.save_record(record)
    # Realign only disposable fixture refs; the recovery command must never do it.
    git_ops.git("reset", "--hard", "origin/master", cwd=str(wt))
    git_ops.git("branch", record.pr.branch, "HEAD", cwd=str(wt))
    provider.confirm_reconciled_head_v1 = lambda *a, **k: True
    return config, wid, wt, remote, path, record, provider


def invoke(legacy, capfd, **overrides):
    from agent_worktrees.pr_state_cli import cmd_pr_abandon

    _config, wid, wt, _remote, _path, record, _provider = legacy
    options = {
        "expected-revision": str(record.pr.pr_revision),
        "expected-head": git_ops.git("rev-parse", "HEAD", cwd=str(wt)).stdout.strip(),
        "reason": "Superseded planning retained upstream; retire this local attempt",
    }
    options.update(overrides)
    argv = ["pr-abandon", wid, "--reconcile-creation", record.pr.pr_id, "--confirm", "--json"]
    for key, value in options.items():
        if value is not None:
            argv += [f"--{key}", str(value)]
    args = cli.build_parser().parse_args(argv)
    code = cmd_pr_abandon(args)
    response = json.loads(capfd.readouterr().out)
    assert code == (0 if response["success"] else 1)
    return response


def test_actual_deadlock_and_owner_cli_retirement(legacy, monkeypatch, capfd):
    config, wid, wt, _remote, path, record, _provider = legacy
    monkeypatch.setattr(finalize_open_pr_gate, "pull_for", lambda *a: None)
    assert not state.reserved(record.pr, record)
    assert not finalize_open_pr_gate.assert_no_live_pr(record, config, wid)
    assert finalize_open_pr_gate.assert_no_live_pr(record, config, wid, force=True)
    assert not finalize._pr_finalize_precondition(
        record, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]
    capfd.readouterr()
    before = source_snapshot(wt)
    assert not invoke(legacy, capfd, **{"expected-head": "changed"})["success"]
    from agent_worktrees import pr_publish
    tip = pr_publish._tip
    monkeypatch.setattr(
        pr_publish, "_tip", lambda remote, branch, cwd: "stale" if branch == config.default_repo.default_branch
        else tip(remote, branch, cwd),
    )
    assert not invoke(legacy, capfd)["success"]
    monkeypatch.setattr(pr_publish, "_tip", tip)
    result = invoke(legacy, capfd)
    assert result["success"], result
    assert result["publication_outcome"] == "unknown"
    assert result["creation_reconciled"] and not result["provider_closed"]
    assert not result["claim_released"] and not result["creation_cancelled"]
    current = tracking.load_record(path)
    assert current.pr.number is None and not current.pr.url and not current.pr.head_sha
    assert current.pr.pr_id == record.pr.pr_id
    assert current.pr.creation["phase"] == "publishing"
    assert current.pr.creation["binding"] == record.pr.creation["binding"]
    assert current.pr.attribution_mode == record.pr.attribution_mode
    assert source_snapshot(wt) == before
    assert finalize_open_pr_gate.assert_no_live_pr(current, config, wid)
    assert finalize._pr_finalize_precondition(
        current, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]
    saved = path.read_bytes()
    assert invoke(legacy, capfd)["already_reconciled"]
    assert path.read_bytes() == saved


@pytest.mark.parametrize("change", ["source", "branch", "revision", "owner", "binding", "prepared", "legacy"])
def test_changed_or_unlanded_inputs_refuse_without_rewriting(legacy, capfd, change):
    _config, _wid, wt, _remote, path, _record, _provider = legacy
    record = tracking.load_record(path)
    if change in ("source", "branch"):
        git_ops.git("commit", "--allow-empty", "-m", "Unlanded planning", cwd=str(wt))
        if change == "branch":
            git_ops.git("branch", "-f", record.pr.branch, "HEAD", cwd=str(wt))
            git_ops.git("reset", "--hard", "origin/master", cwd=str(wt))
    elif change == "revision":
        record.pr.pr_revision += 1
    elif change in ("owner", "binding"):
        record.pr.creation[change] = "changed"
    elif change == "prepared":
        record.pr.creation["push_head"] = "unknown"
    else:
        record.pr.creation = {}
    tracking.save_record(record)
    before = path.read_bytes(), source_snapshot(wt)
    result = invoke(legacy, capfd)
    assert not result["success"], result
    assert (path.read_bytes(), source_snapshot(wt)) == before


@pytest.mark.parametrize("failure", ["provider-false", "provider-unknown", "remote", "remote-unknown"])
def test_incomplete_observations_hold_original_unknown_outcome(legacy, monkeypatch, capfd, failure):
    from agent_worktrees import pr_publish
    from agent_worktrees.providers import ProviderError

    provider, path = legacy[6], legacy[4]
    if failure == "provider-false":
        provider.confirm_reconciled_head_v1 = lambda *a, **k: False
    elif failure == "provider-unknown":
        def unavailable(*a, **k):
            raise ProviderError("observation unavailable")
        provider.confirm_reconciled_head_v1 = unavailable
    else:
        monkeypatch.setattr(pr_publish, "_tip", lambda *a: "unexpected" if failure == "remote" else None)
    before = path.read_bytes()
    assert not invoke(legacy, capfd)["success"]
    assert path.read_bytes() == before


def test_immutable_id_selects_duplicate_without_changing_proper_mapping(legacy, capfd):
    config, _wid, wt, _remote, path, original, _provider = legacy
    record = tracking.load_record(path)
    merged = replace(
        record.pr, pr_id="numbered-attempt", creation={}, state="merged", number=12,
        url="https://github.com/example/repo/pull/12",
        head_sha=git_ops.git("rev-parse", "HEAD", cwd=str(wt)).stdout.strip(),
    )
    record.prs.insert(0, merged)
    tracking.save_record(record)
    result = invoke(legacy, capfd, **{"merged-pr": 12})
    assert result["success"], result
    fresh = tracking.load_record(path)
    assert fresh.prs[0] == merged
    assert fresh.prs[1].pr_id == original.pr.pr_id
    assert finalize._pr_finalize_precondition(
        fresh, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]


def test_late_callback_and_stale_stamp_cannot_resurrect_retirement(legacy, capfd):
    from agent_worktrees import pr_publication_state

    path = legacy[4]
    stale = tracking.load_record(path)
    assert invoke(legacy, capfd)["success"]
    with pytest.raises(ValueError, match="authority changed"):
        pr_publication_state.require_current(stale, stale.pr)
    stale.title = "Unrelated status stamp"
    tracking.save_record(stale)
    fresh = tracking.load_record(path)
    assert fresh.pr.state == "abandoned"
    assert fresh.pr.creation["recovery_contract"]


def test_observation_cannot_outvote_revision_drift(legacy, capfd):
    path, original, provider = legacy[4], legacy[5], legacy[6]
    def race(*args, **kwargs):
        current = tracking.load_record(path)
        current.pr.pr_revision += 1
        tracking.save_record(current)
        return True
    provider.confirm_reconciled_head_v1 = race
    result = invoke(legacy, capfd)
    assert not result["success"] and "authority changed" in result["error"]
    fresh = tracking.load_record(path)
    assert fresh.pr.pr_revision == original.pr.pr_revision + 1
    assert fresh.pr.state == "creating" and "recovery_contract" not in fresh.pr.creation


def test_unconfirmed_reconciliation_does_not_read_the_record(monkeypatch):
    from agent_worktrees.pr_creation_reconcile import reconcile

    monkeypatch.setattr(tracking, "load_record", lambda *a: pytest.fail("unconfirmed record read"))
    result = reconcile(
        "example", None, creation_id="attempt", expected_revision=None,
        expected_head="", merged_pr=None, reason="Superseded", confirm=False,
    )
    assert result["needs_confirm"] and not result["success"]


@pytest.mark.parametrize("options", [
    ["--reconcile-creation", "", "--expected-revision", "0", "--expected-head", "abc"],
    ["--expected-head", ""],
    ["--merged-pr", "0"],
])
def test_invalid_local_selector_never_falls_through_to_provider_abandon(monkeypatch, capfd, options):
    from agent_worktrees import config, pr_ops, worktree_identity
    from agent_worktrees.pr_state_cli import cmd_pr_abandon

    monkeypatch.setattr(config, "load_config", lambda *a: SimpleNamespace())
    monkeypatch.setattr(worktree_identity, "_infer_worktree_id", lambda wid, config: wid)
    monkeypatch.setattr(worktree_identity, "_resolve_worktree_id", lambda wid: wid)
    monkeypatch.setattr(pr_ops, "abandon_pr", lambda *a, **k: pytest.fail("unintended provider abandonment"))
    args = cli.build_parser().parse_args([
        "pr-abandon", "example", "--reason", "Retire only the local attempt",
        "--confirm", "--json", *options,
    ])
    assert cmd_pr_abandon(args) == 1
    assert not json.loads(capfd.readouterr().out)["success"]


def test_other_unlanded_ref_and_post_receipt_drift_still_block(legacy, capfd):
    config, _wid, wt, _remote, path, _record, _provider = legacy
    assert invoke(legacy, capfd)["success"]
    _provider.confirm_reconciled_head_v1 = lambda *a, **k: False
    current = tracking.load_record(path)
    assert not finalize._pr_finalize_precondition(
        current, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]
    _provider.confirm_reconciled_head_v1 = lambda *a, **k: True
    git_ops.git("commit", "--allow-empty", "-m", "New responsibility", cwd=str(wt))
    current = tracking.load_record(path)
    assert not finalize._pr_finalize_precondition(
        current, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]
