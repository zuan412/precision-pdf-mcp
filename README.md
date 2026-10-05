<div align="center">

# 🎯 Precision PDF MCP Server (`precision-pdf-mcp`)

**Pixel-Perfect PDF Form and Worksheet Filling for AI Coding Agents.**  
*Powered by Hybrid Vector-Raster Geometry, Set-of-Marks (SoM), and Virtual Excel Grounding.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compliant](https://img.shields.io/badge/MCP-2024--11--05-green.svg)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Zero Disk Pollution](https://img.shields.io/badge/Zero%20Disk%20Pollution-In--RAM%20NumPy-purple.svg)]()

</div>

---

## 💡 Why Precision PDF?

Filling assignment worksheets, tax forms, and scanned PDF workbooks has always been a painful failure mode for Large Language Models (LLMs):

- ❌ **The "Floating Text" Bug:** LLMs guess raw `(x, y)` floats, causing answers to float aimlessly above or below lines.
- ❌ **The "Collision" Bug:** Answers smash directly into printed text (e.g., `Heis going`, `Parentsmust`, `1)wear`).
- ❌ **The "Scanned PDF" Blindspot:** Most PDF tools rely only on vector drawings. Scanned workbooks have **0 vector lines**, leaving AI completely blind.
- ❌ **Multi-Line Truncation:** Long answers get crammed into line 1 or truncated because the agent doesn't realize two lines are printed for that question.

**Precision PDF solves this once and for all.**

---

## 🚀 Key Innovations

```
[ Input PDF: Digital or Scanned Workbook ]
                    │
                    ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 1. Tri-Layer Hybrid Detector                            │
  │    • Vector Lines & Rects (pdfplumber)                  │
  │    • In-Memory Morphological Line Scanner (NumPy)       │
  │      Detects physical lines in scanned images in RAM!   │
  │    • Text Anchors & Gap Numbers (1), 2., He_________)   │
  └─────────────────────────┬───────────────────────────────┘
                            │
                            ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 2. Context Guards & Smart Layout                        │
  │    • Padding Guard: Auto +6pt..+10pt margin after       │
  │      printed subjects (He, You, Jenny...)               │
  │    • Multi-Line Grouping: Detects stacked lines & auto- │
  │      wraps long sentences at natural word boundaries    │
  │    • Auto-Scale Font: Scales down font to prevent crash │
  └─────────────────────────┬───────────────────────────────┘
                            │
                            ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 3. Virtual Excel Matrix & Set-of-Marks (Agent View)     │
  │    • Renders Top Columns (A, B, C...) & Rows (1, 2, 3)  │
  │    • Badges targets: [S01], [S02], [S03]...             │
  │    • STRICTLY VIRTUAL: Only for the agent to inspect!   │
  └─────────────────────────┬───────────────────────────────┘
                            │
                            ▼
  ┌─────────────────────────────────────────────────────────┐
  │ 4. Clean Vector Injection (Output PDF)                  │
  │    • Baseline Snapped: Text rests 1.2pt above line      │
  │    • Centered in Boxes: Dead-center horizontally & vert │
  │    • Crisp Circles / Underlines: Vector option markers  │
  │    • ZERO GRID POLLUTION: Output PDF is 100% clean!     │
  └─────────────────────────────────────────────────────────┘
```

---

## 📦 Installation & Quickstart

### Method 1: Instant Run with `uvx` (Recommended)
No installation required. Run directly in Claude Desktop or Cursor via `uvx`:

```bash
uvx precision-pdf-mcp
```

### Method 2: Install via `pip`
```bash
pip install precision-pdf-mcp
```

### Method 3: From Source (Local Development)
```bash
git clone https://github.com/zuan412/precision-pdf-mcp.git
cd precision-pdf-mcp
pip install -e .
```

---

## 🛠️ MCP Client Configuration

### 1. Claude Desktop
Add to your `claude_desktop_config.json`:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "precision-pdf": {
      "command": "uvx",
      "args": ["precision-pdf-mcp"]
    }
  }
}
```

### 2. Cursor IDE
Add to Cursor Settings -> MCP Servers (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "precision-pdf": {
      "command": "uvx",
      "args": ["precision-pdf-mcp"]
    }
  }
}
```

### 3. Antigravity / Gemini CLI / Windsurf / Cline
In your `mcp_config.json`:

```json
{
  "mcpServers": {
    "precision-pdf": {
      "command": "python",
      "args": ["-m", "precision_pdf"]
    }
  }
}
```

---

## 🧰 Available MCP Tools

### `hpe_inspect_virtual_grid`
Generates a temporary Virtual Excel Matrix inspector image with Set-of-Marks badges (`[S01]`, `[S02]`...) and returns a JSON catalog of detected slots.
* **Arguments:**
  - `pdf_path` (string, required): Absolute path to the PDF.
  - `page_number` (int, required): 1-based page number.
  - `dpi` (int, optional, default: 150): Image resolution.
* **Returns:**
  - `inspector_image_path`: Path to the image for agent visual inspection.
  - `slots`: Dictionary of slots containing grid address (e.g. `Col D, Row 14`), type, baseline, and width.

### `hpe_fill_slots`
Injects answers directly into the target PDF using Slot IDs.
* **Arguments:**
  - `pdf_path` (string, required): Absolute path to the PDF.
  - `page_number` (int, required): 1-based page number.
  - `slot_answers_json` (string, required): JSON string of answers.
    - Slot map: `{"S01": "must have left", "S02": "could do"}`
    - Multi-line wrap: `{"S03": ["first line text", "second line text"]}`
    - Option circle: `{"circle_option": "A"}`
    - Option underline: `{"underline_option": "Shall"}`
  - `output_path` (string, optional): Output PDF path. If omitted, safely updates in-place.
* **Guarantees:**
  - **100% baseline snap** (rests naturally on the printed line).
  - **Zero grid pollution** (no rulers or badges in final output).

### `hpe_render_clean_verify`
Renders the final, clean PDF page to an image for visual QA verification.
* **Arguments:**
  - `pdf_path` (string, required): Path to the completed PDF.
  - `page_number` (int, required): 1-based page number.
  - `dpi` (int, optional, default: 150): Output DPI.

---

## 🧪 Testing

Run the included unit test suite:

```bash
python -m unittest discover -s tests
```

---

## 🛡️ Zero Disk Pollution & Safety Guarantee

Precision PDF is engineered to run in memory:
- All morphological line detection and raster scanning execute in RAM via NumPy arrays and `io.BytesIO`.
- Temporary inspector previews use OS-standard `tempfile.gettempdir()/precision_pdf` or the `$PRECISION_PDF_TEMP_DIR` environment variable.
- Stdio JSON-RPC communication is 100% isolated: all logs, warnings, and internal debug outputs route strictly to `sys.stderr`.

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details. Built with ❤️ for the AI agent pair-programming community.
