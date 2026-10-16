import argparse
import cProfile
import csv
import inspect
import json
import platform
import pstats
import statistics
import sys
import timeit
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import flask
import werkzeug.wrappers.response
from flask import ctx, sessions

from apps import APPS
from measure_overhead import flask_version_check, handle_request

ROOT = Path(__file__).resolve().parent
DEFAULT_REQUESTS = 10_000

GROUPS = ["flask", "werkzeug", "apps.py", "stdlib/builtins", "other libraries", "harness"]
PASS_THROUGH = "stdlib/builtins" 


def group_of(filename):
    path = filename.replace("\\", "/")
    if path == "~" or path.startswith("<"):
        return "stdlib/builtins"
    if path.endswith("/apps.py"):
        return "apps.py"
    if path.endswith(("/measure_overhead.py", "/profile_calls.py")):
        return "harness"
    if "/flask/" in path:
        return "flask"
    if "/werkzeug/" in path:
        return "werkzeug"
    if "site-packages/" in path:
        return "other libraries"
    return "stdlib/builtins"


def short_path(filename):
    path = filename.replace("\\", "/")
    for marker in ("site-packages/", "/src/"):
        if marker in path:
            return path.rsplit(marker, 1)[1]
    return "/".join(path.split("/")[-2:])


# --- Profiling ----------------------------------------------------------------------

def unprofiled_us(app, requests):
    """Median µs per request without profiler (3 runs), to quantify profiler overhead."""
    timer = timeit.Timer(lambda: handle_request(app))
    timer.timeit(number=requests)
    return statistics.median(timer.repeat(repeat=3, number=requests)) / requests * 1e6


def profile(app, requests):
    for _ in range(requests):
        handle_request(app)
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(requests):
        handle_request(app)
    profiler.disable()
    stats = pstats.Stats(profiler)
    for key in [k for k in stats.stats if "_lsprof" in k[2]]:
        del stats.stats[key]
    return profiler, stats


def incl_attribution(stats):
    memo = {}

    def attribution(key, stack):
        if key in memo:
            return memo[key]
        group = group_of(key[0])
        if group != PASS_THROUGH:
            return {group: 1.0}
        callers = stats.stats[key][4]
        weights = {c: v[3] for c, v in callers.items() if c not in stack}
        total = sum(weights.values())
        if not callers or total == 0:
            result = {PASS_THROUGH: 1.0}
        else:
            result = {}
            for caller, weight in weights.items():
                for g, frac in attribution(caller, stack | {key}).items():
                    result[g] = result.get(g, 0.0) + frac * weight / total
        memo[key] = result
        return result

    return {key: attribution(key, frozenset()) for key in stats.stats}


def summarize(stats, requests):
    """Per group: calls/request, own µs/request, incl µs/request."""
    calls = dict.fromkeys(GROUPS, 0.0)
    own = dict.fromkeys(GROUPS, 0.0)
    incl = dict.fromkeys(GROUPS, 0.0)
    attribution = incl_attribution(stats)

    for key, (_cc, ncalls, tottime, _cumtime, callers) in stats.stats.items():
        group = group_of(key[0])
        calls[group] += ncalls / requests
        own[group] += tottime / requests * 1e6
        if group != PASS_THROUGH:
            incl[group] += tottime / requests * 1e6
        else:
            for caller, (_c, _n, caller_tt, _ct) in callers.items():
                for g, frac in attribution[caller].items():
                    incl[g] += caller_tt * frac / requests * 1e6
            if not callers:
                incl[PASS_THROUGH] += tottime / requests * 1e6
    return calls, own, incl


def function_rows(stats, requests):
    rows = []
    for (filename, line, name), (_cc, ncalls, tottime, cumtime, _callers) in stats.stats.items():
        rows.append({
            "group": group_of(filename),
            "file": short_path(filename),
            "line": line,
            "function": name,
            "calls_per_request": round(ncalls / requests, 3),
            "own_us_per_request": round(tottime / requests * 1e6, 3),
            "cumulative_us_per_request": round(cumtime / requests * 1e6, 3),
        })
    return sorted(rows, key=lambda r: r["own_us_per_request"], reverse=True)

