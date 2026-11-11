"""Question answering on CAD assemblies, grounded in deterministic geometric facts."""

from .assistant import Assistant, rule_route
from .facts import AssemblyIndex

__version__ = "0.1.0"
__all__ = ["Assistant", "AssemblyIndex", "rule_route"]
