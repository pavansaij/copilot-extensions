"""Bounded exact-head observations; never infer empty from a failed lookup."""

from __future__ import annotations

import json
from typing import Any

from .base import ProviderError, run_cli


def confirm(
    provider: Any, repo: str, head: str, *, number: int | None = None,
    head_sha: str = "", api_base: str = "", token: str | None = None,
) -> bool:
    owner, separator, name = repo.partition("/")
    if not owner or not separator or not name or "/" in name or not head:
        raise ProviderError("An exact repository and head are required.")
    host = provider.authority_endpoint(api_base)
    result = run_cli(
        [
            "gh", "api", "--hostname", host, f"repos/{repo}/pulls", "--method", "GET",
            "-f", "state=all", "-f", f"head={owner}:{head}", "-f", "per_page=2",
        ],
        env=provider._env(token, host=host),
    )
    if result.returncode:
        raise ProviderError(f"Cannot observe publication head: {result.stderr.strip()}")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError("Publication-head response is not JSON.") from exc
    if not isinstance(rows, list):
        raise ProviderError("Publication-head response is not a list.")
    if number is None:
        return rows == []
    # Two results already establish ambiguity. A single row is complete because
    # this page requested two; no best-effort first-match or unbounded pagination.
    if len(rows) != 1 or not isinstance(rows[0], dict) or not head_sha:
        return False
    row = rows[0]
    source, base = row.get("head"), row.get("base")
    if not isinstance(source, dict) or not isinstance(base, dict):
        return False
    source_repo, base_repo = source.get("repo"), base.get("repo")
    return bool(
        type(row.get("number")) is int and row["number"] == number
        and row.get("state") == "closed"
        and isinstance(row.get("merged_at"), str) and row["merged_at"].strip()
        and source.get("ref") == head and source.get("sha") == head_sha
        and isinstance(source_repo, dict) and source_repo.get("full_name") == repo
        and isinstance(base_repo, dict) and base_repo.get("full_name") == repo
    )
