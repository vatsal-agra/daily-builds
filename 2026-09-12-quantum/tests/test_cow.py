import pytest

from quantum.cow import COWMemory


def _make_parent(mem, pages=("A", "B", "C")):
    parent = mem.new_process(pid=1)
    for vp, val in enumerate(pages):
        mem.map_page(parent, vp, val)
    return parent


class TestForkSharesFrames:
    def test_child_shares_every_frame_with_parent(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        for vp in range(3):
            assert mem.frame_of(parent, vp) == mem.frame_of(child, vp)
            assert mem.refcount_of(parent, vp) == 2

    def test_child_sees_parents_data_immediately(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        assert [mem.read(child, vp) for vp in range(3)] == ["A", "B", "C"]

    def test_grandchild_triples_the_refcount(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        grandchild = mem.fork(child, child_pid=3)
        assert mem.refcount_of(parent, 0) == 3
        assert mem.frame_of(parent, 0) == mem.frame_of(child, 0) == mem.frame_of(grandchild, 0)


class TestWriteTriggersRealCopy:
    def test_write_by_child_diverges_only_that_page(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)

        mem.write(child, 0, "child-edit")

        assert mem.frame_of(parent, 0) != mem.frame_of(child, 0)
        assert mem.read(parent, 0) == "A"          # parent unaffected
        assert mem.read(child, 0) == "child-edit"  # child sees its own edit
        # every other page is untouched and still shared
        for vp in (1, 2):
            assert mem.frame_of(parent, vp) == mem.frame_of(child, vp)
            assert mem.refcount_of(parent, vp) == 2

    def test_copy_count_is_exactly_one_per_diverging_write(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        assert mem.copies_made == 0
        mem.write(child, 0, "x")
        assert mem.copies_made == 1
        mem.write(child, 1, "y")
        assert mem.copies_made == 2
        # writing vpage 0 again from the same (now-exclusive) child: no new copy
        mem.write(child, 0, "x2")
        assert mem.copies_made == 2

    def test_write_to_already_exclusive_page_never_copies(self):
        mem = COWMemory()
        parent = mem.new_process(pid=1)
        mem.map_page(parent, 0, "solo")  # never forked -- refcount 1 from the start
        assert mem.refcount_of(parent, 0) == 1
        mem.write(parent, 0, "solo-edit")
        assert mem.copies_made == 0
        assert mem.read(parent, 0) == "solo-edit"

    def test_after_both_sides_write_the_shared_frame_is_fully_released(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        original_frame = mem.frame_of(parent, 0)
        mem.write(child, 0, "child-edit")   # child copies away; original frame refcount -> 1
        assert mem.refcount[original_frame] == 1
        mem.write(parent, 0, "parent-edit")  # parent is now the sole owner: in-place, no copy
        assert mem.copies_made == 1
        assert mem.frame_of(parent, 0) == original_frame
        assert mem.read(parent, 0) == "parent-edit"


class TestExitFreesFrames:
    def test_exit_of_one_sibling_does_not_free_a_still_shared_frame(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        mem.exit_process(child)
        assert mem.frames_freed == 0
        for vp in range(3):
            assert mem.refcount_of(parent, vp) == 1

    def test_exit_of_last_holder_frees_the_frame(self):
        mem = COWMemory()
        parent = _make_parent(mem)
        child = mem.fork(parent, child_pid=2)
        mem.exit_process(child)
        mem.exit_process(parent)
        assert mem.frames_freed == 3
        assert mem.refcount == {}
        assert mem.content == {}

    def test_refcount_never_goes_negative(self):
        mem = COWMemory()
        parent = _make_parent(mem, pages=("A",))
        child = mem.fork(parent, child_pid=2)
        mem.exit_process(parent)
        mem.exit_process(child)  # second exit must not double-free / go negative
        assert mem.frames_freed == 1
        assert all(v >= 0 for v in mem.refcount.values())


class TestErrorHandling:
    def test_reading_unmapped_page_raises_like_a_segfault(self):
        mem = COWMemory()
        parent = mem.new_process(pid=1)
        with pytest.raises(ValueError):
            mem.read(parent, 99)

    def test_double_mapping_same_vpage_rejected(self):
        mem = COWMemory()
        parent = mem.new_process(pid=1)
        mem.map_page(parent, 0, "A")
        with pytest.raises(ValueError):
            mem.map_page(parent, 0, "B")
