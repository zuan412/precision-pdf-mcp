"""
Precision PDF MCP Server.
Exposes Virtual Excel Grid inspection, Set-of-Marks slot grounding,
and 100% baseline-snapped answer injection tools to AI coding agents via MCP.
"""

import sys
import os
import json
from typing import Dict, List, Any, Optional

from mcp.server.mcpserver import MCPServer
from .engine import HPEEngine
from .utils import logger

server = MCPServer("precision-pdf")


@server.tool()
def hpe_inspect_virtual_grid(pdf_path: str, page_number: int, dpi: int = 150) -> str:
    """
    Generate a temporary Virtual Excel Grid Inspector Image with Set-of-Marks (SoM) slot badges.
    This image overlays:
      - Top Excel column letters (A, B, C...)
      - Left Excel row numbers (1, 2, 3...)
      - Labeled slot pill badges: [S01], [S02], [S03]... on every detected blank, underline, or box.
    Returns JSON containing:
      - inspector_image_path: Path to the image (view it via view_file to visually inspect the layout!)
      - slots: Catalog of detected slots with tag, type, baseline, and Excel grid address (e.g. Col K, Row 9).
    NOTE: This is strictly a virtual guide for the agent's eyes; it does NOT alter the PDF!
    """
    try:
        engine = HPEEngine(pdf_path)
        img_path, catalog = engine.generate_virtual_grid_inspector(page_number=page_number, dpi=dpi)

        slots_summary = {}
        for tag, s in catalog.items():
            slots_summary[tag] = {
                "type": s["type"],
                "source": s.get("source", "geometry"),
                "grid_address": s.get("grid_address", ""),
                "baseline_y": round(s.get("baseline_y", 0), 1),
                "width": round(s.get("width", 0), 1),
                "height": round(s.get("height", 0), 1),
                "multiline_next": s.get("multiline_next", False)
            }

        return json.dumps({
            "status": "success",
            "page_number": page_number,
            "inspector_image_path": img_path,
            "total_slots": len(catalog),
            "slots": slots_summary
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in hpe_inspect_virtual_grid: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@server.tool()
def hpe_fill_slots(
    pdf_path: str,
    page_number: int,
    slot_answers_json: str,
    output_path: Optional[str] = None
) -> str:
    """
    Inject answers into the PDF using Slot IDs (e.g. {"S01": "answer", "S02": "B"}).
    Guarantees:
      - 100% baseline snap on printed lines (zero floating text).
      - 100% center alignment in boxes (zero off-center boxes).
      - Automatic multi-line wrapping across consecutive lines for long answers.
      - Automatic font scaling to avoid text collision or overflow.
      - 100% CLEAN OUTPUT: Final PDF contains ONLY answers (zero grid lines, zero badges).
    Args:
      pdf_path: Path to target PDF.
      page_number: 1-based page number.
      slot_answers_json: JSON string mapping slot tags to answers:
                         e.g. '{"S01": "went", "S02": ["line 1 text", "line 2 text"], "circle_option": "A"}'
      output_path: Optional output path. If omitted, overwrites safely via atomic replace.
    Returns status JSON with saved path.
    """
    try:
        engine = HPEEngine(pdf_path)
        answers = json.loads(slot_answers_json)
        if not isinstance(answers, dict):
            return json.dumps({"error": "slot_answers_json must be a JSON object (dict)"}, ensure_ascii=False)
        saved = engine.fill_by_slot_ids(page_number=page_number, slot_answers=answers, output_path=output_path)
        return json.dumps({
            "status": "success",
            "saved_path": saved,
            "slots_filled_count": len(answers)
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in hpe_fill_slots: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@server.tool()
def hpe_render_clean_verify(pdf_path: str, page_number: int, dpi: int = 150) -> str:
    """
    Render the final, clean PDF page (with answers, WITHOUT any grid or badges)
    to a high-resolution PNG image for visual QA before submission.
    """
    try:
        engine = HPEEngine(pdf_path)
        img_path = engine.render_clean_verification_image(page_number=page_number, dpi=dpi)
        return json.dumps({
            "status": "success",
            "clean_image_path": img_path,
            "dpi": dpi
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in hpe_render_clean_verify: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================

@server.tool()
def hpe_inspect_geometry(pdf_path: str, page_number: int) -> str:
    """
    Inspect the geometric layout and detected answer blanks of a PDF page.
    Backward-compatible alias for hpe_inspect_virtual_grid.

    Args:
      pdf_path: Absolute or relative filesystem path to the target PDF document.
      page_number: 1-based index of the PDF page to analyze (e.g. 1 for the first page).

    Returns:
      JSON string containing the inspector image path and the catalog of detected blanks.
    """
    return hpe_inspect_virtual_grid(pdf_path=pdf_path, page_number=page_number)


@server.tool()
def hpe_snap_fill(
    pdf_path: str,
    page_number: int,
    operations_json: str,
    output_path: Optional[str] = None
) -> str:
    """
    Execute baseline-snapped text injection and option marking operations on a PDF page.
    Backward-compatible alias for hpe_fill_slots.

    Args:
      pdf_path: Absolute or relative filesystem path to the PDF document to modify.
      page_number: 1-based index of the target page (e.g. 1).
      operations_json: JSON string with operations or slot-to-answer mappings (e.g. '{"S01": "answer"}').
      output_path: Optional destination path for the modified PDF. If omitted, safely overwrites the original.

    Returns:
      JSON string with operation status, output file path, and filled count.
    """
    try:
        data = json.loads(operations_json)
        if isinstance(data, dict):
            return hpe_fill_slots(pdf_path, page_number, operations_json, output_path)
        elif isinstance(data, list):
            answers = {}
            for op in data:
                op_type = op.get("type", "")
                if op_type == "text_on_line":
                    answers[f"op_line_{op.get('y', 0)}"] = op.get("text", "")
                elif op_type == "circle_word":
                    answers["circle_option"] = op.get("word", "")
                elif op_type == "underline_word":
                    answers["underline_option"] = op.get("word", "")
            return hpe_fill_slots(pdf_path, page_number, json.dumps(answers), output_path)
        return json.dumps({"error": "Invalid operations_json format"}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in hpe_snap_fill: {e}", exc_info=True)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@server.tool()
def hpe_render_verify(pdf_path: str, page_number: int, dpi: int = 150) -> str:
    """
    Render a clean, high-resolution raster image of the filled PDF page for visual verification.
    Backward-compatible alias for hpe_render_clean_verify.

    Args:
      pdf_path: Absolute or relative path to the completed PDF file.
      page_number: 1-based index of the page to render (e.g. 1).
      dpi: Rasterization resolution in dots per inch (default 150, recommended 150-300).

    Returns:
      JSON string containing the rendered image path and verification status.
    """
    return hpe_render_clean_verify(pdf_path=pdf_path, page_number=page_number, dpi=dpi)



def main():
    """Main CLI entrypoint."""
    logger.info("Starting Precision PDF MCP Server on stdio...")
    server.run("stdio")


if __name__ == "__main__":
    main()
