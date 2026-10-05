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
from precision_pdf import server


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
        self.assertTrue(os.path.exists(verify_img))


if __name__ == "__main__":
    unittest.main()
