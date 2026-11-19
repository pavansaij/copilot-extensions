"""Explicit legacy-attempt retirement is not cancellation or provider closure."""

from dataclasses import replace
import json
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Callable, cast

import pytest
from machine_transport import detect_platform

from agent_worktrees import __main__ as cli
from agent_worktrees import config as cfg
from agent_worktrees import finalize, finalize_open_pr_gate, git_ops, tracking
from agent_worktrees import pr_creation_state as state
from test_pr_creation_cancel import reservation as reservation, source_snapshot

pytestmark = pytest.mark.contract("agent_worktrees.pr_publish.publication_state")
Legacy = tuple[cfg.Config, str, Path, Path, Path, tracking.WorktreeRecord, Any]
snapshot = cast(Callable[[Path], tuple[str, bytes, str, str]], source_snapshot)


@pytest.fixture
def pr_repo(
    pr_repo: tuple[cfg.Config, str, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[cfg.Config, str, Path, Path]:
    config, wid, wt, remote = pr_repo
    project = tmp_path / "project"
    project.mkdir()
    ledger = project / "worktrees"
    cfg.tracking_dir().rename(ledger)
    monkeypatch.setattr(cfg, "project_dir", lambda name=None: project)
    monkeypatch.setattr(cfg, "tracking_dir", lambda name=None: ledger)
    config = replace(config, platform=detect_platform())
    return config, wid, wt, remote


def selected(record: tracking.WorktreeRecord) -> tracking.PRRecord:
    pr = record.pr
    assert pr is not None
    return pr


@pytest.fixture
def legacy(reservation: Legacy) -> Legacy:
    config, wid, wt, remote, path, _record, provider = reservation
    record = tracking.load_record(path)
    selected(record).creation["phase"] = "publishing"
    selected(record).pr_revision += 1
    tracking.save_record(record)
    # Realign only disposable fixture refs; the recovery command must never do it.
    git_ops.git("reset", "--hard", "origin/master", cwd=str(wt))
    git_ops.git("branch", selected(record).branch, "HEAD", cwd=str(wt))
    provider.confirm_reconciled_head_v1 = lambda *a, **k: True
    return config, wid, wt, remote, path, record, provider


def invoke(legacy: Legacy, capfd: pytest.CaptureFixture[str], **overrides: str | int | None) -> dict[str, Any]:
    from agent_worktrees.pr_state_cli import cmd_pr_abandon

    _config, wid, wt, _remote, _path, record, _provider = legacy
    options: dict[str, str | int | None] = {
        "expected-revision": str(selected(record).pr_revision),
        "expected-head": git_ops.git("rev-parse", "HEAD", cwd=str(wt)).stdout.strip(),
        "reason": "Superseded planning retained upstream; retire this local attempt",
    }
    options.update(overrides)
    argv = ["pr-abandon", wid, "--reconcile-creation", selected(record).pr_id, "--confirm", "--json"]
    for key, value in options.items():
        if value is not None:
            argv += [f"--{key}", str(value)]
    args = cli.build_parser().parse_args(argv)
    code = cmd_pr_abandon(args)
    response: dict[str, Any] = json.loads(capfd.readouterr().out)
    assert code == (0 if response["success"] else 1)
    return response


def test_actual_deadlock_and_owner_cli_retirement(legacy: Legacy, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]) -> None:
    config, wid, wt, _remote, path, record, _provider = legacy
    monkeypatch.setattr(finalize_open_pr_gate, "pull_for", lambda *a: None)
    assert not state.reserved(selected(record), record)
    assert not finalize_open_pr_gate.assert_no_live_pr(record, config, wid)
    assert finalize_open_pr_gate.assert_no_live_pr(record, config, wid, force=True)
    assert not finalize._pr_finalize_precondition(
        record, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]
    capfd.readouterr()
    before = snapshot(wt)
    result = invoke(legacy, capfd)
    assert result["success"], result
    assert result["publication_outcome"] == "unknown"
    assert result["creation_reconciled"] and not result["provider_closed"]
    assert not result["claim_released"] and not result["creation_cancelled"]
    current = tracking.load_record(path)
    assert selected(current).number is None and not selected(current).url and not selected(current).head_sha
    assert selected(current).pr_id == selected(record).pr_id
    assert selected(current).creation["phase"] == "publishing"
    assert selected(current).creation["binding"] == selected(record).creation["binding"]
    assert selected(current).attribution_mode == selected(record).attribution_mode
    assert snapshot(wt) == before
    assert finalize_open_pr_gate.assert_no_live_pr(current, config, wid)


def test_confirmed_retry_keeps_original_receipt(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    assert invoke(legacy, capfd)["success"]
    path = legacy[4]
    saved = path.read_bytes()
    assert invoke(legacy, capfd)["already_reconciled"]
    assert path.read_bytes() == saved


def test_hidden_untracked_work_is_not_clean_source(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    wt, path = legacy[2], legacy[4]
    (wt / "untracked.txt").write_text("retain useful work\n")
    git_ops.git("config", "status.showUntrackedFiles", "no", cwd=str(wt))
    before = path.read_bytes()
    result = invoke(legacy, capfd)
    assert not result["success"] and "Dirty source" in result["error"]
    assert path.read_bytes() == before and (wt / "untracked.txt").exists()


def test_ignored_dirty_submodule_is_not_clean_source(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    wt, remote, path = legacy[2], legacy[3], legacy[4]
    git_ops.git("-c", "protocol.file.allow=always", "submodule", "add", str(remote), "module", cwd=str(wt))
    git_ops.git("commit", "-am", "Add already-landed submodule", cwd=str(wt))
    git_ops.git("push", "origin", "HEAD:master", cwd=str(wt))
    git_ops.git("config", "submodule.module.ignore", "all", cwd=str(wt))
    module = wt / "module"
    tracked = git_ops.git("ls-files", cwd=str(module)).stdout.splitlines()[0]
    (module / tracked).write_text("uncommitted submodule work\n")
    assert not git_ops.git("status", "--porcelain", cwd=str(wt)).stdout.strip()
    before = path.read_bytes()
    result = invoke(legacy, capfd)
    assert not result["success"] and "Dirty source" in result["error"]
    assert path.read_bytes() == before


def test_replace_refs_cannot_make_unlanded_source_an_ancestor(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    wt, path = legacy[2], legacy[4]
    git_ops.git("commit", "--allow-empty", "-m", "Unlanded source", cwd=str(wt))
    head = git_ops.git("rev-parse", "HEAD", cwd=str(wt)).stdout.strip()
    upstream = git_ops.git("rev-parse", "origin/master", cwd=str(wt)).stdout.strip()
    tree = git_ops.git("rev-parse", "origin/master^{tree}", cwd=str(wt)).stdout.strip()
    replacement = git_ops.git("commit-tree", tree, "-p", head, "-m", "Replacement", cwd=str(wt)).stdout.strip()
    git_ops.git("replace", upstream, replacement, cwd=str(wt))
    assert git_ops.git("merge-base", "--is-ancestor", "HEAD", "origin/master", cwd=str(wt)).returncode == 0
    before = path.read_bytes()
    result = invoke(legacy, capfd)
    assert not result["success"] and "Every owned local" in result["error"]
    assert path.read_bytes() == before


def test_unrelated_clone_cannot_stand_in_for_recorded_checkout(legacy: Legacy, tmp_path: Path) -> None:
    from agent_worktrees import pr_creation_reconcile as recovery
    config, _wid, wt, remote, _path, record, _provider = legacy
    shadow = tmp_path / "shadow"
    git_ops.git("clone", "--quiet", str(remote), str(shadow), cwd=str(wt))
    git_ops.git("checkout", "-qb", record.branch, cwd=str(shadow))
    with pytest.raises(ValueError, match="configured anchor"):
        recovery._source(replace(record, worktree_path=str(shadow)), config.default_repo)


@pytest.mark.parametrize("snapshot_number", [1, 2])
def test_native_execution_space_refusal_preserves_attempt(
    legacy: Legacy, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], snapshot_number: int,
) -> None:
    from agent_worktrees import execution_spaces
    real = execution_spaces.require_record_mutation
    calls = 0
    def check(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == snapshot_number:
            raise execution_spaces.ExecutionSpaceError("foreign receiving subject")
        real(*args, **kwargs)
    monkeypatch.setattr(execution_spaces, "require_record_mutation", check)
    before = legacy[4].read_bytes()
    result = invoke(legacy, capfd)
    assert not result["success"] and "foreign receiving subject" in result["error"]
    assert calls == snapshot_number and legacy[4].read_bytes() == before


@pytest.mark.parametrize("damage", ["none", "contract", "all-recovery", "all-creation"])
def test_retirement_requires_qualification_even_when_pr_mode_is_disabled(
    legacy: Legacy, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], damage: str,
) -> None:
    from agent_worktrees import finalize_landing, pr_reconcile
    config, wid, wt, _remote, path, _record, provider = legacy
    assert invoke(legacy, capfd)["success"]
    current = tracking.load_record(path)
    retired = selected(current)
    if damage == "contract":
        del retired.creation["recovery_contract"]
    elif damage == "all-recovery":
        retired.creation = {k: v for k, v in retired.creation.items() if not k.startswith("recovery_")}
    elif damage == "all-creation":
        retired.creation = {}
    tracking.save_record(current)
    provider.find_pull_by_head = lambda *a, **k: pytest.fail("retired attempt was healed")
    assert not pr_reconcile.heal_numberless_active_pr(current, config)
    if damage != "none":
        current.prs.append(tracking.PRRecord(
            pr_id="other-attempt", branch="pr/other", state="merged", number=12,
            repo="example/repo", provider="github",
        ))
        tracking.save_record(current)
    repo = replace(config.default_repo, pr=replace(config.default_repo.pr, enabled=False))
    assert finalize_landing.tracks_pr(current, repo)
    monkeypatch.setattr(finalize_open_pr_gate, "pull_for", lambda *a: None)
    landed, reason = finalize._pr_finalize_precondition(current, repo, str(wt), repo.anchor)
    assert landed is (damage == "none"), reason
    if damage != "none":
        assert reason and "retirement proof is invalid" in reason
    assert current.worktree_id == wid


def test_provider_probe_does_not_hold_clone_or_installation_locks(
    legacy: Legacy, capfd: pytest.CaptureFixture[str],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from agent_worktrees import pr_authority, pr_publish
    config, wid, wt, _remote, _path, _record, provider = legacy
    def acquire() -> bool:
        with pr_authority.guard(timeout=0), pr_publish.publish_lock(str(wt), acquire_timeout=1), \
                pr_publish.metadata_lock(wid, project=config.repo_name, timeout=1):
            return True
    with ThreadPoolExecutor(max_workers=1) as pool:
        def observe(*args: Any, **kwargs: Any) -> bool:
            return pool.submit(acquire).result(timeout=3)
        provider.confirm_reconciled_head_v1 = observe
        result = invoke(legacy, capfd)
    assert result["success"], result


def test_active_record_publisher_refuses_retirement_without_waiting_on_its_authority(
    legacy: Legacy, capfd: pytest.CaptureFixture[str],
) -> None:
    from threading import Event, Thread
    from agent_worktrees import pr_authority
    entered, release = Event(), Event()
    def publisher() -> None:
        with pr_authority.guard():
            entered.set()
            assert release.wait(5)
    thread = Thread(target=publisher)
    def observe(*args: Any, **kwargs: Any) -> bool:
        thread.start()
        assert entered.wait(2)
        return True
    legacy[6].confirm_reconciled_head_v1 = observe
    before = legacy[4].read_bytes()
    try:
        result = invoke(legacy, capfd)
    finally:
        release.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not result["success"] and "authority" in result["error"]
    assert legacy[4].read_bytes() == before


@pytest.mark.parametrize("valid", [False, True])
def test_native_finalization_cannot_disable_retirement_qualification(
    legacy: Legacy, capfd: pytest.CaptureFixture[str], valid: bool,
) -> None:
    config, wid, wt, _remote, path, _record, provider = legacy
    assert invoke(legacy, capfd)["success"]
    record = tracking.load_record(path)
    if not valid:
        del selected(record).creation["recovery_contract"]
        tracking.save_record(record)
    provider.find_pull_by_head = lambda *a, **k: pytest.fail("retired attempt was adopted by heuristic healing")
    config = replace(config, repos={config.repo_name: replace(
        config.default_repo, pr=replace(config.default_repo.pr, enabled=False),
    )})
    result = finalize.validate_and_finalize(wid, config)
    assert result is valid
    assert wt.exists() is not valid


@pytest.mark.parametrize("change", ["source", "branch", "revision", "owner", "binding", "prepared", "legacy", "expected-head"])
def test_changed_or_unlanded_inputs_refuse_without_rewriting(legacy: Legacy, capfd: pytest.CaptureFixture[str], change: str) -> None:
    _config, _wid, wt, _remote, path, _record, _provider = legacy
    record = tracking.load_record(path)
    overrides: dict[str, str] = {}
    if change in ("source", "branch"):
        git_ops.git("commit", "--allow-empty", "-m", "Unlanded planning", cwd=str(wt))
        if change == "branch":
            git_ops.git("branch", "-f", selected(record).branch, "HEAD", cwd=str(wt))
            git_ops.git("reset", "--hard", "origin/master", cwd=str(wt))
    elif change == "revision":
        selected(record).pr_revision += 1
    elif change in ("owner", "binding"):
        selected(record).creation[change] = "changed"
    elif change == "prepared":
        selected(record).creation["push_head"] = "unknown"
    elif change == "expected-head":
        overrides["expected-head"] = "changed"
    else:
        selected(record).creation = {}
    tracking.save_record(record)
    before = path.read_bytes(), snapshot(wt)
    result = invoke(legacy, capfd, **overrides)
    assert not result["success"], result
    assert (path.read_bytes(), snapshot(wt)) == before


@pytest.mark.parametrize("failure", ["provider-false", "provider-unknown", "remote", "remote-unknown", "upstream"])
def test_incomplete_observations_hold_original_unknown_outcome(legacy: Legacy, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], failure: str) -> None:
    from agent_worktrees import pr_publish
    from agent_worktrees.providers import ProviderError

    provider, path = legacy[6], legacy[4]
    if failure == "provider-false":
        provider.confirm_reconciled_head_v1 = lambda *a, **k: False
    elif failure == "provider-unknown":
        def unavailable(*a: Any, **k: Any) -> None:
            raise ProviderError("observation unavailable")
        provider.confirm_reconciled_head_v1 = unavailable
    elif failure == "upstream":
        tip = pr_publish._tip
        branch = legacy[0].default_repo.default_branch
        monkeypatch.setattr(
            pr_publish, "_tip",
            lambda remote, head, cwd: "stale" if head == branch else tip(remote, head, cwd),
        )
    else:
        monkeypatch.setattr(pr_publish, "_tip", lambda *a: "unexpected" if failure == "remote" else None)
    before = path.read_bytes()
    assert not invoke(legacy, capfd)["success"]
    assert path.read_bytes() == before


def test_immutable_id_selects_duplicate_without_changing_proper_mapping(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    config, _wid, wt, _remote, path, original, _provider = legacy
    record = tracking.load_record(path)
    merged = replace(
        selected(record), pr_id="numbered-attempt", creation={}, state="merged", number=12,
        url="https://github.com/example/repo/pull/12",
        head_sha=git_ops.git("rev-parse", "HEAD", cwd=str(wt)).stdout.strip(),
    )
    record.prs.insert(0, merged)
    tracking.save_record(record)
    result = invoke(legacy, capfd, **{"merged-pr": 12})
    assert result["success"], result
    fresh = tracking.load_record(path)
    assert fresh.prs[0] == merged
    assert fresh.prs[1].pr_id == selected(original).pr_id
    assert finalize._pr_finalize_precondition(
        fresh, config.default_repo, str(wt), config.default_repo.anchor,
    )[0]


def test_late_callback_and_stale_stamp_cannot_resurrect_retirement(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    from agent_worktrees import pr_publication_state

    path = legacy[4]
    stale = tracking.load_record(path)
    assert invoke(legacy, capfd)["success"]
    with pytest.raises(ValueError, match="authority changed"):
        pr_publication_state.require_current(stale, stale.pr)
    stale.title = "Unrelated status stamp"
    tracking.save_record(stale)
    fresh = tracking.load_record(path)
    assert selected(fresh).state == "abandoned"
    assert selected(fresh).creation["recovery_contract"]


def test_observation_cannot_outvote_revision_drift(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
    path, original, provider = legacy[4], legacy[5], legacy[6]
    def race(*args: Any, **kwargs: Any) -> bool:
        current = tracking.load_record(path)
        selected(current).pr_revision += 1
        tracking.save_record(current)
        return True
    provider.confirm_reconciled_head_v1 = race
    result = invoke(legacy, capfd)
    assert not result["success"] and "authority changed" in result["error"]
    fresh = tracking.load_record(path)
    assert selected(fresh).pr_revision == selected(original).pr_revision + 1
    assert selected(fresh).state == "creating" and "recovery_contract" not in selected(fresh).creation


def test_unconfirmed_reconciliation_does_not_read_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_worktrees.pr_creation_reconcile import reconcile

    monkeypatch.setattr(tracking, "load_record", lambda *a: pytest.fail("unconfirmed record read"))
    result = reconcile(
        "example", cfg.Config(srcroot="", machine="test", platform="test"), creation_id="attempt", expected_revision=None,
        expected_head="", merged_pr=None, reason="Superseded", confirm=False,
    )
    assert result["needs_confirm"] and not result["success"]


@pytest.mark.parametrize("options", [
    ["--reconcile-creation", "", "--expected-revision", "0", "--expected-head", "abc"],
    ["--expected-head", ""],
    ["--merged-pr", "0"],
])
def test_invalid_local_selector_never_falls_through_to_provider_abandon(monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], options: list[str]) -> None:
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


def test_other_unlanded_ref_and_post_receipt_drift_still_block(legacy: Legacy, capfd: pytest.CaptureFixture[str]) -> None:
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
