import subprocess
import sys
from pathlib import Path

folder = Path(__file__).parent
root = folder.parent
output = folder / "flask_complexity_results.txt"

with output.open("w", encoding="utf-8") as f:
    subprocess.run(
        [sys.executable, "-m", "radon", "cc",
         str(root / "src/flask"), "-a", "-s"],
        stdout=f,
        stderr=subprocess.STDOUT
    )

print(f"Results saved to: {output.resolve()}")