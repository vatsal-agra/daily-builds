(* Hindley-Milner type inference for a tiny lambda calculus, written *in* Milner.
   Substitutions are association lists; types and terms are ADTs. *)

type ty = TInt | TBool | TVar of int | TFun of ty * ty

type term =
  | Int of int
  | Bool of bool
  | V of string
  | Lam of string * term
  | App of term * term
  | If of term * term * term
  | Let of string * term * term

type scheme = Forall of int list * ty

let rec apply_subst s t =
  match t with
  | TVar n -> (match assoc_opt n s with Some t' -> apply_subst s t' | None -> t)
  | TFun (a, b) -> TFun (apply_subst s a, apply_subst s b)
  | _ -> t

let rec occurs n t =
  match t with
  | TVar m -> n = m
  | TFun (a, b) -> occurs n a || occurs n b
  | _ -> false

let rec unify s a b =
  match apply_subst s a, apply_subst s b with
  | TInt, TInt -> Ok s
  | TBool, TBool -> Ok s
  | TVar n, TVar m when n = m -> Ok s
  | TVar n, t | t, TVar n -> if occurs n t then Error "infinite type" else Ok ((n, t) :: s)
  | TFun (a1, b1), TFun (a2, b2) ->
    (match unify s a1 a2 with Ok s' -> unify s' b1 b2 | Error e -> Error e)
  | _ -> Error "type mismatch"

let rec ftv t =
  match t with
  | TVar n -> [n]
  | TFun (a, b) -> ftv a @ ftv b
  | _ -> []

let rec dedupe xs = match xs with [] -> [] | x :: r -> x :: dedupe (filter (fun y -> y <> x) r)

(* the inference state is (substitution, next fresh variable) *)
let fresh next = (TVar next, next + 1)

let instantiate (Forall (vars, t)) next =
  let (mapping, next') =
    fold_left (fun (m, n) v -> ((v, TVar n) :: m, n + 1)) ([], next) vars in
  (apply_subst mapping t, next')

let rec infer env s next term =
  match term with
  | Int _ -> Ok (TInt, s, next)
  | Bool _ -> Ok (TBool, s, next)
  | V x ->
    (match assoc_opt x env with
     | None -> Error ("unbound variable " ^ x)
     | Some sc -> let (t, next') = instantiate sc next in Ok (t, s, next'))
  | Lam (x, body) ->
    let (a, next1) = fresh next in
    (match infer ((x, Forall ([], a)) :: env) s next1 body with
     | Ok (tb, s', next2) -> Ok (TFun (a, tb), s', next2)
     | Error e -> Error e)
  | App (f, arg) ->
    (match infer env s next f with
     | Error e -> Error e
     | Ok (tf, s1, next1) ->
       (match infer env s1 next1 arg with
        | Error e -> Error e
        | Ok (ta, s2, next2) ->
          let (r, next3) = fresh next2 in
          (match unify s2 tf (TFun (ta, r)) with
           | Ok s3 -> Ok (r, s3, next3)
           | Error e -> Error e)))
  | If (c, t, e) ->
    (match infer env s next c with
     | Error m -> Error m
     | Ok (tc, s1, n1) ->
       (match unify s1 tc TBool with
        | Error m -> Error m
        | Ok s2 ->
          (match infer env s2 n1 t with
           | Error m -> Error m
           | Ok (tt, s3, n2) ->
             (match infer env s3 n2 e with
              | Error m -> Error m
              | Ok (te, s4, n3) ->
                (match unify s4 tt te with
                 | Ok s5 -> Ok (tt, s5, n3)
                 | Error m -> Error m)))))
  | Let (x, e1, e2) ->
    (match infer env s next e1 with
     | Error m -> Error m
     | Ok (t1, s1, n1) ->
       let t1' = apply_subst s1 t1 in
       let env_vars = concat_map (fun (_, Forall (_, t)) -> ftv (apply_subst s1 t)) env in
       let gen = filter (fun v -> not (mem v env_vars)) (dedupe (ftv t1')) in
       infer ((x, Forall (gen, t1')) :: env) s1 n1 e2)

(* name type variables a, b, c ... in order of appearance *)
let show_type t =
  let vars = dedupe (ftv t) in
  let name n =
    let rec idx i l = match l with [] -> 0 | x :: r -> if x = n then i else idx (i + 1) r in
    char_of_code (97 + idx 0 vars) in
  let rec go prec t =
    match t with
    | TInt -> "int"
    | TBool -> "bool"
    | TVar n -> "'" ^ name n
    | TFun (a, b) ->
      let s = go 1 a ^ " -> " ^ go 0 b in
      if prec > 0 then "(" ^ s ^ ")" else s
  in
  go 0 t

let type_of term =
  match infer [] [] 0 term with
  | Ok (t, s, _) -> show_type (apply_subst s t)
  | Error e -> "error: " ^ e

let () =
  let id = Lam ("x", V "x") in
  let tests = [
    ("fun x -> x", id);
    ("fun f -> fun x -> f (f x)", Lam ("f", Lam ("x", App (V "f", App (V "f", V "x")))));
    ("fun f -> fun g -> fun x -> f (g x)", Lam ("f", Lam ("g", Lam ("x", App (V "f", App (V "g", V "x"))))));
    ("if true then 1 else 2", If (Bool true, Int 1, Int 2));
    ("let id = fun x -> x in if id true then id 1 else 0", Let ("id", id, If (App (V "id", Bool true), App (V "id", Int 1), Int 0)));
    ("fun x -> x x", Lam ("x", App (V "x", V "x")));
    ("if 1 then 2 else 3", If (Int 1, Int 2, Int 3));
    ("(fun x -> x + y)", Lam ("x", V "y"));
  ] in
  iter (fun (src, t) -> print_endline (src ^ "\n    : " ^ type_of t)) tests
