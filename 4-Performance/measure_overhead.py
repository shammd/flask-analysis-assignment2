import timeit
from pathlib import Path
from importlib.metadata import version
import subprocess
import os
import platform
import sys
import csv
import argparse
from datetime import datetime
import statistics
import json

from werkzeug.test import EnvironBuilder
import flask

from apps import APPS
REQUESTS_PER_RUN = 10000
RUNS = 7


ENVIRON = EnvironBuilder(path="/hello", method="GET").get_environ()


def start_response(status, headers, exc_info=None):
    pass

def handle_request(app):
    environ = ENVIRON.copy() # we do a fresh dictrionary per request
    body = app(environ, start_response)
    for i in body:
        pass
    if hasattr(body, "close"):
        body.close()

def measure_function(app, requests_per_run, runs):
    timer = timeit.Timer(lambda: handle_request(app))
    timer.timeit(number=requests_per_run)
    return timer.repeat(repeat=runs, number=requests_per_run)

def flask_version_check():
    flask_path = Path(flask.__file__).resolve().parent
    root = flask_path.parents[1]

    if flask_path != root / "src" / "flask":
        return "Wrong flask"
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def environment(started_at, label, requests_per_run, runs):
    return {"label": label,
            "started_at": started_at.isoformat(timespec="seconds"),
            "python_version": sys.version,
            "python_executable": sys.executable,
            "python_implementation": platform.python_implementation(),
            "os": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "flask_version": version("flask"),
            "flask_git_commit": flask_version_check(),
            "werkzeug_version": version("werkzeug"),
            "settings": {
                "requests_per_run": requests_per_run,
                "runs": runs,
                "request": "GET /hello",
                "method": "Direct WSGI call, build environ once, one warmup run discarded",
            },
        }

def write_csv_file(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    # full proofing for different version measurements
    parser = argparse.ArgumentParser(description="Metric 1: Per-request overhead")
    parser.add_argument("--label")
    parser.add_argument("--out-dir", default=Path(__file__).parent / "results" / "overhead", type=Path)
    parser.add_argument("--requests", type=int, default=REQUESTS_PER_RUN)
    parser.add_argument("--runs", type=int, default=RUNS)
    args = parser.parse_args()

    started_at = datetime.now()
    label = args.label or started_at.strftime("%Y%m%d-%H%M%S")
    args.out_dir.mkdir(parents=True, exist_ok=True)


    run_rows, summary_rows, medians = [], [], {}
    for app_name, app in APPS.items():
        totals = measure_function(app, args.requests, args.runs)
        per_request = []
        for t in totals:
            per_request.append(t/args.requests * 1000000)

        for run_index, (total, us) in enumerate(zip(totals, per_request), start=1):
            run_rows.append({"app": app_name, "run": run_index, "requests": args.requests, "total_seconds": f"{total:.6f}", "us_per_request": f"{us:.3f}"})

        medians[app_name] = statistics.median(per_request)
        summary_rows.append({"app": app_name, "median_us": f"{medians[app_name]:.3f}", 
                             "min_us": f"{min(per_request):.3f}",
                             "max_us": f"{max(per_request):.3f}",
                             "stdev_us": f"{statistics.stdev(per_request):.3f}"})

        formatted = []
        for us in per_request:
            formatted.append(f"{us:6.2f}")

        runs_text = "  ".join(formatted)
        print(f"{app_name:10} median {medians[app_name]:7.2f} µs  runs: {runs_text}")

    breakdown = {
        "Werkzeug_vs_baseline_us": medians["werkzeug"] - medians["bare_wsgi"],
        "flask_vs_werkzeug_us": medians["flask"] - medians["werkzeug"],
        "flask_vs_baseline_us": medians["flask"] - medians["bare_wsgi"],
    }

    print("Breakdown from medians")
    print(f"Werkzeug only vs baseline: {breakdown['Werkzeug_vs_baseline_us']:7.2f} µs")
    print(f"Flask added cost vs werkzeug only: {breakdown['flask_vs_werkzeug_us']:7.2f} µs")
    print(f"Total flask vs baseline: {breakdown['flask_vs_baseline_us']:7.2f} µs")

    write_csv_file(args.out_dir / f"overhead_runs_{label}.csv", run_rows)
    write_csv_file(args.out_dir / f"overhead_summary_{label}.csv", summary_rows)
    env = environment(started_at, label, args.requests, args.runs)
    rounded = {}
    for key, value in breakdown.items():
        rounded[key] = round(value, 3)

    env["breakdown_us"] = rounded

    (args.out_dir / f"overhead_env_{label}.json").write_text(json.dumps(env, indent=2))



if __name__ == "__main__":
    main()
