"""Unit regressions never call the user's model; real model checks are separate."""
import pytest


@pytest.fixture(autouse=True)
def isolate_research_generation(monkeypatch):
    monkeypatch.setenv("SCHOLARSCOPE_DISABLE_AI", "1")
