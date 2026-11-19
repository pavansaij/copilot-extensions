"""Opt-in observations of the registered sender, never native acceptance."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pytest

pytest_plugins = ("test_post_tool_shell",)


class PreparedFixture(TypedDict):
    payload_root: Path
    harness: Path


class PostToolFixture(Protocol):
    test_registered_prepared_cell_post_tool_uses_selected_original_owners: Callable[
        [PreparedFixture, pytest.MonkeyPatch, str, str], None
    ]


def instrument_sender(source: str) -> str:
    start = source.index("function Send-PostToolReadDemand")
    end = source.index("function Get-PostToolRuntimeRoot", start)
    sender = source[start:end]
    for original, replacement in (
        (
            "    $client = $null",
            "    $script:senderObservation = [ordered]@{ stage = 'entered' }\n"
            "    $client = $null",
        ),
        (
            "        $clock = [Diagnostics.Stopwatch]::StartNew()",
            "        $script:senderObservation.stage = 'serialized'\n"
            "        $clock = [Diagnostics.Stopwatch]::StartNew()",
        ),
        (
            "        $remaining = 100 - [int]$clock.ElapsedMilliseconds",
            "        $script:senderObservation.elapsed_ms = $clock.Elapsed.TotalMilliseconds\n"
            "        $remaining = 100 - [int]$clock.ElapsedMilliseconds",
        ),
        (
            "        if (-not $client.ConnectAsync([Net.IPAddress]::Loopback, $port).Wait($remaining)) { return }",
            "        $script:senderObservation.stage = 'allocated'\n"
            "        $connect = $client.ConnectAsync([Net.IPAddress]::Loopback, $port)\n"
            "        $script:senderObservation.connect_ms = $clock.Elapsed.TotalMilliseconds\n"
            "        if (-not $connect.Wait($remaining)) {\n"
            "            $script:senderObservation.stage = 'connect-timeout'; return\n"
            "        }\n"
            "        $script:senderObservation.stage = 'connected'",
        ),
        (
            "        $null = $client.GetStream().WriteAsync($bytes, 0, $bytes.Length).Wait($remaining)",
            "        $write = $client.GetStream().WriteAsync($bytes, 0, $bytes.Length)\n"
            "        $script:senderObservation.write_ms = $clock.Elapsed.TotalMilliseconds\n"
            "        $script:senderObservation.completed = $write.Wait($remaining)\n"
            "        $script:senderObservation.stage = 'write-waited'",
        ),
        (
            "    } catch {} finally {",
            "    } catch {\n"
            "        $script:senderObservation.exception_type = $_.Exception.GetType().FullName\n"
            "    } finally {",
        ),
    ):
        assert sender.count(original) == (2 if "$remaining = 100 -" in original else 1)
        sender = sender.replace(original, replacement)
    return source[:start] + sender + source[end:]


@pytest.mark.portfolio_tier("T2")
@pytest.mark.effect("process")
@pytest.mark.effect("filesystem")
@pytest.mark.effect("network")
@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("AGENT_WORKTREES_SENDER_DIAGNOSTIC") != "1",
    reason="Explicit native Windows sender observation; not acceptance",
)
@pytest.mark.parametrize("prepared_read_event", ["cell"], indirect=True)
@pytest.mark.parametrize("shell", ["pwsh", "powershell.exe"])
def test_registered_prepared_sender_stage_observation(
    prepared_read_event: PreparedFixture, monkeypatch: pytest.MonkeyPatch, shell: str,
) -> None:
    facts = prepared_read_event["payload_root"] / "scripts" / "hook-facts.ps1"
    facts.write_text(instrument_sender(facts.read_text(encoding="utf-8")), encoding="utf-8")
    harness = prepared_read_event["harness"]
    entry = harness.read_text(encoding="utf-8")
    original = ")); exit 0"
    assert entry.count(original) == 1
    entry = entry.replace(
        original,
        ")); [Console]::Error.WriteLine('sender_observation=' + "
        "(ConvertTo-Json -Compress -InputObject $script:senderObservation)); exit 0",
    )
    harness.write_text(entry, encoding="utf-8")
    fixture = cast(PostToolFixture, importlib.import_module("test_post_tool_shell"))
    fixture.test_registered_prepared_cell_post_tool_uses_selected_original_owners(
        prepared_read_event, monkeypatch, shell, "read",
    )
    pytest.fail("Sender observation is diagnostic only, not uninstrumented native acceptance")
