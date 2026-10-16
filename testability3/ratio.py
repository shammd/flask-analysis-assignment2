from pathlib import Path

folder = Path(__file__).parent
root = folder.parent
output = folder / "flask_line_count_results.txt"


def count_lines(directory):
    return sum(
        1
        for file in directory.rglob("*.py")
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


prod = count_lines(root / "src/flask")
tests = count_lines(root / "tests")
ratio = tests / prod if prod else 0

with output.open("w", encoding="utf-8") as f:
    f.write("Filtered:\n")
    f.write(f"Production: {prod:,}\n")
    f.write(f"Tests: {tests:,}\n")
    f.write(f"Ratio: {ratio:.2f} ({ratio:.2%})\n")

print(f"Results saved to: {output.resolve()}")
