"""Run with PYTHONPATH=engine python -m arena_engine."""

import argparse
import json

from .contract import CONTRACT_SHA256, load_contract
from .runtime import runtime_status
from .runtime import Settings
from .workspaces import initialize, read_runtime, WorkspaceError
from .persistence import Store
from . import operator_cli


def main() -> int:
    parser = argparse.ArgumentParser(description="Coding Arena local engine")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("contract", help="verify frozen v1 manifest")
    commands.add_parser("doctor", help="check Docker/image readiness without reading tokens")
    commands.add_parser("init", help="provision marked disposable workspaces and scoped tokens")
    operator_cli.parser(commands)
    serve = commands.add_parser("serve", help="serve the local v1 API and verification worker")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "init":
        metadata = initialize(settings)
        Store(settings.state_dir)
        print(json.dumps({**metadata, "operator_token_file": str(settings.state_dir / "auth/operator.token")}))
        return 0
    if args.command == "operator":
        read_runtime(settings)
        return operator_cli.run(args, settings)
    if args.command == "contract":
        contract = load_contract()
        print(json.dumps({"contract_version": contract["contract_version"], "canonical_sha256": CONTRACT_SHA256}))
        return 0
    if args.command == "doctor":
        status = runtime_status()
        print(json.dumps(status, sort_keys=True))
        return 0 if status["runner_available"] else 1
    read_runtime(settings)
    import uvicorn
    uvicorn.run("arena_engine.api:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkspaceError, OSError, ValueError) as exc:
        import sys
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
