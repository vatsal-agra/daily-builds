(* Compile arithmetic expressions to a stack machine and check the machine agrees with direct evaluation. *)

type expr = Lit of int | Neg of expr | Bin of char_op * expr * expr
and char_op = Plus | Minus | Times | Divide

type instr = Push of int | Negate | Apply of char_op

let rec compile e =
  match e with
  | Lit n -> [Push n]
  | Neg a -> compile a @ [Negate]
  | Bin (op, a, b) -> compile a @ compile b @ [Apply op]

let apply op a b =
  match op with
  | Plus -> a + b
  | Minus -> a - b
  | Times -> a * b
  | Divide -> a / b

(* run a program against a stack; a malformed program yields Error *)
let rec run prog stack =
  match prog, stack with
  | [], [x] -> Ok x
  | [], _ -> Error "stack should hold exactly one value at the end"
  | Push n :: rest, _ -> run rest (n :: stack)
  | Negate :: rest, x :: s -> run rest (-x :: s)
  | Apply op :: rest, b :: a :: s -> run rest (apply op a b :: s)
  | _ -> Error "stack underflow"

let rec direct e =
  match e with
  | Lit n -> n
  | Neg a -> - (direct a)
  | Bin (op, a, b) -> apply op (direct a) (direct b)

let op_name op = match op with Plus -> "+" | Minus -> "-" | Times -> "*" | Divide -> "/"
let instr_name i =
  match i with
  | Push n -> "push " ^ string_of_int n
  | Negate -> "neg"
  | Apply op -> "apply " ^ op_name op

let () =
  let e = Bin (Times, Bin (Plus, Lit 2, Lit 3), Neg (Bin (Minus, Lit 10, Bin (Divide, Lit 8, Lit 2)))) in
  let prog = compile e in
  print_endline (join "; " (map instr_name prog));
  (match run prog [] with
   | Ok v -> print_endline ("machine: " ^ string_of_int v ^ "   direct: " ^ string_of_int (direct e))
   | Error m -> print_endline ("error: " ^ m));
  (match run [Apply Plus] [] with Ok _ -> () | Error m -> print_endline ("bad program -> " ^ m));
  (match run [Push 1; Push 2] [] with Ok _ -> () | Error m -> print_endline ("bad program -> " ^ m))
