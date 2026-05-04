#!/usr/bin/env python3
from ship_excel_extractor import extract_ship_data

extracted = extract_ship_data('HYDRO HACKATHON DATA.xlsx')
print(f'Extracted Depth: {extracted.get("depth", "NOT FOUND")} m')
print(f'Extracted Draft: {extracted.get("draft", "NOT FOUND")} m')
print(f'Extracted KG: {extracted.get("KG", "NOT FOUND")} m')
