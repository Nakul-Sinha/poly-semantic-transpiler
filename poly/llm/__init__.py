"""The bounded, validated LLM layer.

  * holes are created during lowering (see poly/lower.py) with a compiler-derived
    contract (poly/ir.py: HoleContract);
  * client.HoleFiller fills each hole (cache -> offline mock -> live LLM) and runs
    every candidate through gates A/B/C before accepting it;
  * gates.py implements the three validation gates.

See docs/LLM-LAYER.md.
"""
from __future__ import annotations

from .client import HoleFiller

__all__ = ["HoleFiller"]
