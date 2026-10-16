import argparse
import csv
import json
import platform
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
VERSIONS_DIR = ROOT / "versions" 
VENVS_DIR = ROOT / "venvs" 
RESULTS_DIR = ROOT / "results" / "versions"

CONFIGS = {
    "flask-1.1.4":                    ("1.1.4", "1.0.1", "release"),
    "flask-2.0.3":                    ("2.0.3", "2.0.3", "release"),
    "flask-2.1.3":                    ("2.1.3", "2.1.2", "release"),
    "mix-flask-2.1.3_werkzeug-2.2.3": ("2.1.3", "2.2.3", "mixed"),
    "flask-2.2.5":                    ("2.2.5", "2.2.3", "release"),
    "flask-2.3.3":                    ("2.3.3", "2.3.8", "release"),
    "flask-3.0.3":                    ("3.0.3", "3.0.6", "release"),
    "flask-3.1.3":                    ("3.1.3", "3.1.9", "release"),
}

def venv_python(name):
    """Path to the python executable inside venvs/<name>/ (differs on Windows)."""
    folder = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    return VENVS_DIR / name / folder / exe

def installed_versions(name):
    """Ask the environment itself which Flask and Werkzeug it has."""
    code = ("from importlib.metadata import version; "
            "print(version('flask'), version('werkzeug'))")
    out = subprocess.run([str(venv_python(name)), "-c", code],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[0], out[1]


def setup(name, reinstall=False):
    """Create venvs/<name>/ and install versions/<name>.txt. Returns True if ready."""
    expected = CONFIGS[name][:2]
    python = venv_python(name)

    if python.exists() and not reinstall:
        try:
            if installed_versions(name) == expected:
                return True
        except subprocess.CalledProcessError:
            pass

    print(f"  setting up {name} ...")
    subprocess.run([sys.executable, "-m", "venv", "--clear", str(VENVS_DIR / name)], check=True)
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-r", str(VERSIONS_DIR / f"{name}.txt")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  !! installing {name} failed:\n{result.stderr[-1500:]}")
        return False

    actual = installed_versions(name)
    if actual != expected:
        print(f"  !! {name}: expected Flask/Werkzeug {expected}, got {actual}")
        return False
    return True


def read_summary(path):
    """overhead_summary_*.csv -> {app: median_us}"""
    with path.open(newline="") as f:
        return {row["app"]: float(row["median_us"]) for row in csv.DictReader(f)}


def main():
    parser = argparse.ArgumentParser(description="Metric 3: overhead across Flask versions")
    parser.add_argument("--rounds", type=int, default=3, help="times the full list is measured (default 3)")
    parser.add_argument("--only", nargs="+", choices=CONFIGS, metavar="NAME",
                        help="measure only these configurations")
    parser.add_argument("--requests", type=int, default=10_000, help="requests per run (passed on)")
    parser.add_argument("--runs", type=int, default=7, help="timed runs per app (passed on)")
    parser.add_argument("--reinstall", action="store_true", help="rebuild environments from scratch")
    parser.add_argument("--setup-only", action="store_true", help="build environments, measure nothing")
    args = parser.parse_args()

    names = args.only or list(CONFIGS)

    print(f"Python used for all environments: {platform.python_version()} ({sys.executable})")
    print("Preparing environments:")
    ready = [name for name in names if setup(name, args.reinstall)]
    skipped = [name for name in names if name not in ready]
    print(f"  ready: {len(ready)}   failed: {', '.join(skipped) or 'none'}\n")
    if args.setup_only or not ready:
        return

    started_at = datetime.now()
    session_dir = RESULTS_DIR / started_at.strftime("%Y%m%d-%H%M%S")
    raw_dir = session_dir / "raw"

    round_rows = []
    for round_no in range(1, args.rounds + 1):
        order = ready if round_no % 2 == 1 else list(reversed(ready))
        for name in order:
            label = f"{name}_round{round_no}"
            print(f"=== Round {round_no}/{args.rounds}: {name}")
            subprocess.run(
                [str(venv_python(name)), str(ROOT / "measure_overhead.py"),
                 "--label", label, "--out-dir", str(raw_dir),
                 "--requests", str(args.requests), "--runs", str(args.runs)],
                cwd=ROOT, check=True,
            )
            medians = read_summary(raw_dir / f"overhead_summary_{label}.csv")
            flask_v, werkzeug_v, kind = CONFIGS[name]
            round_rows.append({
                "config": name, "kind": kind, "flask": flask_v, "werkzeug": werkzeug_v,
                "round": round_no,
                "bare_wsgi_us": medians["bare_wsgi"],
                "werkzeug_app_us": medians["werkzeug"],
                "flask_app_us": medians["flask"],
                "flask_vs_werkzeug_us": medians["flask"] - medians["werkzeug"],
            })
            print()

    number_cols = ["bare_wsgi_us", "werkzeug_app_us", "flask_app_us", "flask_vs_werkzeug_us"]
    summary_rows = []
    for name in ready:  # keep the chronological order from CONFIGS
        rows = [r for r in round_rows if r["config"] == name]
        summary = {key: rows[0][key] for key in ("config", "kind", "flask", "werkzeug")}
        summary["rounds"] = len(rows)
        for col in number_cols:
            values = [r[col] for r in rows]
            summary[col] = statistics.median(values)
            summary[col.replace("_us", "_spread_us")] = max(values) - min(values)
        summary_rows.append(summary)

    def write(path, rows):
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            for row in rows:
                writer.writerow({k: f"{v:.3f}" if isinstance(v, float) else v for k, v in row.items()})

    write(session_dir / "versions_rounds.csv", round_rows)
    write(session_dir / "versions_summary.csv", summary_rows)
    (session_dir / "session.json").write_text(json.dumps({
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "python_version": sys.version,
        "os": platform.platform(),
        "processor": platform.processor(),
        "rounds": args.rounds,
        "requests_per_run": args.requests,
        "runs_per_app": args.runs,
        "configs_measured": {n: dict(zip(("flask", "werkzeug", "kind"), CONFIGS[n])) for n in ready},
        "configs_failed": skipped,
        "order": "configurations measured in CONFIGS order, reversed every other round",
    }, indent=2))

    print(f"Median over {args.rounds} round(s), µs per request:\n")
    print(f"{'configuration':32} {'bare':>6} {'werkzeug':>9} {'flask':>8} {'flask-wz':>9}")
    for s in summary_rows:
        print(f"{s['config']:32} {s['bare_wsgi_us']:6.2f} {s['werkzeug_app_us']:9.2f} "
              f"{s['flask_app_us']:8.2f} {s['flask_vs_werkzeug_us']:9.2f}")
    print(f"\nSaved in {session_dir}")


if __name__ == "__main__":
    main()