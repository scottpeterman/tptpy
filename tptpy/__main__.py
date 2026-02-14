#!/usr/bin/env python3
"""
Parse Tester - A Textual TUI for testing TextFSM and TTP templates
against source text with live results and exportable Python snippets.

Usage:
    python -m tptpy [ROOT_PATH]
    tptpy [ROOT_PATH]
"""

import json
import os
import re
import sys
import io
from pathlib import Path
from typing import Any, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
    TextArea,
)
from textual.widgets._directory_tree import DirEntry

# ---------------------------------------------------------------------------
# Parser backends
# ---------------------------------------------------------------------------

def parse_textfsm(source: str, template: str) -> list[dict[str, Any]]:
    """Parse source text with a TextFSM template, return list of dicts."""
    import textfsm as tfsm

    tpl_fh = io.StringIO(template)
    parser = tfsm.TextFSM(tpl_fh)
    raw = parser.ParseText(source)
    headers = parser.header
    return [dict(zip(headers, row)) for row in raw]


def parse_ttp(source: str, template: str) -> list[dict[str, Any]]:
    """Parse source text with a TTP template, return list of dicts."""
    from ttp import ttp as ttp_mod

    parser = ttp_mod(data=source, template=template)
    parser.parse()
    results = parser.result(format="raw")
    # TTP nests results: [[[records]]], flatten until we get list of dicts
    while results and isinstance(results, list) and len(results) > 0:
        if isinstance(results[0], dict):
            break
        results = results[0]
    return results if isinstance(results, list) else []


PARSERS = {
    "textfsm": parse_textfsm,
    "ttp": parse_ttp,
}

# ---------------------------------------------------------------------------
# Friendly error formatting
# ---------------------------------------------------------------------------

def _format_textfsm_error(exc: Exception, template: str) -> str:
    """Extract actionable info from a TextFSM exception."""
    msg = str(exc)
    lines = template.splitlines()
    parts = ["TextFSM Error", "=" * 50, ""]

    line_match = re.search(r"[Ll]ine:?\s*(\d+)", msg)
    if line_match:
        line_no = int(line_match.group(1))
        parts.append(f"  Problem at line {line_no}:")
        start = max(0, line_no - 3)
        end = min(len(lines), line_no + 2)
        for i in range(start, end):
            marker = " >>>" if i == line_no - 1 else "    "
            parts.append(f"{marker} {i + 1:3d} | {lines[i]}")
        parts.append("")

    if "Invalid state name" in msg:
        parts.append("  Issue: Invalid state name in Value definition.")
        parts.append("  Hint:  Blank lines are not allowed between Value")
        parts.append("         declarations. Remove any empty lines before")
        parts.append("         the 'Start' state.")
    elif "No 'Start' state" in msg or "no Start state" in msg.lower():
        parts.append("  Issue: Missing 'Start' state.")
        parts.append("  Hint:  Every TextFSM template needs a 'Start' state")
        parts.append("         after the Value declarations.")
    elif "duplicate" in msg.lower():
        parts.append("  Issue: Duplicate value or state name.")
        parts.append("  Hint:  Each Value name must be unique.")
    elif "rule" in msg.lower() and "syntax" in msg.lower():
        parts.append("  Issue: Rule syntax error.")
        parts.append("  Hint:  Check regex patterns and -> actions.")
    else:
        parts.append(f"  Detail: {msg}")

    return "\n".join(parts)


def _format_ttp_error(exc: Exception, template: str) -> str:
    """Extract actionable info from a TTP exception."""
    msg = str(exc)
    lines = template.splitlines()
    parts = ["TTP Error", "=" * 50, ""]

    if "template" in msg.lower():
        parts.append("  Issue: Template syntax problem.")
    elif "variable" in msg.lower() or "match" in msg.lower():
        parts.append("  Issue: Variable/match definition error.")
    else:
        parts.append(f"  Detail: {msg}")

    parts.append("")
    parts.append("  Template preview:")
    for i, line in enumerate(lines[:10], 1):
        parts.append(f"    {i:3d} | {line}")
    if len(lines) > 10:
        parts.append(f"    ... ({len(lines) - 10} more lines)")

    parts.append("")
    parts.append("  Tips:")
    parts.append("  - Check that {{ variable }} placeholders match source structure")
    parts.append("  - Use {{ ignore }} to skip fields you don't need")
    parts.append("  - Whitespace in the template must match the source text")

    return "\n".join(parts)


