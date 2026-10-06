(* Symbolic differentiation and algebraic simplification over an expression ADT. *)

type expr =
  | Num of int
  | Var of string
  | Add of expr * expr
  | Mul of expr * expr
  | Pow of expr * int

let rec simplify e =
  match e with
  | Add (a, b) ->
    (match simplify a, simplify b with
     | Num 0, x | x, Num 0 -> x
     | Num x, Num y -> Num (x + y)
     | x, y -> if x = y then Mul (Num 2, x) else Add (x, y))
  | Mul (a, b) ->
    (match simplify a, simplify b with
     | Num 0, _ | _, Num 0 -> Num 0
     | Num 1, x | x, Num 1 -> x
     | Num x, Num y -> Num (x * y)
     | x, y -> Mul (x, y))
  | Pow (a, n) ->
    (match simplify a, n with
     | _, 0 -> Num 1
     | x, 1 -> x
     | Num x, _ -> let rec p k = if k = 0 then 1 else x * p (k - 1) in Num (p n)
     | x, _ -> Pow (x, n))
  | _ -> e

let rec diff x e =
  match e with
  | Num _ -> Num 0
  | Var y -> if x = y then Num 1 else Num 0
  | Add (a, b) -> Add (diff x a, diff x b)
  | Mul (a, b) -> Add (Mul (diff x a, b), Mul (a, diff x b))
  | Pow (a, n) -> Mul (Mul (Num n, Pow (a, n - 1)), diff x a)

let rec show e =
  match e with
  | Num n -> string_of_int n
  | Var v -> v
  | Add (a, b) -> "(" ^ show a ^ " + " ^ show b ^ ")"
  | Mul (a, b) -> show a ^ " * " ^ show b
  | Pow (a, n) -> show a ^ "^" ^ string_of_int n

let rec eval env e =
  match e with
  | Num n -> n
  | Var v -> (match assoc_opt v env with Some n -> n | None -> failwith ("unbound " ^ v))
  | Add (a, b) -> eval env a + eval env b
  | Mul (a, b) -> eval env a * eval env b
  | Pow (a, n) -> let rec p k = if k = 0 then 1 else eval env a * p (k - 1) in p n

let report name e =
  let d = simplify (diff "x" e) in
  print_endline (name ^ "      = " ^ show e);
  print_endline ("d/dx " ^ name ^ " = " ^ show d);
  print_endline ("at x=3: f = " ^ string_of_int (eval [("x", 3); ("y", 2)] e) ^ ", f' = " ^ string_of_int (eval [("x", 3); ("y", 2)] d))

let () =
  report "f" (Add (Pow (Var "x", 3), Mul (Num 5, Var "x")));
  report "g" (Mul (Var "x", Add (Var "x", Var "y")));
  report "h" (Pow (Add (Var "x", Num 1), 2))
