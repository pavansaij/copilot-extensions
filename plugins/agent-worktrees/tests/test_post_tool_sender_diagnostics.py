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


def observe_after_entry(harness: Path, expression: str) -> None:
    """Append a bounded observation after the original entry has returned."""
    entry = harness.read_text(encoding="utf-8")
    original = ")); exit 0"
    assert entry.count(original) == 1
    harness.write_text(
        entry.replace(original, ")); " + expression + "; exit 0"), encoding="utf-8",
    )


def instrument_sender(source: str) -> str:
    """Observe fixture-owned finalization without changing timed operations."""
    start = source.index("function Send-PostToolReadDemand")
    end = source.index("function Get-PostToolRuntimeRoot", start)
    sender = source[start:end]
    original = (
        "    } catch {} finally {\n"
        "        if ($null -ne $client) { $client.Dispose() }\n"
        "    }\n"
    )
    replacement = r"""    } catch {
        $caught = $_.Exception.GetBaseException()
    } finally {
        try {
            $script:senderObservation = @{
                elapsed_ms = if ($null -ne $clock) { $clock.Elapsed.TotalMilliseconds } else { $null }
                remaining_ms = $remaining
                client_exists = $null -ne $client
                connected = $null -ne $client -and $client.Connected
                caught_type = if ($null -ne $caught) { $caught.GetType().FullName } else { $null }
                caught_hresult = if ($null -ne $caught) { $caught.HResult } else { $null }
                socket_error = if ($caught -is [Net.Sockets.SocketException]) { $caught.SocketErrorCode.ToString() } else { $null }
            }
        } finally {
            if ($null -ne $client) { $client.Dispose() }
        }
    }
"""
    assert sender.count(original) == 1
    sender = sender.replace(original, replacement)
    return source[:start] + sender + source[end:]


@pytest.mark.guard
def test_sender_observer_leaves_timed_operations_unchanged() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "hook-facts.ps1").read_text(
        encoding="utf-8",
    )
    observed = instrument_sender(source)
    before, _, after = source.partition("function Send-PostToolReadDemand")
    after_sender = "function Get-PostToolRuntimeRoot"
    assert observed.startswith(before)
    assert observed.partition(after_sender)[2] == source.partition(after_sender)[2]
    original_operations = after.partition("    } catch {} finally {")[0]
    observed_operations = observed.partition("function Send-PostToolReadDemand")[2].partition(
        "    } catch {",
    )[0]
    assert observed_operations == original_operations


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
@pytest.mark.parametrize("case", ["read"])
def test_registered_prepared_sender_stage_observation(
    prepared_read_event: PreparedFixture, monkeypatch: pytest.MonkeyPatch, shell: str, case: str,
) -> None:
    facts = prepared_read_event["payload_root"] / "scripts" / "hook-facts.ps1"
    facts.write_text(instrument_sender(facts.read_text(encoding="utf-8")), encoding="utf-8")
    observe_after_entry(
        prepared_read_event["harness"],
        "[Console]::Error.WriteLine('sender_observation=' + "
        "(ConvertTo-Json -Compress -InputObject $script:senderObservation))",
    )
    fixture = cast(PostToolFixture, importlib.import_module("test_post_tool_shell"))
    fixture.test_registered_prepared_cell_post_tool_uses_selected_original_owners(
        prepared_read_event, monkeypatch, shell, case,
    )
    pytest.fail("Sender observation is diagnostic only, not uninstrumented native acceptance")


@pytest.mark.portfolio_tier("T2")
@pytest.mark.effect("process")
@pytest.mark.effect("filesystem")
@pytest.mark.effect("network")
@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("AGENT_WORKTREES_SENDER_DIAGNOSTIC") != "1",
    reason="Explicit post-entry error observation; not acceptance",
)
@pytest.mark.parametrize("prepared_read_event", ["cell"], indirect=True)
@pytest.mark.parametrize("shell", ["pwsh", "powershell.exe"])
@pytest.mark.parametrize("case", ["read"])
def test_registered_prepared_post_entry_error_observation(
    prepared_read_event: PreparedFixture, monkeypatch: pytest.MonkeyPatch, shell: str, case: str,
) -> None:
    facts = prepared_read_event["payload_root"] / "scripts" / "hook-facts.ps1"
    assert facts.read_bytes() == (
        Path(__file__).resolve().parents[1] / "scripts" / "hook-facts.ps1"
    ).read_bytes()
    observe_after_entry(prepared_read_event["harness"], r"""
$observedErrors = @(
    $observedCount = 0
    foreach ($entryError in $Error) {
        if ($observedCount -ge 32) { break }
        $baseError = $entryError.Exception.GetBaseException()
        @{ type = $baseError.GetType().FullName; hresult = $baseError.HResult }
        $observedCount++
    }
)
[Console]::Error.WriteLine('post_entry_errors=' +
    (ConvertTo-Json -Compress -InputObject $observedErrors))
""")
    fixture = cast(PostToolFixture, importlib.import_module("test_post_tool_shell"))
    fixture.test_registered_prepared_cell_post_tool_uses_selected_original_owners(
        prepared_read_event, monkeypatch, shell, case,
    )
    pytest.fail("Post-entry observation is diagnostic only, not uninstrumented native acceptance")
