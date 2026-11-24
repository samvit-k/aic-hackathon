"""Shared pytest setup: make the project modules importable from any working directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))