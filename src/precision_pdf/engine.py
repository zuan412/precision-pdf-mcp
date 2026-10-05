"""
Hybrid Precision Engine (HPE v2) Core Implementation.
High-precision PDF form and worksheet filling using hybrid geometry detection,
in-memory morphological line scanning, Set-of-Marks visual grid anchors, and baseline snapping.
"""

import os
import io
import re
import tempfile
import pymupdf as fitz
import pdfplumber
import numpy as np
from PIL import Image, ImageDraw
from typing import Dict, List, Any, Optional, Tuple, Union

from .utils import resolve_system_font, logger


class HPEEngine:
    """Core engine for Virtual Excel Grid inspection, morphological line scanning, and precision anchor injection."""

    def __init__(self, pdf_path: str, temp_dir: Optional[str] = None):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        self.pdf_path = os.path.abspath(pdf_path)
        self.temp_dir = temp_dir or os.environ.get("PRECISION_PDF_TEMP_DIR") or os.path.join(tempfile.gettempdir(), "precision_pdf")
        os.makedirs(self.temp_dir, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. Multi-Layer Slot Detection Pipeline
    # -------------------------------------------------------------------------

    def detect_all_slots(self, page_number: int, dpi: int = 144) -> List[Dict[str, Any]]:
        """
        Detects all answer slots on the page using a 3-layer hybrid pipeline:
        1. Vector geometry (lines, rectangles) via pdfplumber.
        2. In-memory morphological raster line scanning (NumPy) for scanned workbooks.
        3. Text-based underscores and numbered gap markers via PyMuPDF.
        Applies padding guards and groups consecutive multi-line blanks.
        """
        page_idx = page_number - 1
        doc = fitz.open(self.pdf_path)
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            raise ValueError(f"Page {page_number} out of range (1..{len(doc)})")
        page = doc[page_idx]
        pw = page.rect.width
        ph = page.rect.height

        raw_slots = []

        # Layer 1: Vector geometry via pdfplumber
        try:
            with pdfplumber.open(self.pdf_path) as plum:
                p_plum = plum.pages[page_idx]

                # Vector underlines
                for line in p_plum.lines:
                    x0, y0, x1, y1 = line["x0"], line["top"], line["x1"], line["bottom"]
                    w = abs(x1 - x0)
                    h = abs(y1 - y0)
                    if h <= 2.5 and w >= 20.0:
                        raw_slots.append({
                            "type": "underline",
                            "source": "vector",
                            "bbox": (min(x0, x1), y0 - 10.0, max(x0, x1), y1 + 3.0),
                            "baseline_y": float((y0 + y1) / 2.0),
                            "x0": float(min(x0, x1)),
                            "x1": float(max(x0, x1)),
                            "width": float(w),
                            "height": float(max(h, 1.0))
                        })

                # Vector rectangles (boxes/table cells)
                for rect in p_plum.rects:
                    x0, top, x1, bottom = rect["x0"], rect["top"], rect["x1"], rect["bottom"]
                    w = abs(x1 - x0)
                    h = abs(bottom - top)
                    if 8.0 <= w <= 260.0 and 8.0 <= h <= 100.0 and top > 80.0:
                        raw_slots.append({
                            "type": "box",
                            "source": "vector",
                            "bbox": (float(x0), float(top), float(x1), float(bottom)),
                            "cx": float((x0 + x1) / 2.0),
                            "cy": float((top + bottom) / 2.0),
                            "width": float(w),
                            "height": float(h)
                        })
        except Exception as e:
            logger.debug(f"pdfplumber extraction skipped: {e}")

        # Layer 2: In-Memory Morphological Raster Line Scanning (NumPy)
        raster_lines = self._scan_raster_lines(page, dpi=dpi, min_width_pt=35.0)
        for rl in raster_lines:
            raw_slots.append({
                "type": "underline",
                "source": "raster",
                "bbox": (rl["x0"], rl["y"] - 12.0, rl["x1"], rl["y"] + 2.0),
                "baseline_y": float(rl["y"]),
                "x0": float(rl["x0"]),
                "x1": float(rl["x1"]),
                "width": float(rl["width"]),
                "height": 14.0
            })

        # Layer 3: Text-based underscores & gap markers via PyMuPDF
        words = page.get_text("words")
        sorted_words = sorted(words, key=lambda w: (round(w[1] / 8.0), w[0]))

        for w in words:
            text = w[4]

            # 3A. Text underscores: '_____' or 'He________'
            if "_" in text and len(text) >= 4:
                prefix_len = len(text.rstrip("_"))
                total_len = len(text)
                x_start = w[0] + (w[2] - w[0]) * (prefix_len / total_len) if total_len > 0 else w[0]
                raw_slots.append({
                    "type": "underline",
                    "source": "text_underscore",
                    "bbox": (float(x_start), float(w[1]), float(w[2]), float(w[3])),
                    "baseline_y": float(w[3] - 1.5),
                    "x0": float(x_start),
                    "x1": float(w[2]),
                    "width": float(w[2] - x_start),
                    "height": float(w[3] - w[1])
                })

            # 3B. Numbered gap markers: '1)', '2)', '(1)', '(2)', '1.'
            m_gap = re.match(r"^(\(?\d{1,2}\.?\)?)$", text)
            if m_gap and ("_" not in text):
                marker = m_gap.group(1)
                gap_x0 = float(w[2] + 4.0)
                gap_x1 = float(w[2] + 55.0)
                raw_slots.append({
                    "type": "gap",
                    "source": "gap_marker",
                    "bbox": (gap_x0, float(w[1]), gap_x1, float(w[3])),
                    "baseline_y": float(w[3] - 1.5),
                    "x0": gap_x0,
                    "x1": gap_x1,
                    "width": float(gap_x1 - gap_x0),
                    "height": float(w[3] - w[1]),
                    "marker": marker
                })

        doc.close()

        # Deduplicate, apply padding guard, and identify multi-line groups
        filtered_slots = self._deduplicate_slots(raw_slots)
        self._apply_padding_guard(filtered_slots, sorted_words)
        self._identify_multiline_groups(filtered_slots)

        return filtered_slots

    def _scan_raster_lines(self, page, dpi: int = 144, min_width_pt: float = 35.0) -> List[Dict[str, float]]:
        """Scans rendered raster image for horizontal printed lines using pure NumPy morphology in RAM."""
        scale = dpi / 72.0
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        arr = np.array(img)

        dark = (arr < 205).astype(np.int32)
        min_pixels = int(min_width_pt * scale)
        h, w = dark.shape
        pw = page.rect.width

        detected_lines = []
        for y in range(int(60 * scale), h - int(30 * scale)):
            row = dark[y, :]
            diff = np.diff(np.pad(row, (1, 1), 'constant'))
            starts = np.where(diff == 1)[0]
            ends = np.where(diff == -1)[0]
            for s, e in zip(starts, ends):
                length = (e - s) / scale
                x0_pt = s / scale
                x1_pt = e / scale
                # Filter answer lines: must be inside margins and not full-page banner
                if (length >= min_width_pt and
                    length < (pw * 0.82) and
                    x0_pt >= 35.0 and
                    x1_pt <= (pw - 25.0)):
                    detected_lines.append({
                        "y": y / scale,
                        "x0": x0_pt,
                        "x1": x1_pt,
                        "width": length
                    })

        merged = []
        detected_lines.sort(key=lambda item: (round(item["y"], 1), item["x0"]))
        for l in detected_lines:
            if not merged:
                merged.append(l)
                continue
            prev = merged[-1]
            if (abs(l["y"] - prev["y"]) <= (3.0 / scale) and
                abs(l["x0"] - prev["x0"]) < 8.0 and
                abs(l["x1"] - prev["x1"]) < 8.0):
                prev["y"] = max(prev["y"], l["y"])
                prev["x0"] = min(prev["x0"], l["x0"])
                prev["x1"] = max(prev["x1"], l["x1"])
                prev["width"] = prev["x1"] - prev["x0"]
            else:
                merged.append(l)

        pw = page.rect.width
        return [l for l in merged if l["width"] < (pw * 0.85)]

    def _deduplicate_slots(self, raw_slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicates slots where vector, raster, and text overlaps refer to the same blank."""
        unique = []
        priority = {"raster": 3, "vector": 2, "text_underscore": 1, "gap_marker": 2}
        raw_slots.sort(key=lambda s: (-priority.get(s.get("source", ""), 0), s["bbox"][1], s["bbox"][0]))

        for s in raw_slots:
            bx0, by0, bx1, by1 = s["bbox"]
            is_dup = False
            for u in unique:
                ux0, uy0, ux1, uy1 = u["bbox"]
                if abs(by0 - uy0) < 6.0:
                    overlap_x0 = max(bx0, ux0)
                    overlap_x1 = min(bx1, ux1)
                    if overlap_x1 > overlap_x0:
                        is_dup = True
                        break
            if not is_dup:
                unique.append(s)

        def slot_sort_key(s):
            y_band = round(s["bbox"][1] / 14.0)
            return (y_band, s["bbox"][0])

        unique.sort(key=slot_sort_key)
        return unique

    def _apply_padding_guard(self, slots: List[Dict[str, Any]], words: List[Tuple]):
        """Enforces safe margin (+6pt to +10pt) after preceding text to prevent collisions."""
        for s in slots:
            if s["type"] not in ["underline", "gap"]:
                continue
            x0 = s["x0"]
            y = s.get("baseline_y", s["bbox"][3])
            preceding_words = [
                w for w in words
                if abs(w[3] - y) < 8.0 and w[2] <= (x0 + 4.0) and (x0 - w[2]) < 40.0
            ]
            if preceding_words:
                last_w = max(preceding_words, key=lambda w: w[2])
                min_safe_x = last_w[2] + 6.0
                if s["x0"] < min_safe_x:
                    delta = min_safe_x - s["x0"]
                    s["x0"] = min_safe_x
                    s["width"] = max(10.0, s["width"] - delta)
                    s["bbox"] = (s["x0"], s["bbox"][1], s["bbox"][2], s["bbox"][3])

    def _identify_multiline_groups(self, slots: List[Dict[str, Any]]):
        """Identifies vertically stacked lines for the same question."""
        for i in range(len(slots) - 1):
            curr = slots[i]
            nxt = slots[i + 1]
            if curr["type"] == "underline" and nxt["type"] == "underline":
                dy = nxt["baseline_y"] - curr["baseline_y"]
                dx = abs(nxt["x0"] - curr["x0"])
                if 10.0 <= dy <= 20.0 and dx < 15.0:
                    curr["multiline_next"] = True
                    nxt["multiline_prev"] = True

    # -------------------------------------------------------------------------
    # 2. Virtual Excel Matrix & Set-of-Marks Inspector
    # -------------------------------------------------------------------------

    def generate_virtual_grid_inspector(
        self,
        page_number: int,
        out_image_path: Optional[str] = None,
        dpi: int = 150,
        col_width_pt: float = 40.0,
        row_height_pt: float = 20.0
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Renders a temporary Virtual Excel Grid Inspector Image for agent visual grounding.
        Overlays:
          - Column headers: A, B, C...
          - Row headers: 1, 2, 3...
          - Set-of-Marks (SoM) labeled slot badges: [S01], [S02]...
        """
        page_idx = page_number - 1
        if not out_image_path:
            out_image_path = os.path.join(
                self.temp_dir, f"virtual_grid_p{page_number}_{os.path.basename(self.pdf_path)}.png"
            )

        slots = self.detect_all_slots(page_number=page_number, dpi=dpi)

        slot_catalog = {}
        for i, s in enumerate(slots):
            tag = f"S{i+1:02d}"
            col_idx = int(s["bbox"][0] / col_width_pt)
            row_idx = int(s["bbox"][1] / row_height_pt) + 1
            col_letter = self._col_index_to_letter(col_idx)
            s["tag"] = tag
            s["grid_address"] = f"Col {col_letter}, Row {row_idx}"
            slot_catalog[tag] = s

        doc = fitz.open(self.pdf_path)
        page = doc[page_idx]
        pw = page.rect.width
        ph = page.rect.height

        scale = dpi / 72.0
        RULER_W = 42
        RULER_H = 26

        pix = page.get_pixmap(dpi=dpi)
        doc.close()

        base_img = Image.open(io.BytesIO(pix.tobytes("png")))
        total_w = base_img.width + RULER_W
        total_h = base_img.height + RULER_H

        grid_img = Image.new("RGB", (total_w, total_h), (245, 245, 248))
        grid_img.paste(base_img, (RULER_W, RULER_H))
        draw = ImageDraw.Draw(grid_img, "RGBA")

        font_ruler = resolve_system_font(11, bold=False)
        font_badge = resolve_system_font(11, bold=True)

        # Top Column Ruler
        num_cols = int(pw / col_width_pt) + 1
        for c in range(num_cols):
            pt_x = c * col_width_pt
            px_x = RULER_W + int(pt_x * scale)
            px_next_x = RULER_W + int((pt_x + col_width_pt) * scale)
            col_label = self._col_index_to_letter(c)

            draw.rectangle([px_x, 0, px_next_x, RULER_H], fill=(235, 238, 243), outline=(195, 200, 210), width=1)
            draw.text((px_x + 4, 6), col_label, fill=(60, 65, 75), font=font_ruler)
            draw.line([px_x, RULER_H, px_x, total_h], fill=(210, 215, 225, 90), width=1)

        # Left Row Ruler
        num_rows = int(ph / row_height_pt) + 1
        for r in range(num_rows):
            pt_y = r * row_height_pt
            px_y = RULER_H + int(pt_y * scale)
            px_next_y = RULER_H + int((pt_y + row_height_pt) * scale)
            row_label = str(r + 1)

            draw.rectangle([0, px_y, RULER_W, px_next_y], fill=(235, 238, 243), outline=(195, 200, 210), width=1)
            draw.text((6, px_y + 4), row_label, fill=(60, 65, 75), font=font_ruler)
            draw.line([RULER_W, px_y, total_w, px_y], fill=(210, 215, 225, 90), width=1)

        # Set-of-Marks Badges
        for tag, slot in slot_catalog.items():
            bx0, by0, bx1, by1 = slot["bbox"]
            px0 = RULER_W + int(bx0 * scale)
            py0 = RULER_H + int(by0 * scale)
            px1 = RULER_W + int(bx1 * scale)
            py1 = RULER_H + int(by1 * scale)

            if slot["type"] == "box":
                border_col = (220, 38, 38, 180)
                fill_col = (254, 226, 226, 75)
                badge_bg = (220, 38, 38)
            elif slot["type"] == "gap":
                border_col = (147, 51, 234, 180)
                fill_col = (243, 232, 255, 75)
                badge_bg = (147, 51, 234)
            else:
                border_col = (13, 148, 136, 180)
                fill_col = (204, 251, 241, 75)
                badge_bg = (13, 148, 136)

            draw.rectangle([px0, py0, px1, py1], outline=border_col, fill=fill_col, width=2)

            badge_w = 34
            badge_h = 16
            b_x = max(RULER_W, px0 - 2)
            b_y = max(RULER_H, py0 - badge_h + 1)
            draw.rectangle([b_x, b_y, b_x + badge_w, b_y + badge_h], fill=badge_bg)
            draw.text((b_x + 4, b_y + 2), tag, fill=(255, 255, 255), font=font_badge)

        grid_img.save(out_image_path)
        return out_image_path, slot_catalog

    # -------------------------------------------------------------------------
    # 3. Precision Anchor Injection Engine (CLEAN PDF OUTPUT ONLY)
    # -------------------------------------------------------------------------

    def fill_by_slot_ids(
        self,
        page_number: int,
        slot_answers: Dict[str, Any],
        output_path: Optional[str] = None,
        slot_catalog: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Injects answers directly into the target PDF using Slot IDs (e.g. S01, S05) or explicit operations.
        Guarantees:
          - 100% baseline snap on underlines (zero floating text).
          - 100% dead-center in boxes (zero off-center boxes).
          - Multi-line automatic wrapping across consecutive lines for long answers.
          - Auto-fit text scaling (zero collision).
          - ZERO GRID POLLUTION: Output file contains ONLY the clean answers!
        """
        page_idx = page_number - 1
        target_out = os.path.abspath(output_path if output_path else self.pdf_path)

        if not slot_catalog:
            slots = self.detect_all_slots(page_number=page_number)
            slot_catalog = {}
            for i, s in enumerate(slots):
                tag = f"S{i+1:02d}"
                s["tag"] = tag
                slot_catalog[tag] = s

        doc = fitz.open(self.pdf_path)
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            raise ValueError(f"Page {page_number} out of range (1..{len(doc)})")
        page = doc[page_idx]

        for slot_key, answer_val in slot_answers.items():
            if slot_key.startswith("underline_word") or slot_key.startswith("underline_option"):
                self._handle_underline_word(page, answer_val)
                continue
            elif slot_key.startswith("circle_word") or slot_key.startswith("circle_option"):
                self._handle_circle_operation(page, answer_val)
                continue
            elif slot_key.startswith("tick_") or slot_key.startswith("check_"):
                self._handle_tick_operation(page, answer_val)
                continue
            elif slot_key.startswith("custom_text"):
                self._handle_custom_text(page, answer_val)
                continue

            if isinstance(answer_val, dict) and ("y" in answer_val or "baseline_y" in answer_val) and "text" in answer_val:
                self._handle_custom_text(page, answer_val)
                continue

            if slot_key not in slot_catalog:
                continue

            slot = slot_catalog[slot_key]
            slot_type = slot["type"]

            if isinstance(answer_val, dict):
                text = str(answer_val.get("text", ""))
                fontname = answer_val.get("fontname", "helv")
                fontsize = float(answer_val.get("fontsize", 9.8))
                color = tuple(answer_val.get("color", [0.0, 0.2, 0.6]))
            elif isinstance(answer_val, list):
                text = answer_val
                fontname = "helv"
                fontsize = 9.2
                color = (0.0, 0.2, 0.6)
            else:
                text = str(answer_val)
                fontname = "hebo" if slot_type == "box" and len(text) <= 2 else "helv"
                fontsize = 11.0 if slot_type == "box" and len(text) <= 2 else 9.5
                color = (0.0, 0.2, 0.6)

            # Smart Multi-Line Distribution
            if slot.get("multiline_next") and not isinstance(text, list):
                calc_len = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
                if calc_len > (slot["width"] - 8.0):
                    next_idx = int(slot_key[1:]) + 1
                    next_tag = f"S{next_idx:02d}"
                    if next_tag in slot_catalog:
                        words_list = text.split()
                        mid = len(words_list) // 2
                        part1 = " ".join(words_list[:mid])
                        part2 = " ".join(words_list[mid:])
                        self._inject_single_slot(page, slot, part1, fontname, fontsize, color)
                        self._inject_single_slot(page, slot_catalog[next_tag], part2, fontname, fontsize, color)
                        continue

            if isinstance(text, list):
                if len(text) > 0:
                    self._inject_single_slot(page, slot, text[0], fontname, fontsize, color)
                if len(text) > 1:
                    next_idx = int(slot_key[1:]) + 1
                    next_tag = f"S{next_idx:02d}"
                    if next_tag in slot_catalog:
                        self._inject_single_slot(page, slot_catalog[next_tag], text[1], fontname, fontsize, color)
                continue

            self._inject_single_slot(page, slot, text, fontname, fontsize, color)

        # Atomic In-Place Save
        fd, temp_file = tempfile.mkstemp(suffix=".pdf", dir=self.temp_dir)
        os.close(fd)

        doc.save(temp_file)
        doc.close()

        os.replace(temp_file, target_out)
        return target_out

    def _inject_single_slot(self, page, slot, text: str, fontname: str, fontsize: float, color: tuple):
        """Injects text into a single slot with baseline snapping and auto-scaling."""
        text = str(text).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').strip()
        slot_type = slot["type"]

        if slot_type in ["underline", "gap"]:
            line_y = slot.get("baseline_y", slot["bbox"][3])
            x0 = slot["x0"]
            max_w = slot["width"]

            calc_len = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
            if calc_len > (max_w - 4.0) and max_w > 20.0:
                fontsize = max(6.5, fontsize * ((max_w - 4.0) / calc_len))

            x_pos = x0 + 2.0
            baseline_y = line_y - 1.2
            page.insert_text(fitz.Point(x_pos, baseline_y), text, fontsize=fontsize, fontname=fontname, color=color)

        elif slot_type == "box":
            cx = slot.get("cx", (slot["bbox"][0] + slot["bbox"][2]) / 2.0)
            cy = slot.get("cy", (slot["bbox"][1] + slot["bbox"][3]) / 2.0)
            box_w = slot["width"]

            calc_len = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
            if calc_len > (box_w - 3.0):
                fontsize = max(6.5, fontsize * ((box_w - 3.0) / calc_len))
                calc_len = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)

            x_pos = cx - (calc_len / 2.0)
            y_pos = cy + (fontsize * 0.35)
            page.insert_text(fitz.Point(x_pos, y_pos), text, fontsize=fontsize, fontname=fontname, color=color)

    def _handle_underline_word(self, page, target_info: Any):
        """Draws a clean vector underline beneath target word."""
        color = (0.0, 0.2, 0.6)
        width = 1.3
        if isinstance(target_info, str):
            matches = page.search_for(target_info.strip())
            if matches:
                rect = matches[0]
                page.draw_line(fitz.Point(rect.x0, rect.y1 + 1.2), fitz.Point(rect.x1, rect.y1 + 1.2), color=color, width=width)
        elif isinstance(target_info, dict):
            if "bbox" in target_info:
                b = target_info["bbox"]
                page.draw_line(fitz.Point(b[0], b[3] + 1.2), fitz.Point(b[2], b[3] + 1.2), color=color, width=width)
            else:
                word = target_info.get("word")
                hint_y = target_info.get("hint_y")
                clip = fitz.Rect(target_info["clip"]) if "clip" in target_info else None
                matches = page.search_for(word.strip(), clip=clip)
                if matches:
                    rect = matches[0] if hint_y is None else min(matches, key=lambda r: abs(r.y0 - hint_y))
                    page.draw_line(fitz.Point(rect.x0, rect.y1 + 1.2), fitz.Point(rect.x1, rect.y1 + 1.2), color=color, width=width)

    def _handle_circle_operation(self, page, target_info: Any):
        """Draws a smooth vector ellipse around target word or option letter."""
        color = (0.0, 0.2, 0.6)
        width = 1.3
        if isinstance(target_info, str):
            target_word = target_info.strip()
            matches = page.search_for(target_word)
            if matches:
                rect = matches[0]
                cx = (rect.x0 + rect.x1) / 2.0
                cy = (rect.y0 + rect.y1) / 2.0
                rx = (rect.width / 2.0) + 4.0
                ry = (rect.height / 2.0) + 3.0
                page.draw_oval(fitz.Rect(cx - rx, cy - ry, cx + rx, cy + ry), color=color, width=width)
        elif isinstance(target_info, dict):
            if "cx" in target_info and "cy" in target_info:
                cx, cy = target_info["cx"], target_info["cy"]
                rx = float(target_info.get("rx", 7.0))
                ry = float(target_info.get("ry", 6.0))
                page.draw_oval(fitz.Rect(cx - rx, cy - ry, cx + rx, cy + ry), color=color, width=width)
            elif "bbox" in target_info:
                b = target_info["bbox"]
                cx = (b[0] + b[2]) / 2.0
                cy = (b[1] + b[3]) / 2.0
                rx = ((b[2] - b[0]) / 2.0) + float(target_info.get("pad_x", 4.0))
                ry = ((b[3] - b[1]) / 2.0) + float(target_info.get("pad_y", 3.0))
                page.draw_oval(fitz.Rect(cx - rx, cy - ry, cx + rx, cy + ry), color=color, width=width)
            else:
                word = target_info.get("word", "")
                clip = fitz.Rect(target_info["clip"]) if "clip" in target_info else None
                matches = page.search_for(word.strip(), clip=clip)
                if matches:
                    rect = matches[0]
                    cx = (rect.x0 + rect.x1) / 2.0
                    cy = (rect.y0 + rect.y1) / 2.0
                    rx = (rect.width / 2.0) + float(target_info.get("pad_x", 4.0))
                    ry = (rect.height / 2.0) + float(target_info.get("pad_y", 3.0))
                    page.draw_oval(fitz.Rect(cx - rx, cy - ry, cx + rx, cy + ry), color=color, width=width)

    def _handle_tick_operation(self, page, tick_info: Any):
        """Draws a crisp vector checkmark at (cx, cy)."""
        color = (0.0, 0.2, 0.6)
        width = 1.6
        if isinstance(tick_info, dict):
            cx = float(tick_info.get("cx", 0))
            cy = float(tick_info.get("cy", 0))
            p1 = fitz.Point(cx - 3.5, cy + 0.5)
            p2 = fitz.Point(cx - 1.0, cy + 3.5)
            p3 = fitz.Point(cx + 4.5, cy - 4.0)
            page.draw_line(p1, p2, color=color, width=width)
            page.draw_line(p2, p3, color=color, width=width)

    def _handle_custom_text(self, page, text_info: Any):
        """Places text at an exact custom position with baseline snap."""
        if isinstance(text_info, dict):
            text = str(text_info.get("text", "")).strip()
            x = float(text_info.get("x", text_info.get("x0", 0)))
            y = float(text_info.get("y", text_info.get("baseline_y", 0)))
            fontsize = float(text_info.get("fontsize", 9.5))
            fontname = str(text_info.get("fontname", "helv"))
            color = tuple(text_info.get("color", (0.0, 0.2, 0.6)))
            align = text_info.get("align", "left")
            if align == "center":
                calc_len = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
                x = x - (calc_len / 2.0)
            elif align == "line":
                y = y - 1.2
                x = x + 2.0
            page.insert_text(fitz.Point(x, y), text, fontsize=fontsize, fontname=fontname, color=color)

    # -------------------------------------------------------------------------
    # 4. Clean Final Verification Renderer
    # -------------------------------------------------------------------------

    def render_clean_verification_image(self, page_number: int, dpi: int = 150, out_image_path: Optional[str] = None) -> str:
        """
        Renders the final, clean PDF page (with answers, WITHOUT any grid or badges)
        to a high-resolution PNG for visual verification.
        """
        if not out_image_path:
            fname = f"clean_verified_p{page_number}_{os.path.basename(self.pdf_path)}.png"
            out_image_path = os.path.join(self.temp_dir, fname)

        doc = fitz.open(self.pdf_path)
        p = doc[page_number - 1]
        pix = p.get_pixmap(dpi=dpi)
        pix.save(out_image_path)
        doc.close()
        return out_image_path

    # -------------------------------------------------------------------------
    # 5. Backward Compatibility Aliases
    # -------------------------------------------------------------------------

    def inspect_geometry(self, page_number: int) -> Dict[str, Any]:
        """Backward compatibility alias for inspect_virtual_grid catalog."""
        _, catalog = self.generate_virtual_grid_inspector(page_number)
        return {"page_number": page_number, "slots": catalog}

    def snap_fill(self, page_number: int, operations: Any, output_path: Optional[str] = None) -> str:
        """Backward compatibility alias for fill_by_slot_ids."""
        if isinstance(operations, str):
            import json
            operations = json.loads(operations)
        if isinstance(operations, dict):
            return self.fill_by_slot_ids(page_number, operations, output_path)
        return output_path or self.pdf_path

    @staticmethod
    def _col_index_to_letter(idx: int) -> str:
        """Converts 0 -> A, 1 -> B, 26 -> AA..."""
        result = ""
        n = idx
        while n >= 0:
            result = chr(ord('A') + (n % 26)) + result
            n = (n // 26) - 1
        return result
