"""Agent-friendly command line entrypoint; uses the existing headless services."""
from core.agent_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
