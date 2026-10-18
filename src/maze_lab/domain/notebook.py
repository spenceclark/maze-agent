"""Notebook splice rules (spec §5.4)."""

from typing import Literal

from maze_lab.agent_contracts import (
    Notebook,
    NotebookEdit,
    NotebookRejection,
    SimpleTurnAction,
    TurnAction,
    utf8_len,
)


def _given(text: str | None) -> str | None:
    """Blank text or the string "null" means no change: small models send these where they mean null."""
    if text is None or not text.strip() or text.strip().lower() == "null":
        return None
    return text


def requested_edit(
    action: TurnAction | SimpleTurnAction, notebook: Notebook
) -> NotebookEdit | Literal["conflicting_notebook_ops"] | None:
    """The splice an action asks for. Append and rewrite are placed against the current notebook,
    so the usual budget and cap checks in `apply_splice` still apply."""
    if isinstance(action, TurnAction):
        return action.notebook_edit
    append, rewrite = _given(action.notebook_append), _given(action.notebook_rewrite)
    if append is not None and rewrite is not None:
        return "conflicting_notebook_ops"
    end = notebook.codepoints
    if append is not None:
        return NotebookEdit(expected_revision=notebook.revision, start=end, end=end, text=append)
    if rewrite is not None:
        return NotebookEdit(expected_revision=notebook.revision, start=0, end=end, text=rewrite)
    return None


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
