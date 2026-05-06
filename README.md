# HydroHackathon — Ship Stability Analysis & Offset Optimizer

An interactive ship stability toolkit built for HydroHackathon. Computes hydrostatics, GZ curves, and runs constrained offset optimization to meet stability criteria.

---

## Quick Start (Streamlit UI — recommended)

### 1. Clone the repository

```bash
git clone https://github.com/raviasha/HYDROHACKATHON.git
cd HYDROHACKATHON
```

### 2. Create and activate a virtual environment

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Launch the Streamlit app

```bash
streamlit run interactive_ui.py
```

The app opens automatically in your browser at **http://localhost:8501**.

If it does not open automatically, navigate to that URL manually.

---

## What's in the UI

| Tab | Description |
|-----|-------------|
| **Stability Explorer** | Upload offsets CSV, set draft / KG / density, run full hydrostatics pipeline |
| **KN → GZ Transform** | Convert KN table to GZ curve for a given KG |
| **Benchmark Validation** | Run and visualise benchmark test results |
| **Volume Validation** | Verify displaced volume conservation across waterlines |
| **Offset Optimizer** | Constrained optimisation — maximise GZ while satisfying minimum GZ and area-under-GZ stability criteria |

---

## Input file format

Upload a CSV with half-breadth offsets (metres). Rows = waterlines, Columns = stations.

Example (`offsetdata.csv` included in repo):

```
wl\stn, 0, 1, 2, ...
0.0,    0, 0, 0, ...
0.5,    1, 1, 1, ...
...
```

---

## Command-line pipeline (alternative)

```bash
python main.py "HYDRO HACKATHON DATA.xlsx"
# or with a custom output directory:
python main.py "HYDRO HACKATHON DATA.xlsx" --output-dir results
```

Core outputs: `results.csv`, `gz_curve.png`, `hull_3d.html`, `insights.txt`

Open `hull_3d.html` in a browser to view the 3D hull visualisation.

---

## Requirements

- Python 3.9+ (Python 3.11 recommended)
- Dependencies listed in `requirements.txt` (numpy, scipy, streamlit, plotly, pandas, …)

---

## Common issues

| Issue | Fix |
|-------|-----|
| `streamlit: command not found` | Run `pip install streamlit` inside your activated venv |
| Port 8501 already in use | Run `streamlit run interactive_ui.py --server.port 8502` |
| `ModuleNotFoundError` | Ensure venv is activated and `pip install -r requirements.txt` completed without errors |
| Excel file not found (CLI mode) | Make sure the `.xlsx` file is in the same folder as `main.py` |
