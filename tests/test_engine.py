"""
Unit tests for Precision PDF MCP Engine and Server.
"""

import os
import sys
import unittest
import tempfile

# Ensure src is on sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import pymupdf as fitz
from precision_pdf.engine import HPEEngine
from precision_pdf.server import hpe_inspect_virtual_grid, hpe_fill_slots, hpe_render_clean_verify


class TestPrecisionPDF(unittest.TestCase):

    def setUp(self):
        # Create a synthetic 1-page PDF for test verification
        self.temp_dir = tempfile.mkdtemp()
        self.test_pdf = os.path.join(self.temp_dir, "sample_test.pdf")

        doc = fitz.open()
        page = doc.new_page(width=595, height=842) # A4

        # Add printed prompt and horizontal line
        page.insert_text(fitz.Point(60, 100), "1. What is your name?", fontsize=12)
        page.draw_line(fitz.Point(60, 140), fitz.Point(300, 140), color=(0, 0, 0), width=1.0)

        # Add a box
        page.insert_text(fitz.Point(60, 180), "Select status:", fontsize=12)
        page.draw_rect(fitz.Rect(60, 200, 120, 230), color=(0, 0, 0), width=1.0)

        doc.save(self.test_pdf)
        doc.close()

        self.engine = HPEEngine(self.test_pdf, temp_dir=self.temp_dir)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_detect_slots(self):
        slots = self.engine.detect_all_slots(page_number=1)
        self.assertGreaterEqual(len(slots), 1, "Should detect at least 1 slot")

    def test_virtual_grid_inspector(self):
        img_path, catalog = self.engine.generate_virtual_grid_inspector(page_number=1)
        self.assertTrue(os.path.exists(img_path))
        self.assertGreaterEqual(len(catalog), 1)

    def test_fill_slots_clean(self):
        img_path, catalog = self.engine.generate_virtual_grid_inspector(page_number=1)
        first_tag = list(catalog.keys())[0]

        out_pdf = os.path.join(self.temp_dir, "output_clean.pdf")
        saved = self.engine.fill_by_slot_ids(
            page_number=1,
            slot_answers={first_tag: "John Doe"},
            output_path=out_pdf,
            slot_catalog=catalog
        )

        self.assertTrue(os.path.exists(saved))
        # Ensure clean verification renders
        verify_img = self.engine.render_clean_verification_image(page_number=1, out_image_path=os.path.join(self.temp_dir, "verify.png"))
    def test_dynamic_margin_guard(self):
        """Verifies header lines (y < 55.0) are ignored by margin guard."""
        mg_pdf = os.path.join(self.temp_dir, "margin_guard_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Header rule at y=30 (should be rejected)
        page.draw_line(fitz.Point(50, 30), fitz.Point(545, 30), color=(0, 0, 0), width=1.0)
        # Header box at y=35..45 (should be rejected)
        page.draw_rect(fitz.Rect(50, 35, 120, 48), color=(0, 0, 0), width=1.0)

        # Valid exercise answer line at y=120
        page.draw_line(fitz.Point(60, 120), fitz.Point(300, 120), color=(0, 0, 0), width=1.0)
        doc.save(mg_pdf)
        doc.close()

        engine = HPEEngine(mg_pdf, temp_dir=self.temp_dir)
        slots = engine.detect_all_slots(page_number=1)

        for s in slots:
            y = s.get("baseline_y", s["bbox"][1])
            self.assertGreaterEqual(y, 55.0, f"Slot {s} is above margin guard threshold 55.0pt")

        self.assertTrue(any(abs(s.get("baseline_y", 0) - 120.0) < 3.0 for s in slots), "Valid line at y=120 must be detected")

    def test_context_grounding(self):
        """Verifies context and question_hint extraction in engine and server."""
        cg_pdf = os.path.join(self.temp_dir, "context_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Question 1 with inline blank
        page.insert_text(fitz.Point(50, 100), "1. What is your hobby:", fontsize=11)
        page.draw_line(fitz.Point(190, 102), fitz.Point(380, 102), color=(0, 0, 0), width=1.0)

        # Question 2 with box
        page.insert_text(fitz.Point(50, 160), "Question 2: Select option:", fontsize=11)
        page.draw_rect(fitz.Rect(210, 145, 270, 168), color=(0, 0, 0), width=1.0)

        doc.save(cg_pdf)
        doc.close()

        engine = HPEEngine(cg_pdf, temp_dir=self.temp_dir)
        slots = engine.detect_all_slots(page_number=1)
        self.assertGreaterEqual(len(slots), 2)

        slot1 = slots[0]
        self.assertEqual(slot1.get("question_hint"), "1")
        self.assertIn("What is your hobby", slot1.get("context", ""))

        slot2 = slots[1]
        self.assertEqual(slot2.get("question_hint"), "2")

        # Test server endpoint hpe_inspect_virtual_grid
        import json
        grid_json_str = hpe_inspect_virtual_grid(cg_pdf, page_number=1)
        grid_data = json.loads(grid_json_str)
        self.assertEqual(grid_data["status"], "success")
        self.assertIn("S01", grid_data["slots"])
        self.assertEqual(grid_data["slots"]["S01"]["question_hint"], "1")
        self.assertIn("What is your hobby", grid_data["slots"]["S01"]["context"])

    def test_unicode_vietnamese_text_injection(self):
        """Verifies full Unicode Vietnamese text injection with diacritics preserved."""
        vn_pdf = os.path.join(self.temp_dir, "vn_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(50, 100), "1. Điền thông tin cá nhân:", fontsize=11)
        page.draw_line(fitz.Point(50, 130), fitz.Point(400, 130), color=(0, 0, 0), width=1.0)
        doc.save(vn_pdf)
        doc.close()

        engine = HPEEngine(vn_pdf, temp_dir=self.temp_dir)
        _, catalog = engine.generate_virtual_grid_inspector(page_number=1)
        out_pdf = os.path.join(self.temp_dir, "vn_output.pdf")

        vn_text = "Nguyễn Văn An - Hà Nội, Việt Nam - Đặng Thùy Trâm"
        saved = engine.fill_by_slot_ids(
            page_number=1,
            slot_answers={"S01": vn_text},
            output_path=out_pdf,
            slot_catalog=catalog
        )

        self.assertTrue(os.path.exists(saved))
        # Re-read PDF and verify characters
        doc_out = fitz.open(saved)
        extracted = doc_out[0].get_text()
        doc_out.close()
        self.assertIn("Nguyễn Văn An", extracted)
        self.assertIn("Việt Nam", extracted)
        self.assertIn("Đặng Thùy Trâm", extracted)

    def test_cross_and_connector_line(self):
        """Verifies cross mark (X), connector line, and option circle operations."""
        draw_pdf = os.path.join(self.temp_dir, "draw_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(50, 100), "1. Choose Apple or Banana", fontsize=11)
        page.insert_text(fitz.Point(50, 150), "2. Choose Orange or Grape", fontsize=11)
        doc.save(draw_pdf)
        doc.close()

        engine = HPEEngine(draw_pdf, temp_dir=self.temp_dir)
        out_pdf = os.path.join(self.temp_dir, "draw_output.pdf")

        ops = {
            "cross_1": {"cx": 100, "cy": 120, "size": 5.0},
            "cross_2": {"bbox": [200, 200, 240, 240]},
            "connector_1": {"x0": 50, "y0": 60, "x1": 150, "y1": 80},
            "connector_2": {"start": [80, 90], "end": [200, 90]},
            "circle_word_1": {"word": "Banana", "question_hint": "1"},
        }
        saved = engine.fill_by_slot_ids(page_number=1, slot_answers=ops, output_path=out_pdf)
        self.assertTrue(os.path.exists(saved))

        # Check clean verification image
        verify_img = engine.render_clean_verification_image(page_number=1, out_image_path=os.path.join(self.temp_dir, "draw_verify.png"))
        self.assertTrue(os.path.exists(verify_img))

    def test_column_multiline_grouping(self):
        """Verifies 2-column layout correctly pairs vertically stacked lines in each column."""
        twocol_pdf = os.path.join(self.temp_dir, "twocol_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Column 1 lines (x=60)
        page.draw_line(fitz.Point(60, 100), fitz.Point(250, 100), color=(0, 0, 0), width=1.0)
        page.draw_line(fitz.Point(60, 116), fitz.Point(250, 116), color=(0, 0, 0), width=1.0)

        # Column 2 lines (x=320)
        page.draw_line(fitz.Point(320, 100), fitz.Point(510, 100), color=(0, 0, 0), width=1.0)
        page.draw_line(fitz.Point(320, 116), fitz.Point(510, 116), color=(0, 0, 0), width=1.0)

        doc.save(twocol_pdf)
        doc.close()

        engine = HPEEngine(twocol_pdf, temp_dir=self.temp_dir)
        slots = engine.detect_all_slots(page_number=1)
        self.assertEqual(len(slots), 4)

        col1_slots = sorted([s for s in slots if s["x0"] < 200], key=lambda s: s["baseline_y"])
        col2_slots = sorted([s for s in slots if s["x0"] > 300], key=lambda s: s["baseline_y"])

        self.assertEqual(len(col1_slots), 2)
        self.assertEqual(len(col2_slots), 2)

        # Col 1 first line should connect to Col 1 second line
        self.assertTrue(col1_slots[0].get("multiline_next", False))
        self.assertTrue(col1_slots[1].get("multiline_prev", False))

        # Col 2 first line should connect to Col 2 second line
        self.assertTrue(col2_slots[0].get("multiline_next", False))
        self.assertTrue(col2_slots[1].get("multiline_prev", False))

    def test_utils_get_default_temp_dir_and_font(self):
        """Verifies utility temp dir safety (no 'D:' on Linux) and font resolution."""
        from precision_pdf.utils import get_default_temp_dir, resolve_unicode_font
        temp_dir = get_default_temp_dir(self.test_pdf)
        self.assertTrue(os.path.exists(temp_dir))
        if sys.platform != "win32":
            self.assertFalse(temp_dir.startswith("D:"), "Temp dir must not reference D: on Linux")

        font_path = resolve_unicode_font()
        if sys.platform == "linux":
            self.assertIsNotNone(font_path)
            self.assertTrue(os.path.exists(font_path))

    def test_server_hpe_fill_slots_and_snap_fill(self):
        """Verifies server.hpe_fill_slots with cross, connector, and circle."""
        import json
        srv_pdf = os.path.join(self.temp_dir, "server_fill_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(60, 100), "1. What is your name?", fontsize=12)
        page.draw_line(fitz.Point(60, 140), fitz.Point(300, 140), color=(0, 0, 0), width=1.0)
        page.insert_text(fitz.Point(60, 180), "Options: (A) Apple  (B) Banana", fontsize=12)
        doc.save(srv_pdf)
        doc.close()

        # Test hpe_fill_slots
        out_pdf = os.path.join(self.temp_dir, "server_out.pdf")
        answers = {
            "S01": "Trần Thị Mai",
            "cross_1": {"cx": 100, "cy": 120},
            "connector_1": {"x0": 50, "y0": 50, "x1": 150, "y1": 50},
            "circle_word_1": {"word": "Apple", "question_hint": "1"}
        }
        res_str = hpe_fill_slots(srv_pdf, 1, json.dumps(answers), out_pdf)
        res = json.loads(res_str)
        self.assertEqual(res["status"], "success")
        self.assertTrue(os.path.exists(res["saved_path"]))

        # Verify output has Vietnamese text
        doc_out = fitz.open(res["saved_path"])
        self.assertIn("Trần Thị Mai", doc_out[0].get_text())
        doc_out.close()

    def test_column_aware_reading_order(self):
        """Verifies multi-column layout detection and Left->Right column reading order."""
        col_pdf = os.path.join(self.temp_dir, "two_column_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Left column (x=50..250): Ex 1 (y=120) and Ex 2 (y=300)
        page.insert_text(fitz.Point(50, 100), "Exercise 1: Vocabulary", fontsize=11)
        page.insert_text(fitz.Point(50, 120), "1. First left item:", fontsize=10)
        page.draw_line(fitz.Point(150, 122), fitz.Point(240, 122), color=(0, 0, 0), width=1.0)

        page.insert_text(fitz.Point(50, 280), "Exercise 2: Grammar", fontsize=11)
        page.insert_text(fitz.Point(50, 300), "2. Second left item:", fontsize=10)
        page.draw_line(fitz.Point(150, 302), fitz.Point(240, 302), color=(0, 0, 0), width=1.0)

        # Right column (x=330..530): Ex 3 (y=120) and Ex 4 (y=300)
        page.insert_text(fitz.Point(330, 100), "Exercise 3: Reading", fontsize=11)
        page.insert_text(fitz.Point(330, 120), "1. First right item:", fontsize=10)
        page.draw_line(fitz.Point(430, 122), fitz.Point(520, 122), color=(0, 0, 0), width=1.0)

        page.insert_text(fitz.Point(330, 280), "Exercise 4: Writing", fontsize=11)
        page.insert_text(fitz.Point(330, 300), "2. Second right item:", fontsize=10)
        page.draw_line(fitz.Point(430, 302), fitz.Point(520, 302), color=(0, 0, 0), width=1.0)

        doc.save(col_pdf)
        doc.close()

        engine = HPEEngine(col_pdf, temp_dir=self.temp_dir)
        slots = engine.detect_all_slots(page_number=1)
        self.assertEqual(len(slots), 4)

        # First 2 slots must be left column
        self.assertEqual(slots[0]["column"], "left")
        self.assertEqual(slots[1]["column"], "left")
        self.assertLess(slots[0]["bbox"][0], 300)
        self.assertLess(slots[1]["bbox"][0], 300)
        self.assertLess(slots[0]["baseline_y"], slots[1]["baseline_y"])

        # Next 2 slots must be right column
        self.assertEqual(slots[2]["column"], "right")
        self.assertEqual(slots[3]["column"], "right")
        self.assertGreater(slots[2]["bbox"][0], 300)
        self.assertGreater(slots[3]["bbox"][0], 300)
        self.assertLess(slots[2]["baseline_y"], slots[3]["baseline_y"])

    def test_header_margin_guard_advanced(self):
        """Verifies lines at y < 85 are ignored unless accompanied by a valid question number."""
        hm_pdf = os.path.join(self.temp_dir, "header_guard_adv.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Spurious decorative header rule at y=60 (no question number -> must be ignored)
        page.draw_line(fitz.Point(50, 60), fitz.Point(200, 60), color=(0, 0, 0), width=1.0)

        # Spurious decorative header rule at y=75 (no question number -> must be ignored)
        page.draw_line(fitz.Point(80, 75), fitz.Point(200, 75), color=(0, 0, 0), width=1.0)

        # Valid question header line at y=75 (with question number "1." in 20pt radius -> must be kept)
        page.insert_text(fitz.Point(385, 75), "1.", fontsize=10)
        page.draw_line(fitz.Point(400, 76), fitz.Point(520, 76), color=(0, 0, 0), width=1.0)

        # Normal question line at y=150 (must be kept)
        page.insert_text(fitz.Point(50, 150), "2. Normal question:", fontsize=10)
        page.draw_line(fitz.Point(150, 152), fitz.Point(300, 152), color=(0, 0, 0), width=1.0)

        doc.save(hm_pdf)
        doc.close()

        engine = HPEEngine(hm_pdf, temp_dir=self.temp_dir)
        slots = engine.detect_all_slots(page_number=1)

        baselines = [s.get("baseline_y", s["bbox"][1]) for s in slots]
        # Decorative lines at y=60 and left y=75 must not be in slots
        self.assertFalse(any(abs(b - 60.0) < 2.0 for b in baselines), "Decorative line at y=60 must be ignored")
        self.assertFalse(any(abs(b - 75.0) < 2.0 and s["bbox"][0] < 250 for b, s in zip(baselines, slots)), "Decorative line at y=75 without Q-number must be ignored")

        # Valid lines must be kept
        self.assertTrue(any(abs(b - 76.0) < 3.0 for b in baselines), "Line at y=76 with question number must be kept")
        self.assertTrue(any(abs(b - 152.0) < 3.0 for b in baselines), "Line at y=152 must be kept")

    def test_real_fixture_rlw_workbook(self):
        """Tests directly on real fixture RLW_Real Life Workbook-45-46.pdf Page 1."""
        real_pdf = "/home/zuan/CST_Assignments/scratch/RLW_Real Life Workbook-45-46.pdf"
        if not os.path.exists(real_pdf):
            self.skipTest(f"Fixture {real_pdf} not available")

        engine = HPEEngine(real_pdf, temp_dir=self.temp_dir)
        slots = engine.detect_all_slots(page_number=1)
        self.assertGreater(len(slots), 10)

        # Proof 1: No header lines at y=60 or y=75
        for s in slots:
            y = s.get("baseline_y", s["bbox"][1])
            self.assertGreaterEqual(y, 85.0, f"Slot {s.get('tag')} has y={y} < 85.0 pt")

        # Proof 2: Left column slots come first, followed by right column slots
        saw_right = False
        for s in slots:
            col = s.get("column")
            if col == "right":
                saw_right = True
            elif col == "left":
                self.assertFalse(saw_right, f"Found left slot {s.get('tag')} after right column slots!")


if __name__ == "__main__":
    unittest.main()
