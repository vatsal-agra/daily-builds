"""Ground-truth correctness checks for the four demo programs in examples/,
each checked against an independently-known answer -- not just "it produced
something" (the N-Queens solution counts for small N are published; the
Zebra puzzle has exactly one solution)."""

from conftest import consult_example, fails, solutions, succeeds


def test_family_tree(engine):
    consult_example(engine, "family.horn")
    assert succeeds(engine, "father(tom, bob).")
    assert succeeds(engine, "mother(marge, liz).")
    assert fails(engine, "father(marge, bob).")  # marge is female
    assert solutions(engine, "grandparent(marge, X).") == ["X = ann.", "X = pat."]
    assert set(s for s in solutions(engine, "sibling(bob, X).")) == {"X = liz."}
    assert succeeds(engine, "ancestor(tom, jim).")  # tom -> bob -> pat -> jim
    assert fails(engine, "ancestor(jim, tom).")  # not symmetric


def test_queens_6_has_exactly_4_solutions(engine):
    consult_example(engine, "queens.horn")
    sols = solutions(engine, "queens(6, Qs).")
    assert len(sols) == 4  # published count for 6-Queens
    # every returned arrangement must actually be a permutation with no
    # two queens sharing a diagonal -- re-verified independently in Python,
    # not just trusted because the engine said so.
    for s in sols:
        board = eval(s.split("= ", 1)[1].rstrip("."))
        assert sorted(board) == [1, 2, 3, 4, 5, 6]
        for i in range(len(board)):
            for j in range(i + 1, len(board)):
                assert abs(board[i] - board[j]) != j - i


def test_queens_4_has_exactly_2_solutions(engine):
    consult_example(engine, "queens.horn")
    assert len(solutions(engine, "queens(4, Qs).")) == 2


def test_map_coloring_all_solutions_are_actually_valid(engine):
    consult_example(engine, "map_coloring.horn")
    sols = solutions(engine, "australia(WA,NT,SA,Q,NSW,V,T).")
    assert len(sols) == 18  # 6 mainland colorings x 3 free choices for Tasmania
    adjacency = [
        ("WA", "NT"), ("WA", "SA"), ("NT", "SA"), ("NT", "Q"), ("SA", "Q"),
        ("SA", "NSW"), ("SA", "V"), ("Q", "NSW"), ("NSW", "V"),
    ]
    for s in sols:
        assign = dict(
            (kv.split(" = ")[0], kv.split(" = ")[1])
            for kv in s.rstrip(".").split(", ")
        )
        for a, b in adjacency:
            assert assign[a] != assign[b], f"{a} and {b} share a color in {s}"


def test_zebra_puzzle_unique_answer(engine):
    consult_example(engine, "zebra.horn")
    assert solutions(engine, "water_drinker(X).") == ["X = norwegian."]
    assert solutions(engine, "zebra_owner(X).") == ["X = japanese."]
    # Both questions must have a *unique* answer -- the puzzle's whole point.
    assert len(solutions(engine, "houses(H).")) == 1
