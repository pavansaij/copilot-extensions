"""Install an opt-in observer before the unchanged original packet."""

import os

import pytest

from test_post_tool_sender_diagnostics import ReceiverPacketObserver


@pytest.mark.portfolio_tier("T2")
@pytest.mark.effect("process")
@pytest.mark.effect("filesystem")
@pytest.mark.effect("network")
@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("AGENT_WORKTREES_SENDER_DIAGNOSTIC") != "1",
    reason="Explicit original-packet receiver observation; not acceptance",
)
def test_enable_original_packet_receiver_observer(pytestconfig: pytest.Config) -> None:
    pytestconfig.pluginmanager.register(
        ReceiverPacketObserver(), name="prepared-read-receiver-observer",
    )
    pytest.fail("Original-packet receiver observation is diagnostic only, never native acceptance")
