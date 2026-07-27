"""A small standard library, written in Unify itself and loaded at REPL
startup -- proof the inference engine handles real, nontrivial,
polymorphic, list-recursive code, not just the toy examples in tests/.

Each entry is exactly what a user could type at the REPL prompt themselves:
a top-level `let [rec] name = value` binding with no `in`.
"""

PRELUDE = [
    ("map", "let rec map f l = match l with | [] -> [] | h :: t -> f h :: map f t"),
    (
        "filter",
        "let rec filter pred l = match l with "
        "| [] -> [] "
        "| h :: t -> if pred h then h :: filter pred t else filter pred t",
    ),
    (
        "foldl",
        "let rec foldl f acc l = match l with | [] -> acc | h :: t -> foldl f (f acc h) t",
    ),
    ("length", "let rec length l = match l with | [] -> 0 | _ :: t -> 1 + length t"),
    ("append", "let rec append a b = match a with | [] -> b | h :: t -> h :: append t b"),
    ("reverse", "let rec reverse l = foldl (fun acc h -> h :: acc) [] l"),
    (
        "assoc",
        "let rec assoc key l = match l with "
        "| [] -> None "
        "| (k, v) :: rest -> if k = key then Some v else assoc key rest",
    ),
]
