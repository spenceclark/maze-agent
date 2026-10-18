"""Notebook edits: splices (spec §5.4) and the rolling-log variant (`notebook_ops="append_log"`)."""

from maze_lab.agent_contracts import (
    AppendTurnAction,
    Notebook,
    NotebookEdit,
    NotebookRejection,
    TurnAction,
    utf8_len,
)

# The new notebook, the splice that was applied, and how many of the oldest code points the
# rolling log then dropped to fit the cap (always 0 for splices).
type NotebookUpdate = tuple[Notebook, NotebookEdit, int]


def _note(action: AppendTurnAction) -> str | None:
    """Blank text or the string "null" means no note: small models send these where they mean null."""
    text = action.notebook_append
    if text is None or not text.strip() or text.strip().lower() == "null":
        return None
    return text


def requested_change(action: TurnAction | AppendTurnAction) -> bool:
    if isinstance(action, TurnAction):
        return action.notebook_edit is not None
    return _note(action) is not None


def apply_change(
    action: TurnAction | AppendTurnAction, notebook: Notebook, cap_bytes: int, insert_bytes: int
) -> NotebookUpdate | NotebookRejection:
    """Apply the notebook change an action requests (`requested_change` must be true)."""
    if isinstance(action, TurnAction):
        assert action.notebook_edit is not None
        result = apply_splice(notebook, action.notebook_edit, cap_bytes, insert_bytes)
        return result if isinstance(result, str) else (result, action.notebook_edit, 0)
    note = _note(action)
    assert note is not None
    return append_to_log(notebook, note, cap_bytes, insert_bytes)


def apply_splice(
    notebook: Notebook, edit: NotebookEdit, cap_bytes: int, insert_bytes: int
) -> Notebook | NotebookRejection:
    """Return the new notebook, or a rejection code leaving the old one untouched."""
    if edit.expected_revision != notebook.revision:
        return "stale_revision"
    if not edit.start <= edit.end <= len(notebook.text):
        return "invalid_span"
    try:
        inserted = utf8_len(edit.text)
        new_text = notebook.text[: edit.start] + edit.text + notebook.text[edit.end :]
        new_bytes = utf8_len(new_text)
    except UnicodeEncodeError:
        return "invalid_unicode"
    if inserted > insert_bytes:
        return "write_budget_exceeded"
    if new_bytes > cap_bytes:
        return "notebook_cap_exceeded"
    return Notebook.of(notebook.owner, notebook.revision + 1, new_text)


def append_to_log(
    notebook: Notebook, note: str, cap_bytes: int, insert_bytes: int
) -> NotebookUpdate | NotebookRejection:
    """Add the note on a new line, then drop the oldest lines until the notebook fits the cap."""
    if utf8_len(note) > insert_bytes:
        return "write_budget_exceeded"
    separator = "\n" if notebook.text and not notebook.text.endswith("\n") else ""
    end = notebook.codepoints
    edit = NotebookEdit(expected_revision=notebook.revision, start=end, end=end, text=separator + note)
    text = notebook.text + edit.text
    while utf8_len(text) > cap_bytes and "\n" in text:
        text = text.split("\n", 1)[1]
    if utf8_len(text) > cap_bytes:  # only when one note is bigger than the whole cap
        return "notebook_cap_exceeded"
    dropped = end + len(edit.text) - len(text)
    return Notebook.of(notebook.owner, notebook.revision + 1, text), edit, dropped
