"""Transport invalidation and operation-scoped finalization observations."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import inspect
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec, TypeVar
import uuid

if TYPE_CHECKING:
    from .git_ops import PushResult
    from .providers.base import PullResult

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class Qualification:
    proofs: dict[str, object] = field(default_factory=dict)
    heads: dict[str, tuple[Head, ...]] = field(default_factory=dict)
    cleanup: bool = False


current: ContextVar[Qualification | None] = ContextVar("pr-finalization-qualification", default=None)


@dataclass(frozen=True)
class Head:
    identity: str
    branch: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", self.identity.casefold())

    @property
    def directory(self) -> Path:
        from . import config as cfg
        key = hashlib.sha256((self.identity.casefold() + "\0" + self.branch).encode("utf-8")).hexdigest()
        return cfg.install_dir() / "pr-publication-heads" / key

    @contextmanager
    def guard(self, *, timeout: float = 0) -> Iterator[None]:
        from . import pr_publish
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "transport.lock").open("a+b") as handle:
            pr_publish._lock_publish_file(handle, timeout=timeout)
            try:
                yield
            finally:
                pr_publish._unlock_publish_file(handle)


def generation(head: Head, *, initialize: bool = False) -> str:
    """Caller holds this head's fence; the token is not publication permission."""
    from . import tracking

    path = head.directory / "generation"
    try:
        value = path.read_text(encoding="ascii")
    except FileNotFoundError:
        if not initialize:
            raise ValueError("Publication generation evidence is missing.") from None
        value = uuid.uuid4().hex
        tracking._atomic_write(path, value)
    if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Publication generation evidence is malformed.")
    return value


def _targets(remote: str, refspec: str, cwd: str, lifetime: ExitStack) -> tuple[Head, ...]:
    from . import git_ops, pr_publish
    from .git_push_transport import captured_urls, pinned_destination
    branch = refspec.rpartition(":")[2] if ":" in refspec else refspec.removeprefix("+")
    if any(c.isspace() or c in "*?\0\r\n" for c in branch):
        raise ValueError("Publication fencing requires one exact ref.")
    if branch.startswith("refs/") and not branch.startswith("refs/heads/"):
        return ()
    branch = branch.removeprefix("refs/heads/")
    if branch == "HEAD":
        branch = git_ops.git(
            "symbolic-ref", "--short", "HEAD", cwd=cwd, isolated_repository=True,
            timeout=10, kill_tree=True,
        ).stdout.strip()
    if not branch or branch.startswith("-") or any(c.isspace() or c in "*?\0\r\n" for c in branch):
        raise ValueError("Publication fencing requires one exact head.")
    urls = captured_urls(remote)
    if not urls:
        with pr_publish.publish_lock(cwd):
            literal = "://" in remote or ":" in remote or Path(remote).is_absolute() or remote.startswith(("./", "../", ".\\", "..\\"))
            if not literal:
                fetch, pushes, _target = pr_publish._remote_snapshot(remote, cwd=cwd)
                literal = bool((fetch.returncode or pushes.returncode) and Path(cwd, remote).exists())
            if literal:
                alias = f"agent-worktrees-capture-{uuid.uuid4().hex}"
                prefix = ("-c", f"remote.{alias}.url={remote}")
                fetch = git_ops.git(*prefix, "remote", "get-url", alias, cwd=cwd,
                                    isolated_repository=True, timeout=10, kill_tree=True)
                pushes = git_ops.git(*prefix, "remote", "get-url", "--push", "--all", alias,
                                     cwd=cwd, isolated_repository=True, timeout=10, kill_tree=True)
                settings: tuple[tuple[str, str], ...] = ()
            else:
                settings = pr_publish._transport_settings(remote, cwd=cwd)
            urls = tuple(pushes.stdout.splitlines())
            if fetch.returncode or pushes.returncode or not fetch.stdout.strip() or not urls or any(not u.strip() for u in urls):
                raise ValueError("The exact push destinations are unavailable.")
        lifetime.enter_context(pinned_destination(remote, urls, settings, fetch_url=fetch.stdout.rstrip("\r\n")))
    identities = {pr_publish._identity(url, cwd) for url in urls}
    if not identities or "" in identities:
        raise ValueError("Publication destination identity is unavailable.")
    return tuple(sorted({Head(identity, branch) for identity in identities}, key=lambda h: h.directory))


