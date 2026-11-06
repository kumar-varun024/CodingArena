"""Human operator HTTP client with a persistent, non-secret retry journal."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from .contract import canonical_bytes


def parser(commands):
    operator = commands.add_parser("operator", help="human operator HTTP commands")
    operator.add_argument("--api-url", default=os.environ.get("ARENA_API_URL", "http://127.0.0.1:8765"))
    operations = operator.add_subparsers(dest="operation", required=True)
    create = operations.add_parser("create")
    create.add_argument("--label-a", default="Unavailable")
    create.add_argument("--label-b", default="Unavailable")
    create.add_argument("--budget-minutes", type=int, default=10)
    create.add_argument("--max-repair-rounds", type=int, default=2)
    action = operations.add_parser("action")
    action.add_argument("--match", required=True)
    action.add_argument("--action", choices=["reveal", "cancel", "start_repair", "finalize"], required=True)
    action.add_argument("--reason", required=True)
    for mutation in (create, action):
        mutation.add_argument("--request-id", type=UUID)
        mutation.add_argument("--room-id")
        mutation.add_argument("--message-id")
        mutation.add_argument("--note")
        mutation.add_argument("--source-kind", choices=["operator_recorded", "fixture"], default="operator_recorded")
    retry = operations.add_parser("retry", help="resend an exact journalled operation")
    retry.add_argument("--request-id", type=UUID, required=True)
    match = operations.add_parser("match")
    match.add_argument("--match", required=True)
    job = operations.add_parser("job")
    job.add_argument("--id", required=True)


def run(args, settings):
    method, body = "POST", None
    journal_root = settings.state_dir / "operator-requests"
    if args.operation == "retry":
        record = json.loads((journal_root / (str(args.request_id) + ".json")).read_text())
        endpoint, body = record["endpoint"], record["body"]
    elif args.operation in ("match", "job"):
        method = "GET"
        endpoint = "/matches/" + args.match if args.operation == "match" else "/jobs/" + args.id
    else:
        request_id = str(args.request_id or uuid4())
        source = {"kind": args.source_kind, "room_id": args.room_id,
                  "message_id": args.message_id, "note": args.note}
        body = {"request_id": request_id, "source": source}
        if args.operation == "create":
            endpoint = "/matches"
            body.update(task_id="booking-v1", candidate_budget_minutes=args.budget_minutes,
                        max_repair_rounds=args.max_repair_rounds,
                        provider_labels={"a": args.label_a, "b": args.label_b})
        else:
            endpoint = "/matches/" + args.match + "/actions"
            body.update(action=args.action, reason=args.reason)
        record = {"endpoint": endpoint, "body": body}
        journal_root.mkdir(mode=0o700, exist_ok=True)
        destination = journal_root / (request_id + ".json")
        if destination.exists():
            if canonical_bytes(json.loads(destination.read_text())) != canonical_bytes(record):
                raise ValueError("Request ID already journalled with a different operation/body")
        else:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical_bytes(record))
                stream.flush()
                os.fsync(stream.fileno())
    if body is not None:
        print("request_id=" + body["request_id"], file=sys.stderr)
    token = (settings.state_dir / "auth/operator.token").read_text().strip()
    request = Request(args.api_url.rstrip("/") + "/api/v1" + endpoint, method=method,
                      data=canonical_bytes(body) if body is not None else None,
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            print(response.read().decode("utf-8"))
        return 0
    except HTTPError as exc:
        print(exc.read().decode("utf-8"))
        return 1
    except (URLError, TimeoutError):
        print("Transport failed; outcome is unknown. Retry the same request ID using operator retry.", file=sys.stderr)
        return 1