def format_parse_error(parser_name: str, exc: Exception, template: str) -> str:
    """Route to the appropriate error formatter."""
    if parser_name == "textfsm":
        return _format_textfsm_error(exc, template)
    elif parser_name == "ttp":
        return _format_ttp_error(exc, template)
    else:
        return f"Parse Error: {exc}"

# ---------------------------------------------------------------------------
# Snippet generator
# ---------------------------------------------------------------------------

SNIPPET_TEXTFSM = '''\
#!/usr/bin/env python3
"""Auto-generated TextFSM parse snippet."""
import io, json, textfsm

TEMPLATE = """{template}"""

SOURCE = """{source}"""

parser = textfsm.TextFSM(io.StringIO(TEMPLATE))
raw = parser.ParseText(SOURCE)
headers = parser.header
results = [dict(zip(headers, row)) for row in raw]
print(json.dumps(results, indent=2))
'''

SNIPPET_TTP = '''\
#!/usr/bin/env python3
"""Auto-generated TTP parse snippet."""
import json
from ttp import ttp

TEMPLATE = """{template}"""

SOURCE = """{source}"""

parser = ttp(data=SOURCE, template=TEMPLATE)
parser.parse()
results = parser.result(format="raw")
if results and isinstance(results[0], list):
    results = results[0]
print(json.dumps(results, indent=2))
'''


def generate_snippet(parser_type: str, source: str, template: str) -> str:
    """Return a self-contained Python script embedding source + template."""
    tpl = SNIPPET_TEXTFSM if parser_type == "textfsm" else SNIPPET_TTP
    return tpl.format(
        template=template.replace('"""', r'\"\"\"'),
        source=source.replace('"""', r'\"\"\"'),
    )


# ---------------------------------------------------------------------------
# Custom filtered directory tree (show common text/template extensions)
# ---------------------------------------------------------------------------

TEXT_EXTENSIONS = {
    ".txt", ".log", ".cfg", ".conf", ".csv", ".json", ".yaml", ".yml",
    ".xml", ".textfsm", ".template", ".ttp", ".tpl", ".py", ".md",
    ".ini", ".toml",
}


class FilteredDirectoryTree(DirectoryTree):
    """DirectoryTree that filters to text-ish files."""

    def filter_paths(self, paths: list[Path]) -> list[Path]:
        return [
            p for p in paths
            if p.is_dir() or p.suffix.lower() in TEXT_EXTENSIONS
        ]


class FolderOnlyTree(DirectoryTree):
    """DirectoryTree that shows only directories (for save dialog)."""

    def filter_paths(self, paths: list[Path]) -> list[Path]:
        return [p for p in paths if p.is_dir()]


# ---------------------------------------------------------------------------
# Modal dialog screens
# ---------------------------------------------------------------------------

