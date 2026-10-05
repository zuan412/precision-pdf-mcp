"""
Precision PDF MCP Server Package.
Pixel-perfect PDF form and assignment filling for AI coding agents.
"""

from .engine import HPEEngine
from .server import server, main

__version__ = "0.1.0"
__all__ = ["HPEEngine", "server", "main", "__version__"]
