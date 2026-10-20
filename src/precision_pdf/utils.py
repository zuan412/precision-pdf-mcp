"""
Utility functions for Precision PDF MCP Server.
Provides cross-platform font resolution, safe stderr logging, and warning filters.
"""

import os
import sys
import tempfile
import logging
import warnings
from typing import Optional
from PIL import ImageFont

# Ensure all warnings are directed to stderr to protect stdio JSON-RPC transport
warnings.filterwarnings("default")

logger = logging.getLogger("precision_pdf")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_default_temp_dir(pdf_path: Optional[str] = None, temp_dir: Optional[str] = None) -> str:
    """
    Returns the appropriate temporary directory for intermediate assets.
    Prioritizes explicit temp_dir, PRECISION_PDF_TEMP_DIR environment variable,
    platform-specific scratch paths, or fallback to the PDF's directory.
    Guarantees that on Linux, no 'D:' directory is ever referenced or created.
    """
    if temp_dir:
        return temp_dir
    env_dir = os.environ.get("PRECISION_PDF_TEMP_DIR")
    if env_dir:
        return env_dir

    if sys.platform == "win32":
        for candidate in [r"D:\.agent_temp\scratch", r"C:\.agent_temp\scratch"]:
            if os.path.exists(candidate):
                return candidate
        if pdf_path:
            pdf_drive = os.path.splitdrive(os.path.abspath(pdf_path))[0]
            if pdf_drive:
                candidate = os.path.join(pdf_drive, ".agent_temp", "scratch")
                if os.path.exists(candidate):
                    return candidate
            return os.path.dirname(os.path.abspath(pdf_path))
        return os.path.join(tempfile.gettempdir(), "precision_pdf")
    else:  # Linux / Unix / macOS
        user_scratch = os.path.join(os.path.expanduser("~"), ".agent_temp", "scratch")
        if os.path.exists(user_scratch):
            return user_scratch
        tmp_dir = os.path.join(tempfile.gettempdir(), "precision_pdf")
        try:
            os.makedirs(tmp_dir, exist_ok=True)
            return tmp_dir
        except Exception:
            if pdf_path:
                return os.path.dirname(os.path.abspath(pdf_path))
            return tempfile.gettempdir()


def resolve_unicode_font(bold: bool = False) -> Optional[str]:
    """
    Finds a TrueType/OpenType font file supporting full Unicode (including Vietnamese)
    across Linux, Windows, and macOS.
    Returns the absolute path if found, otherwise None.
    """
    candidate_fonts = []

    if sys.platform == "win32":
        candidate_fonts = [
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
        ]
    elif sys.platform == "darwin":
        candidate_fonts = [
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    else:  # Linux / Unix
        if bold:
            candidate_fonts = [
                "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Bold.ttf",
                "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Bold.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf",
                "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Regular.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
        else:
            candidate_fonts = [
                "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf",
                "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Regular.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]

    for font_path in candidate_fonts:
        if os.path.isfile(font_path):
            return os.path.abspath(font_path)

    # Cross-platform fallback check
    fallback_candidates = [
        "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf",
        "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for font_path in fallback_candidates:
        if os.path.isfile(font_path):
            return os.path.abspath(font_path)

    return None


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
    else:  # Linux / Unix
        candidate_fonts = [
            "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Bold.ttf" if bold else "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf",
            "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Bold.otf" if bold else "/usr/share/fonts/abattis-cantarell-fonts/Cantarell-Regular.otf",
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

