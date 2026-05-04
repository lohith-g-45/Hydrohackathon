# HydroHackathon Run Guide

## 0. Prerequisites (install first)

- Python 3.9+ (recommended: Python 3.11)
- pip (Python package installer)

Install required packages:

py -3 -m pip install pandas numpy matplotlib plotly

If `py` is not available:

python -m pip install pandas numpy matplotlib plotly

## 1. Open a terminal in the project folder

Project folder:

D:\HYDROHACKATHON

## 2. Run the pipeline (default output in current folder)

Use this command:

py -3 main.py "HYDRO HACKATHON DATA.xlsx"

If `py` is not available, use:

python main.py "HYDRO HACKATHON DATA.xlsx"

## 3. Run with a custom output directory

Example:

py -3 main.py "HYDRO HACKATHON DATA.xlsx" --output-dir results

## 4. Expected core outputs

After a successful run, you should see these files generated:

- results.csv
- gz_curve.png
- hull_3d.html
- insights.txt

Note on 3D output:

- `hull_3d.html` is not a command/script to run.
- Open it in your browser after pipeline execution (double-click it, or run `start hull_3d.html` on Windows).

Advanced optional outputs (if polygon generation succeeds):

- real_kn_polygon.png
- real_gz_polygon_physical.png

## 5. Common issues

- If you get "file not found", check that `HYDRO HACKATHON DATA.xlsx` is in the same folder.
- If Python is not recognized, install Python 3 and reopen terminal.
- If output files do not appear, check the terminal for error messages from each phase.
