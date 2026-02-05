"""Backtest harness for the REASON node.

This script replays stored observations from MemoryStore (if available) through
the REASON step to inspect what actions the agent *would* have taken.

It is intentionally minimal and intended as a starting point for deeper
evaluation tooling.
"""

from __future__ import annotations

import logging

from core.agent import AgentState, build_graph
from core.config import load_config
from core.memory import MemoryStore
from core.policy_engine import PolicyEngine

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config()
    memory = MemoryStore()
    policy = PolicyEngine(config, memory)

    # Use a single-step graph invocation to inspect current behaviour on the
    # latest observations stored in MemoryStore.
    graph = build_graph(config, memory, policy, dry_run=True)

    # Seed state with last_observations if present so REASON has context even
    # without a fresh PERCEIVE step.
    mem_state = memory.load()
    observations = mem_state.get("last_observations", "")
    state: AgentState = {
        "observations": observations,
        "plan": None,
        "action_result": "",
        "reflection": "",
        "done": False,
        "step": 0,
        "last_action_type": None,
    }

    # Run through REASON only by invoking the compiled graph nodes directly.
    # This keeps things simple without needing a separate REASON-only graph.
    result = graph.invoke(state)
    logger.info("backtest result plan: %s", result.get("plan"))


if __name__ == "__main__":
    main()

