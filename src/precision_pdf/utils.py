"""
Utility functions for Precision PDF MCP Server.
Provides cross-platform font resolution, safe stderr logging, and warning filters.
"""

import os
import sys
import logging
import warnings
from PIL import ImageFont

# Ensure all warnings are directed to stderr to protect stdio JSON-RPC transport
warnings.filterwarnings("default")

logger = logging.getLogger("precision_pdf")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def resolve_system_font(size: int = 11, bold: bool = False) -> ImageFont.ImageFont:
    """
    Resolves an appropriate system font across Windows, macOS, and Linux.
    Falls back gracefully to PIL's built-in default font if no TTF is found.
    """
    candidate_fonts = []

    if sys.platform == "win32":
        candidate_fonts = [
            "arialbd.ttf" if bold else "arial.ttf",
            "segoeuib.ttf" if bold else "segoeui.ttf",
            "calibrib.ttf" if bold else "calibri.ttf",
        ]
    elif sys.platform == "darwin":
        candidate_fonts = [
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    else: # Linux / Unix
        candidate_fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]

    for font_name in candidate_fonts:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue

    # Final safe fallback
    return ImageFont.load_default()
