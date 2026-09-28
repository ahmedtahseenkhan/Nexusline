#!/usr/bin/env python3
"""Load-test the Aegis GRC API the way a bank's users actually hit it.

Not a synthetic hammer on one URL: each virtual user signs in once, then loops through a
weighted mix of the calls a real session makes — the asset register's first page, a page
deep in the register, a search, the stat cards, one record, the dashboard and the
notification poll. Latency is reported per endpoint, because "the app is slow" is almost
always one endpoint, not all of them.

  # 25 concurrent users for two minutes against a local stack
  python scripts/loadtest.py --base-url http://localhost:8080 --users 25 --duration 120

  # gate a release: fail the run if p95 on any endpoint exceeds 1.5s
  python scripts/loadtest.py --users 50 --duration 300 --p95-budget 1500

Fill the register first, or the numbers mean nothing:
  docker compose exec api python -m app.tools.bulkdata generate --org acme --assets 10000

Needs only httpx (already a backend dependency):  pip install httpx
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

try:
    import httpx
except ImportError:  # pragma: no cover - guidance beats a traceback
    sys.exit("httpx is required:  pip install httpx")


# --------------------------------------------------------------------- scenario ---
# (weight, label, method, path builder). Weights are relative: the register's first page
# is loaded far more often than the dashboard, so it carries more of the load.
def _scenario(state: dict, exclude: list[str] | None = None, only: list[str] | None = None) -> list[tuple]:
    total = max(state.get("total", 0), 1)
    pages = max((total - 1) // 50, 0)

    def deep_offset() -> int:
        # Uniform across the register, so the count query and OFFSET are both exercised
        # at their worst, not just page 1 which any cache would flatter.
        return random.randint(0, pages) * 50

    calls = [
        (30, "assets: first page", "GET", lambda: "/api/v1/assets?limit=50&offset=0&sort_by=name"),
        (20, "assets: deep page", "GET", lambda: f"/api/v1/assets?limit=50&offset={deep_offset()}&sort_by=name"),
        (12, "assets: search", "GET", lambda: f"/api/v1/assets?limit=50&search={random.choice(_TERMS)}"),
        # Two sorts that cost more than ORDER BY name: a computed expression and a
        # correlated subquery on the owner's name. Both are one click in the UI.
        (5, "assets: sort by criticality", "GET",
         lambda: "/api/v1/assets?limit=50&offset=0&sort_by=effective_criticality&sort_dir=desc"),
        (3, "assets: sort by owner", "GET",
         lambda: "/api/v1/assets?limit=50&offset=0&sort_by=owner"),
        (6, "assets: overdue filter", "GET", lambda: "/api/v1/assets?limit=50&review_overdue=true"),
        (8, "assets: stat cards", "GET", lambda: "/api/v1/assets/summary"),
        (8, "asset: one record", "GET",
         lambda: f"/api/v1/assets/{random.choice(state['ids'])}" if state.get("ids") else None),
        # What the UI actually loads: the redesigned dashboard's single payload, the
        # bell on every page (fresh=false, cached scan) and the notifications page
        # (fresh=true, which re-scans the whole tenant inside the request).
        (5, "dashboard overview", "GET", lambda: "/api/v1/dashboard/overview?days=30"),
        (6, "notifications bell", "GET", lambda: "/api/v1/notifications?limit=1&fresh=false"),
        (2, "notifications page", "GET", lambda: "/api/v1/notifications?limit=100&fresh=true"),
    ]
    # --exclude isolates a suspect endpoint: run the same mix without it and see whether
    # everything else recovers. That is how you tell one slow call from a slow app.
    if only:
        calls = [c for c in calls if any(t.lower() in c[1].lower() for t in only)]
    if exclude:
        calls = [c for c in calls if not any(t.lower() in c[1].lower() for t in exclude)]
    if not calls:
        sys.exit("--only/--exclude left no endpoints in the mix.")
    return calls


_TERMS = ["core", "atm", "server", "customer", "card", "branch", "data", "gateway", "switch", "node"]


@dataclass
class Bucket:
    """Latency samples for one endpoint label."""

    ms: list[float] = field(default_factory=list)
    errors: int = 0
    statuses: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    bytes_total: int = 0

    def pct(self, p: float) -> float:
        if not self.ms:
            return 0.0
        ordered = sorted(self.ms)
        # Nearest-rank percentile: no interpolation, so a reported p95 is a real request.
        idx = min(int(round(p / 100 * len(ordered) + 0.5)) - 1, len(ordered) - 1)
        return ordered[max(idx, 0)]


async def login(client: httpx.AsyncClient, org: str, email: str, password: str) -> str:
    try:
        r = await client.post(
            "/api/v1/auth/login",
            json={"tenant_slug": org, "email": email, "password": password},
        )
    except httpx.HTTPError as exc:
        sys.exit(f"Cannot reach {client.base_url}: {type(exc).__name__}: {exc}")
    if r.status_code != 200:
        sys.exit(f"Login failed ({r.status_code}): {r.text[:300]}")
    body = r.json()
    if body.get("mfa_required"):
        sys.exit(
            "This account requires MFA, which a load test cannot complete. Use a service "
            "account with MFA off, or set MFA_ENFORCEMENT=off on the test install."
        )
    return body["access_token"]


def _weighted(scenario: list[tuple]) -> tuple:
    total = sum(w for w, *_ in scenario)
    mark = random.uniform(0, total)
    upto = 0.0
    for entry in scenario:
        upto += entry[0]
        if upto >= mark:
            return entry
    return scenario[-1]


async def user_loop(
    args: argparse.Namespace,
    token: str,
    state: dict,
    buckets: dict[str, Bucket],
    stop_at: float,
    counter: dict,
) -> None:
    """One virtual user: keep-alive connection, weighted call mix, optional think time."""
    scenario = _scenario(state, args.exclude, args.only)
    headers = {"Authorization": f"Bearer {token}"}
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=2)
    async with httpx.AsyncClient(
        base_url=args.base_url, headers=headers, timeout=args.timeout, limits=limits
    ) as client:
        while time.monotonic() < stop_at and counter["done"] < args.requests:
            _, label, method, build = _weighted(scenario)
            path = build()
            if path is None:
                continue
            started = time.perf_counter()
            bucket = buckets[label]
            try:
                r = await client.request(method, path)
                elapsed = (time.perf_counter() - started) * 1000
                bucket.statuses[r.status_code] += 1
                bucket.bytes_total += len(r.content)
                if r.status_code >= 400:
                    bucket.errors += 1
                    if args.verbose:
                        print(f"  {r.status_code} {path} -> {r.text[:200]}")
                else:
                    bucket.ms.append(elapsed)
            except Exception as exc:  # timeouts, resets, refused connections
                bucket.errors += 1
                bucket.statuses[0] += 1
                if args.verbose:
                    print(f"  ERR {path} -> {type(exc).__name__}: {exc}")
            counter["done"] += 1
            if args.think > 0:
                await asyncio.sleep(random.uniform(0, args.think * 2))


async def probe(args: argparse.Namespace, token: str) -> dict:
    """Read the register once: how many assets there are, and some real ids to fetch."""
    async with httpx.AsyncClient(
        base_url=args.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=args.timeout
    ) as client:
        started = time.perf_counter()
        try:
            r = await client.get("/api/v1/assets?limit=50&offset=0")
        except httpx.HTTPError as exc:
            sys.exit(f"Cannot read the asset register: {type(exc).__name__}: {exc}")
        first_page_ms = (time.perf_counter() - started) * 1000
        if r.status_code != 200:
            sys.exit(f"Cannot read /api/v1/assets ({r.status_code}): {r.text[:300]}")
        body = r.json()
        ids = [item["id"] for item in body.get("items", [])]
        total = body.get("total", len(ids))

        # A deliberately worst-case single call, measured before any load: the last page.
        deep_ms = None
        if total > 50:
            offset = ((total - 1) // 50) * 50
            started = time.perf_counter()
            try:
                dr = await client.get(f"/api/v1/assets?limit=50&offset={offset}&sort_by=name")
                if dr.status_code == 200:
                    deep_ms = (time.perf_counter() - started) * 1000
            except httpx.HTTPError:
                pass  # the ramp will measure it under load anyway
    return {"total": total, "ids": ids, "first_page_ms": first_page_ms, "deep_ms": deep_ms,
            "page_bytes": len(r.content)}


def report(args: argparse.Namespace, state: dict, buckets: dict[str, Bucket], wall: float) -> int:
    rows = [(label, b) for label, b in buckets.items() if b.ms or b.errors]
    rows.sort(key=lambda kv: kv[1].pct(95), reverse=True)
    ok = sum(len(b.ms) for _, b in rows)
    errors = sum(b.errors for _, b in rows)
    requests = ok + errors

    print()
    print("=" * 96)
    print(f"Register size      : {state['total']:,} assets")
    print(f"Cold single calls  : first page {state['first_page_ms']:.0f} ms"
          + (f", last page {state['deep_ms']:.0f} ms" if state.get("deep_ms") else "")
          + f", page payload {state['page_bytes'] / 1024:.0f} KB")
    print(f"Concurrent users   : {args.users}")
    print(f"Duration           : {wall:.1f} s")
    print(f"Requests           : {requests:,} ({errors:,} failed)  "
          f"throughput {requests / wall:.1f} req/s")
    print("=" * 96)
    head = f"{'endpoint':<32}{'n':>7}{'err':>6}{'p50':>9}{'p90':>9}{'p95':>9}{'p99':>9}{'max':>9}"
    print(head)
    print("-" * len(head))
    for label, b in rows:
        print(f"{label:<32}{len(b.ms):>7}{b.errors:>6}"
              f"{b.pct(50):>9.0f}{b.pct(90):>9.0f}{b.pct(95):>9.0f}"
              f"{b.pct(99):>9.0f}{(max(b.ms) if b.ms else 0):>9.0f}")
    print("-" * len(head))
    all_ms = [v for _, b in rows for v in b.ms]
    if all_ms:
        overall = Bucket(ms=all_ms)
        print(f"{'ALL (ms)':<32}{len(all_ms):>7}{errors:>6}"
              f"{overall.pct(50):>9.0f}{overall.pct(90):>9.0f}{overall.pct(95):>9.0f}"
              f"{overall.pct(99):>9.0f}{max(all_ms):>9.0f}")
        print(f"\nmean {statistics.fmean(all_ms):.0f} ms")

    non_2xx: dict[int, int] = defaultdict(int)
    for _, b in rows:
        for code, n in b.statuses.items():
            if code == 0 or code >= 400:
                non_2xx[code] += n
    if non_2xx:
        print("failures by status:", ", ".join(
            f"{'timeout/reset' if c == 0 else c}={n}" for c, n in sorted(non_2xx.items())))

    if args.json:
        payload = {
            "register_size": state["total"], "users": args.users, "duration_s": round(wall, 1),
            "requests": requests, "errors": errors, "throughput_rps": round(requests / wall, 1),
            "endpoints": {
                label: {
                    "n": len(b.ms), "errors": b.errors,
                    "p50": round(b.pct(50)), "p95": round(b.pct(95)), "p99": round(b.pct(99)),
                } for label, b in rows
            },
        }
        with open(args.json, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nWrote {args.json}")

    # Verdict — an explicit budget makes this usable as a release gate.
    failed = False
    error_rate = (errors / requests * 100) if requests else 0
    if error_rate > args.max_error_rate:
        print(f"\nFAIL: error rate {error_rate:.2f}% exceeds {args.max_error_rate}%")
        failed = True
    if args.p95_budget:
        over = [(label, b.pct(95)) for label, b in rows if b.pct(95) > args.p95_budget]
        if over:
            print(f"\nFAIL: p95 over budget ({args.p95_budget} ms): "
                  + ", ".join(f"{label} {ms:.0f} ms" for label, ms in over))
            failed = True
    if not failed:
        if args.p95_budget:
            print(f"\nPASS (no endpoint over {args.p95_budget:.0f} ms p95, "
                  f"failures {error_rate:.2f}%)")
        else:
            print(f"\nNo p95 budget set, so latency was not judged — pass --p95-budget to "
                  f"gate on it. Failures {error_rate:.2f}%.")
    return 1 if failed else 0


async def run(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout) as client:
        token = await login(client, args.org, args.email, args.password)
    state = await probe(args, token)
    if state["total"] < 1000:
        print(f"WARNING: only {state['total']} assets in '{args.org}'. This measures demo scale, "
              f"not bank scale — generate 6,000-10,000 first (see the docstring).\n")

    buckets: dict[str, Bucket] = defaultdict(Bucket)
    counter = {"done": 0}
    print(f"Running {args.users} users for {args.duration}s against {args.base_url} ...")
    started = time.monotonic()
    stop_at = started + args.duration
    await asyncio.gather(*[
        user_loop(args, token, state, buckets, stop_at, counter) for _ in range(args.users)
    ])
    return report(args, state, buckets, time.monotonic() - started)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="scripts/loadtest.py", description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--base-url", default="http://localhost:8080", help="API base URL (default %(default)s)")
    p.add_argument("--org", default="acme", help="tenant slug to sign in to")
    p.add_argument("--email", default="admin@acme.com")
    p.add_argument("--password", default="ChangeMe123!")
    p.add_argument("--users", type=int, default=20, help="concurrent virtual users")
    p.add_argument("--duration", type=int, default=60, help="seconds to run")
    p.add_argument("--requests", type=int, default=10**9, help="stop after this many requests")
    p.add_argument("--think", type=float, default=0.0,
                   help="mean seconds a user pauses between calls (0 = flat out)")
    p.add_argument("--timeout", type=float, default=60.0, help="per-request timeout, seconds")
    p.add_argument("--p95-budget", type=float, default=0,
                   help="fail the run if any endpoint's p95 exceeds this many ms")
    p.add_argument("--max-error-rate", type=float, default=1.0, help="fail above this %% of failures")
    p.add_argument("--exclude", action="append", default=[], metavar="TEXT",
                   help="drop endpoints whose label contains TEXT (repeatable)")
    p.add_argument("--only", action="append", default=[], metavar="TEXT",
                   help="keep only endpoints whose label contains TEXT (repeatable)")
    p.add_argument("--json", help="also write the summary to this JSON file")
    p.add_argument("--verbose", action="store_true", help="print every failure")
    args = p.parse_args(argv)
    args.base_url = args.base_url.rstrip("/")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
