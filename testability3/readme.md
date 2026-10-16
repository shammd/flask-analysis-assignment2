# Flask Testability Analysis
Code Quality Analysis

Flask commit: 22d924701a6ae2e4cd01e9a15bbaf3946094af65

Tools: Python 3.14.3, Radon 6.0.1, Coverage.py 7.16.2, pytest 8.4.2.

All three scripts are located in the testability/ directory in the Flask repository root.

Install dependencies:

python -m pip install radon==6.0.1 coverage==7.16.2 pytest==8.4.2


Run from the Flask repository root:

python testability/complexity.py
python testability/coverage_analysis.py
python testability/line_count.py


This folder contains Python scripts for analyzing the testability of Flask 3.1.3 using the cloned Flask repository.

- `coverage.py` – Generates `flask_coverage_results.txt`, containing the Test Coverage.
- `ratio.py` – Generates `flask_line_count_results.txt`, containing the resulting ratio.
- `complexity.py` – Generates `flask_complexity_results.txt`, containing the cyclomatic complexity analysis results.

Each results file is generated when its corresponding Python script is executed.

Note: all measurements were performed directly in the terminal. Later, Python scripts were added to the Flask repository in a new file named testability to save the results and demonstrate how the measurements could be generated and reproduced within the repository. The original approach and results remain the same; the additional files simply make the process easier to reproduce and preserve the output for reference. 

