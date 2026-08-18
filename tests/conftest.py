"""Shared test configuration.

Forces the LLM layer into offline *mock* mode for the whole suite so tests are
deterministic and need no API key, and exposes the examples directory.
"""
import os
import pathlib

os.environ["POLY_LLM_MODE"] = "mock"

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
