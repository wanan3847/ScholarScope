"""Test SPAR2 engine functionality."""

import pytest
from agent.spar2.engine import SPAR2Engine


def test_spar2_basic():
    """Test basic SPAR2 functionality."""
    engine = SPAR2Engine(max_output=5, judge_threshold=0.2)
    assert engine.max_output == 5
    assert engine.judge_threshold == 0.2
    assert engine.max_judge <= 250
    assert engine.local_top_k >= 100
    print("✓ SPAR2 basic test passed")


if __name__ == "__main__":
    test_spar2_basic()