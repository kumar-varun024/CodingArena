# Engine foundation

Sprint 1 implements the frozen contract loader, bounded scenario driver, read-only runtime doctor and FastAPI health endpoint. The Docker fixture checker runs trusted test data against frozen fixture modules. It does not submit candidates or establish eligibility.

## HTTP surface

`GET /api/v1/health` requires no token and returns exactly:

```json
{"api_version":"1.0","mode":"live","runner_available":false,"status":"ok"}
```

`status=ok` means the service is running. `runner_available=false` is intentional until the production job executor lands in Sprint 2. Unimplemented routes return 404 with the v1 JSON error envelope. The API does not advertise match mutations as working.

A response captured from the running service is saved in [sprint1-api-snapshot.json](../contracts/sprint1-api-snapshot.json) for B's comparison. It covers health only.

The complete normative interface is [arena-v1.json](../contracts/arena-v1.json). Canonicalization uses UTF-8 JSON with sorted keys, compact separators, unescaped Unicode and no trailing newline. SHA-256: `3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80`. File whitespace is irrelevant to this digest.

## Task pack and trusted driver

`fixtures/booking-v1/starter/` is the only directory eligible for future task checkout provisioning. The frozen specification must also be copied into those checkouts. Reference, held-out cases and known-good/bad fixtures remain engine-owned. Fixture data is never evidence of a live agent discovery.

`engine/arena_engine/driver.py` validates the frozen Scenario shape before loading a module. Bounds include 1–20 capacity, 1–30 operations, fixed operation arity and bounded JSON values. Invalid business arguments such as boolean, null or negative seats remain valid scenario data. Expectations allow boolean, integer or string-to-integer maps; comparisons preserve types, so `true` differs from `1`.

Candidate code is loaded only inside disposable Docker test containers. The server never imports submitted implementations. Trusted unit tests use toy factories, while the task-pack check runs fixture implementations in Docker. The private instance-isolation check covers BOOK-07 without changing the public Scenario interface.

The fixture checker uses a pinned Python image, fresh containers, no network, read-only source/driver/root mounts, non-root execution, temporary scratch, dropped capabilities, resource limits and a wall-clock timeout. This is foundation verification on synthetic fixtures; official challenge reproduction, persistent jobs, immutable submissions and selection are Sprint 2/3 work. Restricted containers do not make this a hostile-agent hosting platform.

See [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/) and [Docker run controls](https://docs.docker.com/reference/cli/docker/container/run/) for the underlying API and isolation options.

## Deferred work

Sprint 2 adds marked disposable task Git roots, token provisioning, SQLite persistence, request-id idempotency, assignment/submission projections and real verification jobs. Sprint 3 adds challenges, adjudication, stale-evidence invalidation, repairs, recovery and exports. Tests of those properties cannot be claimed by this skeleton.
