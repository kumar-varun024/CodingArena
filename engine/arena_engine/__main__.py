"""Run with PYTHONPATH=engine python -m arena_engine."""

import argparse
import json

from .contract import CONTRACT_SHA256, load_contract
from .runtime import runtime_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Coding Arena engine foundation")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("contract", help="verify frozen v1 manifest")
    commands.add_parser("doctor", help="check Docker/image readiness without reading tokens")
    serve = commands.add_parser("serve", help="serve the Sprint 1 health endpoint")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "contract":
        load_contract()
        print(json.dumps({"contract_version": "1.0", "canonical_sha256": CONTRACT_SHA256}))
        return 0
    if args.command == "doctor":
        status = runtime_status()
        print(json.dumps(status, sort_keys=True))
        return 0 if status["image_available"] else 1
    import uvicorn
    uvicorn.run("arena_engine.api:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
