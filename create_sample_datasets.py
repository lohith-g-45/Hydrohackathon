import numpy as np
import pandas as pd
from pathlib import Path

# Create 5 sample ShipD hull design vectors (45 parameters each)
np.random.seed(42)
n_hulls = 5
n_params = 45

# Generate base hull designs
designs = np.random.randn(n_hulls, n_params) * 20 + 100

# Ensure principal dimensions are reasonable
for i in range(n_hulls):
    designs[i, 0] = np.random.uniform(100, 250)   # LOA: 100-250m
    designs[i, 1] = np.random.uniform(15, 45)     # Beam: 15-45m
    designs[i, 6] = np.random.uniform(10, 35)     # Depth: 10-35m

# Save to CSV
output_file = Path("tests/fixtures/sample_ship_designs.csv")
output_file.parent.mkdir(parents=True, exist_ok=True)
np.savetxt(output_file, designs, delimiter=",")

print(f"Created {output_file} with {n_hulls} hull designs ({n_params} parameters each)")
print(f"File shape: {designs.shape}")
