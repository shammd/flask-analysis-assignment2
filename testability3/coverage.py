import subprocess
import sys
from pathlib import Path

folder = Path("testability")
folder.mkdir(exist_ok=True)

output = folder / "flask_coverage_results.txt"

with output.open("w", encoding="utf-8") as f:
    subprocess.run(
        [sys.executable, "-m", "coverage", "run",
         "--source=flask", "-m", "pytest"],
        stdout=f, stderr=subprocess.STDOUT
    )

    report = subprocess.run(
        [sys.executable, "-m", "coverage", "report", "-m"],
        capture_output=True, text=True
    )

    f.write("\n\nCoverage Report:\n")
    f.write(report.stdout)

print(f"Results saved to: {output.resolve()}")