class SaveDialog(ModalScreen[Optional[Path]]):
    """Modal save dialog with directory picker and filename input."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    CSS = """
    SaveDialog {
        align: center middle;
    }
    #save-dialog-container {
        width: 70;
        height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #save-dialog-container > Label {
        text-style: bold;
        margin-bottom: 1;
    }
    #save-dir-tree {
        height: 1fr;
        margin-bottom: 1;
        border: round $primary-background;
    }
    #save-path-display {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
        padding: 0 1;
    }
    #save-filename-input {
        margin-bottom: 1;
    }
    #save-button-row {
        height: auto;
        align-horizontal: right;
    }
    #save-button-row Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        root_path: str,
        suggested_name: str = "",
        title: str = "Save File",
    ):
        super().__init__()
        self._root_path = root_path
        self._suggested_name = suggested_name
        self._title = title
        self._selected_dir: Path = Path(root_path)

    def compose(self) -> ComposeResult:
        with Vertical(id="save-dialog-container"):
            yield Label(self._title)
            yield FolderOnlyTree(self._root_path, id="save-dir-tree")
            yield Static(
                f"  Directory: {self._selected_dir}",
                id="save-path-display",
            )
            yield Input(
                value=self._suggested_name,
                placeholder="filename.ext",
                id="save-filename-input",
            )
            with Horizontal(id="save-button-row"):
                yield Button("Cancel", id="save-cancel-btn", variant="default")
                yield Button("Save", id="save-ok-btn", variant="success")

    def on_mount(self) -> None:
        self.query_one("#save-filename-input", Input).focus()

    @on(DirectoryTree.DirectorySelected, "#save-dir-tree")
    def handle_dir_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self._selected_dir = event.path
        self.query_one("#save-path-display", Static).update(
            f"  Directory: {event.path}"
        )

    @on(Button.Pressed, "#save-ok-btn")
    def handle_save(self) -> None:
        filename = self.query_one("#save-filename-input", Input).value.strip()
        if not filename:
            self.query_one("#save-path-display", Static).update(
                "  ⚠ Enter a filename"
            )
            return
        full_path = self._selected_dir / filename
        self.dismiss(full_path)

    @on(Button.Pressed, "#save-cancel-btn")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#save-filename-input")
    def handle_input_submit(self) -> None:
        """Allow Enter in the filename input to trigger save."""
        self.handle_save()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDialog(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-container {
        width: 60;
        height: auto;
        max-height: 12;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-container > Label {
        margin-bottom: 1;
    }
    #confirm-message {
        margin-bottom: 1;
        color: $text;
    }
    #confirm-button-row {
        height: auto;
        align-horizontal: right;
    }
    #confirm-button-row Button {
        margin-left: 1;
    }
    """

    def __init__(self, message: str, title: str = "Confirm"):
        super().__init__()
        self._message = message
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(self._title)
            yield Static(self._message, id="confirm-message")
            with Horizontal(id="confirm-button-row"):
                yield Button("Cancel", id="confirm-no-btn", variant="default")
                yield Button("Delete", id="confirm-yes-btn", variant="error")

    @on(Button.Pressed, "#confirm-yes-btn")
    def handle_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no-btn")
    def handle_no(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputDialog(ModalScreen[Optional[str]]):
    """Single-input dialog for rename / new file / new folder."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    CSS = """
    InputDialog {
        align: center middle;
    }
    #input-dialog-container {
        width: 60;
        height: auto;
        max-height: 10;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #input-dialog-container > Label {
        text-style: bold;
        margin-bottom: 1;
    }
    #input-dialog-field {
        margin-bottom: 1;
    }
    #input-dialog-button-row {
        height: auto;
        align-horizontal: right;
    }
    #input-dialog-button-row Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        title: str = "Input",
        placeholder: str = "",
        initial_value: str = "",
        ok_label: str = "OK",
    ):
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._initial_value = initial_value
        self._ok_label = ok_label

    def compose(self) -> ComposeResult:
        with Vertical(id="input-dialog-container"):
            yield Label(self._title)
            yield Input(
                value=self._initial_value,
                placeholder=self._placeholder,
                id="input-dialog-field",
            )
            with Horizontal(id="input-dialog-button-row"):
                yield Button(
                    "Cancel", id="input-cancel-btn", variant="default"
                )
                yield Button(
                    self._ok_label, id="input-ok-btn", variant="primary"
                )

    def on_mount(self) -> None:
        self.query_one("#input-dialog-field", Input).focus()

    @on(Button.Pressed, "#input-ok-btn")
    def handle_ok(self) -> None:
        value = self.query_one("#input-dialog-field", Input).value.strip()
        if value:
            self.dismiss(value)

    @on(Button.Pressed, "#input-cancel-btn")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#input-dialog-field")
    def handle_submit(self) -> None:
        self.handle_ok()

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class ParseTesterApp(App):
    """Textual app for interactively testing TextFSM / TTP templates."""

    TITLE = "Parse Tester"
    CSS = """
    /* ── overall layout ── */
    #main-container {
        height: 1fr;
    }

    /* ── left sidebar: tree ── */
    #left-sidebar {
        width: 30;
        min-width: 24;
        border-right: thick $primary-background;
    }
    #left-sidebar > Label {
        padding: 0 1;
        text-style: bold;
        color: $text;
        background: $primary-background;
        width: 100%;
    }
    #root-input {
        margin: 0 1;
    }
    #set-root-btn {
        margin: 0 1;
        min-width: 10;
    }
    #dir-tree {
        height: 1fr;
    }

    /* ── file management buttons ── */
    #file-mgmt-bar {
        height: auto;
        padding: 0 1;
        background: $primary-background;
    }
    #file-mgmt-bar Button {
        min-width: 1;
        width: 1fr;
        margin: 0;
    }

    /* ── right workspace ── */
    #workspace {
        width: 1fr;
    }

    /* ── editor panes (top half) ── */
    #editor-row {
        height: 1fr;
    }
    #source-pane, #template-pane {
        width: 1fr;
        border: round $primary;
        padding: 0;
    }
    #source-pane Label, #template-pane Label {
        padding: 0 1;
        text-style: bold;
        color: $text;
        background: $primary-background;
        width: 100%;
    }

    /* ── results panes (bottom half) ── */
    #results-row {
        height: 1fr;
    }
    #results-pane, #snippet-pane {
        width: 1fr;
        border: round $accent;
        padding: 0;
    }
    #results-pane Label, #snippet-pane Label {
        padding: 0 1;
        text-style: bold;
        color: $text;
        background: $primary-background;
        width: 100%;
    }

    /* ── controls bar ── */
    #controls-bar {
        height: auto;
        padding: 0 1;
        background: $primary-background;
        align: center middle;
    }
    #controls-bar Select {
        width: 20;
        margin: 0 1;
    }
    #controls-bar Button {
        margin: 0 1;
    }
    #controls-bar RadioSet {
        layout: horizontal;
        height: auto;
        margin: 0 1;
    }

    /* ── content switcher ── */
    #result-switcher {
        height: 1fr;
    }

    /* ── text areas ── */
    TextArea {
        height: 1fr;
    }
    #result-json {
        height: 1fr;
    }
    #result-table {
        height: 1fr;
    }
    #snippet-text {
        height: 1fr;
    }

    /* ── status bar ── */
    #status-bar {
        height: 1;
        background: $primary-background;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+p", "parse", "Parse", show=True),
        Binding("ctrl+s", "save_source", "Save Src", show=True),
        Binding("ctrl+t", "save_template", "Save Tpl", show=True),
        Binding("ctrl+r", "set_root", "Set Root", show=True),
        Binding("f2", "rename_file", "Rename", show=False),
        Binding("delete", "delete_file", "Delete", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    def __init__(self, root_path: str = "."):
        super().__init__()
        self.root_path = str(Path(root_path).resolve())

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-container"):
            # ── Left sidebar: directory tree ──
            with Vertical(id="left-sidebar"):
                yield Label("📁 Project Root")
                yield Input(
                    value=self.root_path,
                    placeholder="/path/to/project",
                    id="root-input",
                )
                yield Button("Set Root", id="set-root-btn", variant="primary")
                yield FilteredDirectoryTree(self.root_path, id="dir-tree")

                # File management buttons
                with Horizontal(id="file-mgmt-bar"):
                    yield Button(
                        "+File", id="new-file-btn", variant="default"
                    )
                    yield Button(
                        "+Dir", id="new-dir-btn", variant="default"
                    )
                    yield Button(
                        "Ren", id="rename-btn", variant="default"
                    )
                    yield Button(
                        "Del", id="delete-btn", variant="error"
                    )

            # ── Right workspace ──
            with Vertical(id="workspace"):
                # Controls bar
                with Horizontal(id="controls-bar"):
                    yield Select(
                        [(name.upper(), name) for name in PARSERS],
                        value="textfsm",
                        prompt="Parser",
                        id="parser-select",
                        allow_blank=False,
                    )
                    yield Button("▶ Parse", id="parse-btn", variant="success")
                    yield Button("Clear All", id="clear-btn", variant="warning")
                    yield Label("Result View:")
                    yield RadioSet(
                        RadioButton("JSON", value=True, id="radio-json"),
                        RadioButton("Table", id="radio-table"),
                        id="view-radio",
                    )

                # Top half: source + template
                with Horizontal(id="editor-row"):
                    with Vertical(id="source-pane"):
                        yield Label("📄 Source Text")
                        yield TextArea.code_editor(
                            "",
                            id="source-text",
                            theme="monokai",
                        )
                    with Vertical(id="template-pane"):
                        yield Label("📝 Template")
                        yield TextArea.code_editor(
                            "",
                            id="template-text",
                            theme="monokai",
                        )

                # Bottom half: results + snippet
                with Horizontal(id="results-row"):
                    with Vertical(id="results-pane"):
                        yield Label("📊 Parsed Result")
                        with ContentSwitcher(
                            initial="result-json", id="result-switcher"
                        ):
                            yield TextArea.code_editor(
                                "",
                                language="json",
                                read_only=True,
                                id="result-json",
                                theme="monokai",
                            )
                            yield DataTable(id="result-table")

                    with Vertical(id="snippet-pane"):
                        yield Label("🐍 Python Snippet")
                        yield TextArea.code_editor(
                            "# Parse to generate a snippet...",
                            language="python",
                            read_only=True,
                            id="snippet-text",
                            theme="monokai",
                        )

        yield Static("Ready", id="status-bar")
        yield Footer()

    # ----- helpers -----

    def _get_selected_tree_path(self) -> Optional[Path]:
        """Return the path of the currently highlighted node in the tree."""
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        node = tree.cursor_node
        if node is None:
            return None
        return node.data.path if node.data else None

    def _refresh_tree(self) -> None:
        """Reload the directory tree to reflect filesystem changes."""
        tree = self.query_one("#dir-tree", FilteredDirectoryTree)
        tree.reload()

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-bar", Static).update(msg)

    # ----- parse actions / event handlers -----

    def action_parse(self) -> None:
        """Trigger a parse run."""
        self._run_parse()

    def action_set_root(self) -> None:
        """Focus the root input."""
        self.query_one("#root-input", Input).focus()

    @on(Button.Pressed, "#parse-btn")
    def handle_parse_btn(self) -> None:
        self._run_parse()

    @on(Button.Pressed, "#clear-btn")
    def handle_clear_btn(self) -> None:
        self.query_one("#source-text", TextArea).text = ""
        self.query_one("#template-text", TextArea).text = ""
        self.query_one("#result-json", TextArea).text = ""
        self.query_one("#snippet-text", TextArea).text = (
            "# Parse to generate a snippet..."
        )
        table = self.query_one("#result-table", DataTable)
        table.clear(columns=True)
        self._set_status("Cleared.")

    @on(Button.Pressed, "#set-root-btn")
    def handle_set_root(self) -> None:
        path_input = self.query_one("#root-input", Input)
        new_root = Path(path_input.value).expanduser().resolve()
        if new_root.is_dir():
            tree = self.query_one("#dir-tree", FilteredDirectoryTree)
            tree.path = new_root
            tree.reload()
            self.root_path = str(new_root)
            self._set_status(f"Root set: {new_root}")
        else:
            self._set_status(f"⚠ Not a valid directory: {new_root}")

    @on(DirectoryTree.FileSelected, "#dir-tree")
    def handle_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Load selected file into the appropriate text area."""
        path = event.path
        try:
            content = path.read_text(errors="replace")
        except Exception as exc:
            self._set_status(f"⚠ Could not read {path.name}: {exc}")
            return

        # Decide where to load: templates go to template pane, else source
        if path.suffix.lower() in {".textfsm", ".template", ".ttp", ".tpl"}:
            self.query_one("#template-text", TextArea).text = content
            self._set_status(f"Template loaded: {path.name}")
        else:
            self.query_one("#source-text", TextArea).text = content
            self._set_status(f"Source loaded: {path.name}")

    @on(RadioSet.Changed, "#view-radio")
    def handle_view_toggle(self, event: RadioSet.Changed) -> None:
        switcher = self.query_one("#result-switcher", ContentSwitcher)
        if event.index == 0:
            switcher.current = "result-json"
        else:
            switcher.current = "result-table"

    # ----- save actions -----

    def action_save_source(self) -> None:
        """Save source pane content via save dialog."""
        content = self.query_one("#source-text", TextArea).text
        if not content.strip():
            self._set_status("⚠ Source pane is empty — nothing to save.")
            return
        self._open_save_dialog(content, "source", "Save Source Text")

    def action_save_template(self) -> None:
        """Save template pane content via save dialog."""
        content = self.query_one("#template-text", TextArea).text
        if not content.strip():
            self._set_status("⚠ Template pane is empty — nothing to save.")
            return

        # Suggest an extension based on parser type
        parser_name = self.query_one("#parser-select", Select).value
        if parser_name == "ttp":
            suggested = "template.ttp"
        else:
            suggested = "template.textfsm"
        self._open_save_dialog(
            content, "template", "Save Template", suggested
        )

    def _open_save_dialog(
        self,
        content: str,
        pane: str,
        title: str,
        suggested_name: str = "",
    ) -> None:
        """Open save dialog and write file on completion."""

        def on_save_result(result: Optional[Path]) -> None:
            if result is None:
                self._set_status("Save cancelled.")
                return
            try:
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(content)
                self._refresh_tree()
                self._set_status(f"✓ Saved {pane}: {result}")
            except Exception as exc:
                self._set_status(f"⚠ Save failed: {exc}")

        self.push_screen(
            SaveDialog(
                root_path=self.root_path,
                suggested_name=suggested_name,
                title=title,
            ),
            callback=on_save_result,
        )

    # ----- file management: new file / new directory -----

    @on(Button.Pressed, "#new-file-btn")
    def handle_new_file(self) -> None:
        self._create_new("file")

    @on(Button.Pressed, "#new-dir-btn")
    def handle_new_dir(self) -> None:
        self._create_new("directory")

    def _create_new(self, kind: str) -> None:
        """Prompt for a name and create a new file or directory."""
        selected = self._get_selected_tree_path()
        if selected and selected.is_dir():
            parent = selected
        elif selected and selected.is_file():
            parent = selected.parent
        else:
            parent = Path(self.root_path)

        def on_name(name: Optional[str]) -> None:
            if name is None:
                return
            target = parent / name
            try:
                if kind == "directory":
                    target.mkdir(parents=True, exist_ok=True)
                    self._set_status(f"✓ Created directory: {target.name}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    self._set_status(f"✓ Created file: {target.name}")
                self._refresh_tree()
            except Exception as exc:
                self._set_status(f"⚠ Create failed: {exc}")

        self.push_screen(
            InputDialog(
                title=f"New {kind} in: {parent.name}/",
                placeholder=(
                    "my_template.textfsm" if kind == "file" else "subfolder"
                ),
                ok_label="Create",
            ),
            callback=on_name,
        )

    # ----- file management: rename -----

    def action_rename_file(self) -> None:
        self._rename_selected()

    @on(Button.Pressed, "#rename-btn")
    def handle_rename_btn(self) -> None:
        self._rename_selected()

    def _rename_selected(self) -> None:
        """Rename the currently selected file or directory."""
        selected = self._get_selected_tree_path()
        if selected is None:
            self._set_status("⚠ Select a file or folder to rename.")
            return

        def on_new_name(new_name: Optional[str]) -> None:
            if new_name is None:
                return
            new_path = selected.parent / new_name
            if new_path.exists():
                self._set_status(f"⚠ Already exists: {new_name}")
                return
            try:
                selected.rename(new_path)
                self._refresh_tree()
                self._set_status(
                    f"✓ Renamed: {selected.name} → {new_name}"
                )
            except Exception as exc:
                self._set_status(f"⚠ Rename failed: {exc}")

        self.push_screen(
            InputDialog(
                title=f"Rename: {selected.name}",
                initial_value=selected.name,
                ok_label="Rename",
            ),
            callback=on_new_name,
        )

    # ----- file management: delete -----

    def action_delete_file(self) -> None:
        self._delete_selected()

    @on(Button.Pressed, "#delete-btn")
    def handle_delete_btn(self) -> None:
        self._delete_selected()

    def _delete_selected(self) -> None:
        """Delete the currently selected file or empty directory."""
        selected = self._get_selected_tree_path()
        if selected is None:
            self._set_status("⚠ Select a file or folder to delete.")
            return

        kind = "directory" if selected.is_dir() else "file"

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                self._set_status("Delete cancelled.")
                return
            try:
                if selected.is_dir():
                    if any(selected.iterdir()):
                        self._set_status(
                            "⚠ Directory not empty. Remove contents first."
                        )
                        return
                    selected.rmdir()
                else:
                    selected.unlink()
                self._refresh_tree()
                self._set_status(f"✓ Deleted: {selected.name}")
            except Exception as exc:
                self._set_status(f"⚠ Delete failed: {exc}")

        self.push_screen(
            ConfirmDialog(
                message=f"Delete {kind}: {selected.name}?",
                title="Confirm Delete",
            ),
            callback=on_confirm,
        )

    # ----- core parse logic -----

    def _run_parse(self) -> None:
        source = self.query_one("#source-text", TextArea).text
        template = self.query_one("#template-text", TextArea).text
        parser_name = self.query_one("#parser-select", Select).value

        if not source.strip():
            self._set_status("⚠ Source text is empty.")
            return
        if not template.strip():
            self._set_status("⚠ Template is empty.")
            return
        if parser_name is Select.BLANK:
            self._set_status("⚠ Select a parser type.")
            return

        parse_fn = PARSERS[parser_name]

        try:
            results = parse_fn(source, template)
        except Exception as exc:
            error_msg = format_parse_error(parser_name, exc, template)
            self.query_one("#result-json", TextArea).text = error_msg
            table = self.query_one("#result-table", DataTable)
            table.clear(columns=True)
            self.query_one("#snippet-text", TextArea).text = (
                f"# Parse failed — fix template first\n# {exc}"
            )
            self._set_status(f"✗ {parser_name.upper()}: {exc}")
            return

        # ── populate JSON view ──
        json_str = json.dumps(results, indent=2, default=str)
        self.query_one("#result-json", TextArea).text = json_str

        # ── populate table view ──
        table = self.query_one("#result-table", DataTable)
        table.clear(columns=True)
        if results and isinstance(results[0], dict):
            cols = list(results[0].keys())
            for col in cols:
                table.add_column(col, key=col)
            for row in results:
                table.add_row(*[str(row.get(c, "")) for c in cols])

        # ── generate Python snippet ──
        snippet = generate_snippet(parser_name, source, template)
        self.query_one("#snippet-text", TextArea).text = snippet

        count = len(results)
        self._set_status(
            f"✓ Parsed {count} record{'s' if count != 1 else ''} "
            f"with {parser_name.upper()}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Console entry point."""
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    app = ParseTesterApp(root_path=root)
    app.run()


if __name__ == "__main__":
    main()