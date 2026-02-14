# tptpy

A terminal UI for interactively testing **TextFSM** and **TTP** templates against network device output — with live parsed results and auto-generated Python snippets you can drop straight into your automation.

![Parse Tester TUI](https://raw.githubusercontent.com/scottpeterman/tptpy/main/screenshots/tui1.png)

## What this is for and why

Writing TextFSM and TTP templates is an iterative process: tweak the template, run it, check the output, repeat. Most workflows involve bouncing between a text editor, a Python REPL, and maybe a browser-based tool that doesn't have your files.

**tptpy** puts everything in one screen:

- **Source text** (left top) — paste or load device output from the file tree
- **Template** (right top) — your TextFSM or TTP template
- **Parsed result** (left bottom) — JSON or table view, updated on each parse
- **Python snippet** (right bottom) — a self-contained script embedding your source + template, ready to copy

The directory tree auto-routes files: `.textfsm`, `.template`, `.ttp`, and `.tpl` extensions load into the template pane; everything else loads into the source pane.

## Installation

### From PyPI

```bash
pip install tptpy
```

### From Source

```bash
git clone https://github.com/scottpeterman/tptpy.git
cd tptpy
pip install .
```

### Development

```bash
git clone https://github.com/scottpeterman/tptpy.git
cd tptpy
pip install -e ".[dev]"
```

## Usage

```bash
# Launch in current directory
tptpy

# Launch rooted at a specific project
tptpy ~/templates/bgp

# Or run as a module
python -m tptpy ~/templates/bgp
```

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Ctrl+P` | Run parse |
| `Ctrl+S` | Save source pane (directory picker) |
| `Ctrl+T` | Save template pane (directory picker) |
| `Ctrl+R` | Focus the root path input |
| `F2` | Rename selected file/folder |
| `Delete` | Delete selected file/folder |
| `Ctrl+Q` | Quit |

## Supported Parsers

| Parser | Template Style | Best For |
|---|---|---|
| **TextFSM** | Value declarations + regex state machine | Structured CLI output (show commands) |
| **TTP** | Template with `{{ variable }}` placeholders | Output that closely mirrors the template shape |

## Features

- **Four-pane layout** — source, template, results, and snippet visible simultaneously
- **File tree with smart routing** — template extensions auto-load to the template pane
- **File management** — create, rename, and delete files and folders directly from the sidebar
- **Save with directory picker** — save source or template content to any location in your project tree
- **JSON and table views** — toggle between structured JSON and a tabular DataTable
- **Actionable error messages** — parse failures include line numbers, context, and fix hints
- **Auto-generated snippets** — each successful parse produces a standalone Python script
- **Filtered directory tree** — shows only text and template files (`.txt`, `.log`, `.cfg`, `.textfsm`, `.ttp`, `.yaml`, `.json`, etc.)

## Quick Example

1. Launch `tptpy` pointed at a directory containing your show command output and templates
2. Click a `.txt` or `.log` file — it loads into **Source Text**
3. Click a `.textfsm` file — it loads into **Template**
4. Hit `Ctrl+P` or click **▶ Parse**
5. Review results in JSON or Table view; grab the Python snippet for your project
6. Hit `Ctrl+S` to save source or `Ctrl+T` to save your template — pick the directory and filename

## Requirements

- Python 3.10+
- [Textual](https://github.com/Textualize/textual) — TUI framework
- [TextFSM](https://github.com/google/textfsm) — Google's template-based state machine parser
- [TTP](https://github.com/dmulyalin/ttp) — Template Text Parser

## Project Structure

```
tptpy/
├── pyproject.toml
├── README.md
├── screenshots/
│   └── tui1.png
└── tptpy/
    ├── __init__.py
    └── __main__.py
```

## License

MIT

## Author

**Scott Peterman** — Principal Infrastructure Engineer, network automation toolsmith.
Part of a broader toolkit for practical network engineering: [github.com/scottpeterman](https://github.com/scottpeterman)