LIFECYCLE = [
    ("Flask.wsgi_app (whole request inside Flask)",          flask.Flask.wsgi_app),
    ("1  create request context (Request, URL adapter)",     flask.Flask.request_context),
    ("2  push contexts",                                     ctx.RequestContext.push),
    ("   2a URL matching",                                   ctx.RequestContext.match_request),
    ("   2b open session",                                   sessions.SecureCookieSessionInterface.open_session),
    ("3  full_dispatch_request",                             flask.Flask.full_dispatch_request),
    ("   3a before_request hooks",                           flask.Flask.preprocess_request),
    ("   3b dispatch to view function",                      flask.Flask.dispatch_request),
    ("   3c finalize (make_response, after_request, save session)", flask.Flask.finalize_request),
    ("4  send response (Response as WSGI app)",              werkzeug.wrappers.response.Response.__call__),
    ("5  pop contexts (teardown)",                           ctx.RequestContext.pop),
]


def lifecycle_rows(stats, requests):
    by_location = {(Path(f).resolve(), line, name): v for (f, line, name), v in stats.stats.items()
                   if not f.startswith(("~", "<"))}
    rows = []
    total = None
    for label, func in LIFECYCLE:
        key = (Path(inspect.getsourcefile(func)).resolve(), inspect.getsourcelines(func)[1], func.__name__)
        entry = by_location.get(key)
        if entry is None:
            print(f"   warning: lifecycle step '{label.strip()}' not found in the profile")
        cum_us = entry[3] / requests * 1e6 if entry else 0.0
        if total is None:
            total = cum_us
        rows.append({
            "step": label,
            "function": func.__qualname__,
            "cumulative_us_per_request": round(cum_us, 3),
            "share_of_wsgi_app": round(cum_us / total, 4) if total else 0.0,
        })
    return rows


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Metric 2: calls and time distribution per request")
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS, help="profiled requests per app")
    parser.add_argument("--label", help="output folder name (default: date and time)")
    args = parser.parse_args()

    started_at = datetime.now()
    label = args.label or started_at.strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "results" / "profile" / label
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Flask {version('flask')}, Werkzeug {version('werkzeug')}, Python {platform.python_version()}")
    print(f"Profiling {args.requests} requests per app (after an unprofiled warm-up)\n")

    group_rows, overhead_info = [], {}
    for app_name, app in APPS.items():
        plain_us = unprofiled_us(app, args.requests)
        profiler, stats = profile(app, args.requests)
        profiler.dump_stats(out_dir / f"{app_name}.prof")   # raw profile, e.g. for snakeviz
        write_csv(out_dir / f"functions_{app_name}.csv", function_rows(stats, args.requests))

        calls, own, incl = summarize(stats, args.requests)
        profiled_us = sum(own.values())
        overhead_info[app_name] = {"unprofiled_us": round(plain_us, 3),
                                   "profiled_us": round(profiled_us, 3),
                                   "slowdown_factor": round(profiled_us / plain_us, 2)}
        for group in GROUPS:
            group_rows.append({
                "app": app_name, "group": group,
                "calls_per_request": round(calls[group], 3),
                "own_us_per_request": round(own[group], 3),
                "own_share": round(own[group] / profiled_us, 4),
                "incl_us_per_request": round(incl[group], 3),
                "incl_share": round(incl[group] / profiled_us, 4),
            })

        print(f"=== {app_name}: {sum(calls.values()):.0f} calls per request, "
              f"{plain_us:.1f} µs without profiler, {profiled_us:.1f} µs with "
              f"(x{profiled_us / plain_us:.1f})")
        print(f"   {'group':18} {'calls/req':>9} {'own time':>9} {'incl. stdlib':>13}")
        for group in GROUPS:
            if calls[group]:
                print(f"   {group:18} {calls[group]:9.1f} {own[group] / profiled_us:9.1%} "
                      f"{incl[group] / profiled_us:13.1%}")
        print()

        if app_name == "flask":
            lifecycle = lifecycle_rows(stats, args.requests)
            write_csv(out_dir / "lifecycle_flask.csv", lifecycle)

    print("=== Flask lifecycle: share of time inside Flask.wsgi_app (profiled)")
    for row in lifecycle:
        print(f"   {row['step']:60} {row['share_of_wsgi_app']:6.1%}")

    write_csv(out_dir / "groups.csv", group_rows)
    (out_dir / "profile_env.json").write_text(json.dumps({
        "started_at": started_at.isoformat(timespec="seconds"),
        "python_version": sys.version,
        "os": platform.platform(),
        "processor": platform.processor(),
        "flask_version": version("flask"),
        "flask_git_commit": flask_version_check(),
        "werkzeug_version": version("werkzeug"),
        "requests_profiled_per_app": args.requests,
        "method": "cProfile around direct WSGI calls (same harness as measure_overhead.py), "
                  "one unprofiled warm-up of the same size first",
        "profiler_overhead": overhead_info,
    }, indent=2))
    print(f"\nSaved in {out_dir}")


if __name__ == "__main__":
    main()