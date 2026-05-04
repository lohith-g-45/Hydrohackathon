#!/usr/bin/env python3
from ship_excel_extractor import extract_ship_data
import pandas as pd

# Try extracting with debug
extracted = extract_ship_data('HYDRO HACKATHON DATA.xlsx')

print("EXTRACTED VALUES:")
print(f"  Depth: {extracted.get('depth')} m")
print(f"  Draft: {extracted.get('draft')} m")
print(f"  KG: {extracted.get('KG')} m")

# Also check directly from Excel
print("\nDIRECT EXCEL CHECK:")
wb = pd.ExcelFile('HYDRO HACKATHON DATA.xlsx')
df = wb.parse('Main Particulars')
print("\nMain Particulars DataFrame:")
print(df[['Unnamed: 1', 'Unnamed: 2']].head(10))
