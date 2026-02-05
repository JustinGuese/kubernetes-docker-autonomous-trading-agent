"""Entry point: load config → build graph → invoke → exit."""

from __future__ import annotations

import argparse
import logging
import sys

from core.agent import _initial_state, build_graph
from core.config import load_config
from core.memory import MemoryStore
from core.policy_engine import PolicyEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous trading agent runner")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="plan actions but do not execute wallet_send or swap on-chain",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logger.info("starting up (dry_run=%s)", args.dry_run)
    try:
        config = load_config()
    except EnvironmentError as exc:
        logger.error("configuration error: %s", exc)
        sys.exit(1)

    logger.info("config loaded — model=%s rpc=%s", config.llm.heavy_model, config.solana.rpc_url)

    memory = MemoryStore(config=config.memory)
    policy = PolicyEngine(config, memory)

    graph = build_graph(config, memory, policy, dry_run=args.dry_run)
    logger.info("graph built — invoking")
    result = graph.invoke(_initial_state())

    logger.info("─── done ───")
    logger.info("action_result: %s", result.get("action_result", ""))
    logger.info("reflection:    %s", result.get("reflection", ""))


if __name__ == "__main__":
    main()
