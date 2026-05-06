from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.usefixtures("streamlit_server")
BASE_URL = os.environ.get("STREAMLIT_BASE_URL", "http://127.0.0.1:8501")


def _open_app(page):
    page.goto(BASE_URL, wait_until="networkidle")
    return page


def test_tab1_loads(page):
    _open_app(page)
    assert page.get_by_role("tab", name="Stability Explorer").count() >= 1


def test_tab1_renders_charts(page):
    _open_app(page)
    page.get_by_role("tab", name="Stability Explorer").click()
    page.locator("div[data-testid='stPlotlyChart']").first.wait_for(state="visible")
    assert page.locator("div[data-testid='stPlotlyChart']").count() >= 2


def test_tab2_shows_kg_sensitivity(page):
    _open_app(page)
    page.get_by_role("tab", name="KN → GZ Transform").click()
    page.get_by_role("heading", name="KG Sensitivity").wait_for(state="visible")
    assert page.locator("div[data-testid='stPlotlyChart']").count() >= 3


def test_tab3_benchmark_section(page):
    _open_app(page)
    page.get_by_role("tab", name="Benchmark Validation").click()
    page.get_by_role("heading", name="Benchmark Validation").wait_for(state="visible")
    if page.get_by_text("No benchmark summary found").count() > 0:
        assert page.get_by_text("No benchmark summary found").is_visible()
    else:
        assert page.get_by_text("Select hull sample").is_visible()
        assert page.locator("div[data-testid='stDataFrame']").count() >= 1


def test_tab4_optimizer_form(page):
    _open_app(page)
    page.get_by_role("tab", name="Offset Optimizer").click()
    page.get_by_role("button", name="Run Optimization").wait_for(state="visible")
    assert page.get_by_role("button", name="Run Optimization").is_visible()
    
    # Verify constraint form elements are present
    assert page.get_by_text("Target heel angle").count() > 0
    assert page.get_by_text("Max half-breadth perturbation").count() > 0
    assert page.get_by_text("Minimum GZ Constraints").count() > 0
    assert page.get_by_text("Min area under GZ").count() > 0