def publication(function: Callable[P, PushResult]) -> Callable[P, PushResult]:
    signature = inspect.signature(function)
    @wraps(function)
    def fenced(*args: P.args, **kwargs: P.kwargs) -> PushResult:
        from . import publication_deadline, push_timeout, tracking
        from .git_ops import GitError, PushResult
        lifetime = ExitStack()
        try:
            bound = signature.bind(*args, **kwargs).arguments
            requested = kwargs.get("timeout")
            if requested is not None and type(requested) not in (int, float):
                raise ValueError("Invalid publication timeout.")
            timeout = float(requested) if isinstance(requested, (int, float)) else push_timeout.DEFAULT_PUSH_TIMEOUT
            heads = _targets(bound["remote"], bound["branch"], str(bound["cwd"]), lifetime)
            for head in heads:
                lifetime.enter_context(head.guard(timeout=publication_deadline.validate(timeout)))
        except (GitError, subprocess.SubprocessError):
            lifetime.close()
            return PushResult(ok=False, stderr="Cannot qualify the exact publication destination/head before transport.")
        except (OSError, ValueError, TimeoutError) as exc:
            lifetime.close()
            return PushResult(ok=False, stderr=f"Publication transport is fenced: {exc}")
        try:
            try:
                for head in heads:
                    tracking._atomic_write(head.directory / "generation", uuid.uuid4().hex)
            except OSError as exc:
                return PushResult(ok=False, stderr=f"Publication invalidation evidence is unavailable: {exc}")
            return function(*args, **kwargs)
        finally:
            lifetime.close()
    return fenced


def qualification_scope(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def scoped(*args: P.args, **kwargs: P.kwargs) -> R:
        token = current.set(Qualification())
        try:
            return function(*args, **kwargs)
        finally:
            current.reset(token)
    return scoped


def provider_creation(function: Callable[P, PullResult]) -> Callable[P, PullResult]:
    signature = inspect.signature(function)
    @wraps(function)
    def fenced(*args: P.args, **kwargs: P.kwargs) -> PullResult:
        from . import pr_publish, tracking
        from .providers.base import ProviderError
        bound = signature.bind(*args, **kwargs).arguments
        provider, scope = bound["self"], bound["scope"]
        binding = scope.repo, scope.head, scope.api_base
        head = Head(provider.authority_endpoint(scope.api_base) + "/" + scope.repo,
                    scope.head.rsplit(":", 1)[-1])
        lease = head.guard(timeout=pr_publish.PUBLISH_LOCK_ACQUIRE_TIMEOUT_S)
        try:
            lease.__enter__()
        except (OSError, ValueError, TimeoutError) as exc:
            raise ProviderError(f"Provider creation is fenced: {exc}") from exc
        try:
            if (scope.repo, scope.head, scope.api_base) != binding:
                raise ProviderError("Provider creation binding changed before admission.")
            tracking._atomic_write(head.directory / "generation", uuid.uuid4().hex)
            return function(*args, **kwargs)
        finally:
            lease.__exit__(None, None, None)
    return fenced


@contextmanager
def cleanup_guard(record: object, repo: object) -> Iterator[None]:
    """Never perform remote I/O while cleanup owns the ledger/finalization locks."""
    from . import pr_creation_reconcile, tracking
    from .config import RepoConfig
    if not isinstance(record, tracking.WorktreeRecord) or not any(
        pr_creation_reconcile.requires_qualification(pr) for pr in record.prs
    ):
        yield
        return
    if not isinstance(repo, RepoConfig):
        raise ValueError("Retirement cleanup requires the exact repository policy.")
    scope = current.get()
    if scope is None:
        raise ValueError("Retirement cleanup has no operation-scoped qualification.")
    heads = scope.heads.get(str(record.yaml_path.resolve()))
    if not heads:
        raise ValueError("Retirement prequalification is missing; retry before cleanup.")
    with ExitStack() as lifetime:
        for head in sorted(set(heads), key=lambda h: h.directory):
            lifetime.enter_context(head.guard())
        scope.cleanup = True
        try:
            error = pr_creation_reconcile.finalization_error(record, repo)
            if error:
                raise ValueError(error)
            yield
        finally:
            scope.cleanup = False
