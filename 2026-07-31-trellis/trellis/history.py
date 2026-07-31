"""Undo/redo as a command stack over cell edits. Each entry records enough
to restore the *previous raw content* of the edited cell; undoing replays
that through `Workbook.set_cell`, so the full downstream recalculation
(every dependent cell, error states included) is restored exactly the way
it would be from a fresh edit -- not just the one cell's raw text."""


class _Edit:
    __slots__ = ("sheet", "row", "col", "before", "after")

    def __init__(self, sheet, row, col, before, after):
        self.sheet = sheet
        self.row = row
        self.col = col
        self.before = before
        self.after = after


class History:
    def __init__(self, workbook, limit=500):
        self.wb = workbook
        self.undo_stack = []
        self.redo_stack = []
        self.limit = limit
        self.last_changed = set()

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.last_changed = set()

    def set_cell(self, sheet_name, row, col, raw_text):
        cell = self.wb.sheets[sheet_name].get(row, col)
        before = cell.raw if cell is not None else None
        changed = self.wb.set_cell(sheet_name, row, col, raw_text)
        self.last_changed = changed
        self.undo_stack.append(_Edit(sheet_name, row, col, before, raw_text))
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        return changed

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack:
            return None
        edit = self.undo_stack.pop()
        changed = self.wb.set_cell(edit.sheet, edit.row, edit.col, edit.before)
        self.redo_stack.append(edit)
        self.last_changed = changed
        return changed

    def redo(self):
        if not self.redo_stack:
            return None
        edit = self.redo_stack.pop()
        changed = self.wb.set_cell(edit.sheet, edit.row, edit.col, edit.after)
        self.undo_stack.append(edit)
        self.last_changed = changed
        return changed
