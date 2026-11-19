"""Transport authority cannot be inherited as permission across a fork."""

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Barrier, Event
from typing import Any

import pytest
from agent_procutil.owned_process import run_caller_owned
from agent_worktrees import config as cfg, git_ops, pr_transport_fence
from agent_worktrees.git_push_transport import pinned_destination


def test_unpinned_pushurl_is_captured_before_a_remote_repoint(
    pr_repo: tuple[cfg.Config, str, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config, _wid, root, destination = pr_repo
    fetch_store, replacement = tmp_path / "fetch.git", tmp_path / "replacement.git"
    for store in (fetch_store, replacement):
        git_ops.git("init", "--bare", str(store), cwd=str(root))
    git_ops.git("remote", "add", "split", str(fetch_store), cwd=str(root))
    git_ops.git("remote", "set-url", "--add", "--push", "split", str(destination), cwd=str(root))
    head = git_ops.git("rev-parse", "HEAD", cwd=str(root)).stdout.strip()
    original = git_ops.git
    changed = False
    def git(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        if "push" in args and not changed:
            changed = True
            original("remote", "set-url", "--push", "split", str(replacement), cwd=str(root))
        return original(*args, **kwargs)
    monkeypatch.setattr(git_ops, "git", git)
    result = git_ops.push("split", "HEAD:refs/heads/topic", cwd=str(root))
    assert result.ok and changed, result.stderr
    assert original("--git-dir", str(destination), "rev-parse", "topic", cwd=str(root)).stdout.strip() == head
    assert original("--git-dir", str(replacement), "show-ref", "--verify", "refs/heads/topic",
                    cwd=str(root), check=False).returncode != 0


def test_unrelated_heads_keep_concurrent_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "install_dir", lambda: tmp_path / "state")
    both = Barrier(2, timeout=5)
    @pr_transport_fence.publication
    def transport(remote: str, branch: str, *, cwd: str, timeout: float) -> git_ops.PushResult:
        both.wait()
        return git_ops.PushResult(ok=True)
    def publish(branch: str) -> git_ops.PushResult:
        with pinned_destination("origin", ("https://example.com/owner/repo.git",)):
            return transport("origin", branch, cwd=str(tmp_path), timeout=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ("topic-a", "topic-b")))
    assert all(result.ok for result in results)


def test_same_head_transport_remains_exclusive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "install_dir", lambda: tmp_path / "state")
    entered, release = Event(), Event()
    @pr_transport_fence.publication
    def transport(remote: str, branch: str, *, cwd: str, timeout: float) -> git_ops.PushResult:
        entered.set()
        assert release.wait(10)
        return git_ops.PushResult(ok=True)
    def publish() -> git_ops.PushResult:
        with pinned_destination("origin", ("https://example.com/owner/repo.git",)):
            return transport("origin", "topic", cwd=str(tmp_path), timeout=0.1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(publish)
        try:
            assert entered.wait(5)
            second = publish()
            assert not second.ok and "fenced" in second.stderr
        finally:
            release.set()
        assert first.result(timeout=3).ok


def test_forked_publisher_cannot_reuse_parent_authority(tmp_path: Path) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("POSIX fork-specific authority boundary")
    code = """
import multiprocessing
from pathlib import Path
import sys
from agent_worktrees import config, pr_authority
config.install_dir = lambda: Path(sys.argv[1])
def probe(sender):
    try:
        with pr_authority.guard(timeout=0):
            sender.send("bypassed")
    except pr_authority.PublicationAuthorityBusy:
        sender.send("held")
    finally:
        sender.close()
ctx = multiprocessing.get_context("fork")
receiver, sender = ctx.Pipe(duplex=False)
child = ctx.Process(target=probe, args=(sender,))
try:
    with pr_authority.guard():
        child.start()
        sender.close()
        assert receiver.poll(3), "child did not report authority"
        assert receiver.recv() == "held", "fork inherited publication permission"
    child.join(3)
    assert child.exitcode == 0
finally:
    if child.is_alive():
        child.terminate()
        child.join(3)
    receiver.close()
"""
    result = run_caller_owned(
        [sys.executable, "-c", code, str(tmp_path)], timeout=15,
        max_stdout_bytes=4096, max_stderr_bytes=4096,
    )
    assert result.returncode == 0, result.stderr
