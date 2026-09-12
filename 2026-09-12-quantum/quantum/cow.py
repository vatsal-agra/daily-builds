"""Copy-on-write (CoW) `fork()`, from scratch.

The real trick real operating systems use to make `fork()` cheap: instead
of copying a child's entire address space up front, the child's page table
is set up to point at the *exact same physical frames* as the parent, with
every shared frame's reference count bumped. Both processes can read
those frames all day for free. Only the instant one side tries to *write*
to a still-shared frame does the kernel step in, allocate a fresh frame,
copy the data into it, and repoint that one page-table entry — so the
copy that "should have happened at fork time" actually happens lazily,
page by page, only for the pages that turn out to matter.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AddressSpace:
    """One process's page table: virtual page -> physical frame id."""

    pid: int
    page_table: dict[int, int] = field(default_factory=dict)

    def clone_table(self) -> dict[int, int]:
        return dict(self.page_table)


class COWMemory:
    """A shared physical frame pool with reference counting, backing any
    number of `AddressSpace`s connected by `fork()`."""

    def __init__(self) -> None:
        self._next_frame = 0
        self.refcount: dict[int, int] = {}
        self.content: dict[int, object] = {}
        self.copies_made = 0
        self.frames_freed = 0

    def _alloc_frame(self, value: object) -> int:
        frame = self._next_frame
        self._next_frame += 1
        self.refcount[frame] = 1
        self.content[frame] = value
        return frame

    def new_process(self, pid: int) -> AddressSpace:
        return AddressSpace(pid=pid)

    def map_page(self, space: AddressSpace, vpage: int, value: object) -> int:
        """Allocate a brand-new, exclusively-owned page (as if the process
        just touched fresh memory — the initial malloc/heap-growth case,
        not a fork)."""
        if vpage in space.page_table:
            raise ValueError(f"pid {space.pid} already has vpage {vpage} mapped")
        frame = self._alloc_frame(value)
        space.page_table[vpage] = frame
        return frame

    def fork(self, parent: AddressSpace, child_pid: int) -> AddressSpace:
        """Classic CoW fork: the child's page table starts as an exact
        copy of the parent's *mapping* — every entry pointing at the same
        physical frame the parent uses — and every one of those frames'
        refcount goes up by one. No page content is copied here."""
        child = AddressSpace(pid=child_pid, page_table=parent.clone_table())
        for frame in child.page_table.values():
            self.refcount[frame] += 1
        return child

    def read(self, space: AddressSpace, vpage: int) -> object:
        frame = self._frame_of(space, vpage)
        return self.content[frame]

    def write(self, space: AddressSpace, vpage: int, value: object) -> int:
        """Write to a page. If its frame is still shared (refcount > 1),
        this triggers a real copy: a fresh frame is allocated for this
        writer alone, the writer's page table is repointed to it, and the
        old frame's refcount drops by one (everyone else keeps sharing
        it). If the frame is already exclusively owned, the write just
        happens in place — no copy, exactly like a real kernel skips the
        fault once nobody else can see the page."""
        frame = self._frame_of(space, vpage)
        if self.refcount[frame] > 1:
            new_frame = self._alloc_frame(value)
            self.refcount[frame] -= 1
            space.page_table[vpage] = new_frame
            self.copies_made += 1
            return new_frame
        self.content[frame] = value
        return frame

    def exit_process(self, space: AddressSpace) -> None:
        """Drop every page this process holds, freeing any frame whose
        refcount reaches zero (i.e. nobody else — no sibling, no
        surviving parent — still shares it)."""
        for vpage in list(space.page_table):
            self._unmap(space, vpage)

    def frame_of(self, space: AddressSpace, vpage: int) -> int:
        return self._frame_of(space, vpage)

    def refcount_of(self, space: AddressSpace, vpage: int) -> int:
        return self.refcount[self._frame_of(space, vpage)]

    def _frame_of(self, space: AddressSpace, vpage: int) -> int:
        if vpage not in space.page_table:
            raise ValueError(f"pid {space.pid} has no mapping for vpage {vpage} (segfault)")
        return space.page_table[vpage]

    def _unmap(self, space: AddressSpace, vpage: int) -> None:
        frame = space.page_table.pop(vpage)
        self.refcount[frame] -= 1
        if self.refcount[frame] < 0:
            raise RuntimeError(f"frame {frame} refcount went negative — bookkeeping bug")
        if self.refcount[frame] == 0:
            del self.refcount[frame]
            del self.content[frame]
            self.frames_freed += 1
