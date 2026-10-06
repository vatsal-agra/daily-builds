(* Milner prelude: the standard library, written in Milner itself and type-checked at start-up. *)

let id x = x
let const x _ = x
let compose f g x = f (g x)
let flip f a b = f b a
let fst (a, _) = a
let snd (_, b) = b
let not b = if b then false else true
let ignore _ = ()
let succ n = n + 1
let pred n = n - 1
let abs n = if n < 0 then -n else n
let min a b = if a < b then a else b
let max a b = if a > b then a else b

type ('a, 'b) result = Ok of 'a | Error of 'b
type ('a, 'b) either = Left of 'a | Right of 'b

let option_map f o = match o with None -> None | Some x -> Some (f x)
let option_default d o = match o with None -> d | Some x -> x
let option_bind o f = match o with None -> None | Some x -> f x

let rec fold_left f acc xs =
  match xs with
  | [] -> acc
  | x :: rest -> fold_left f (f acc x) rest

let rev xs = fold_left (fun acc x -> x :: acc) [] xs
let rev_append xs ys = fold_left (fun acc x -> x :: acc) ys xs
(* tail-recursive, so it is safe on very long lists *)
let fold_right f xs acc = fold_left (fun a x -> f x a) acc (rev xs)
let rec length_aux n xs = match xs with [] -> n | _ :: t -> length_aux (n + 1) t
let length xs = length_aux 0 xs
let map f xs = rev (fold_left (fun acc x -> f x :: acc) [] xs)
let mapi f xs =
  let rec go i ys = match ys with [] -> [] | y :: t -> f i y :: go (i + 1) t in
  go 0 xs
let filter p xs = rev (fold_left (fun acc x -> if p x then x :: acc else acc) [] xs)
let rec iter f xs = match xs with [] -> () | x :: t -> f x; iter f t
let append a b = a @ b
let concat xss = fold_right (fun xs acc -> xs @ acc) xss []
let concat_map f xs = concat (map f xs)
let rec exists p xs = match xs with [] -> false | x :: t -> p x || exists p t
let rec for_all p xs = match xs with [] -> true | x :: t -> p x && for_all p t
let rec mem x xs = match xs with [] -> false | y :: t -> x = y || mem x t
let rec find_opt p xs = match xs with [] -> None | x :: t -> if p x then Some x else find_opt p t
let rec assoc_opt k xs =
  match xs with
  | [] -> None
  | (k', v) :: t -> if k = k' then Some v else assoc_opt k t
let hd_opt xs = match xs with [] -> None | x :: _ -> Some x
let tl_opt xs = match xs with [] -> None | _ :: t -> Some t
let rec last_opt xs = match xs with [] -> None | [x] -> Some x | _ :: t -> last_opt t
let rec nth_opt xs n =
  match xs with
  | [] -> None
  | x :: t -> if n = 0 then Some x else if n < 0 then None else nth_opt t (n - 1)
let take n xs =
  let rec go n ys acc = match ys with [] -> rev acc | y :: t -> if n <= 0 then rev acc else go (n - 1) t (y :: acc) in
  go n xs []
let rec drop n xs = match xs with [] -> [] | _ :: t as all -> if n <= 0 then all else drop (n - 1) t
let range lo hi =
  let rec go i acc = if i < lo then acc else go (i - 1) (i :: acc) in
  go (hi - 1) []
let replicate n x =
  let rec go i acc = if i <= 0 then acc else go (i - 1) (x :: acc) in
  go n []
let zip xs ys =
  let rec go xs ys acc =
    match xs, ys with
    | x :: xt, y :: yt -> go xt yt ((x, y) :: acc)
    | _ -> rev acc
  in
  go xs ys []
let unzip ps = (map fst ps, map snd ps)
let sum xs = fold_left (fun a b -> a + b) 0 xs
let product xs = fold_left (fun a b -> a * b) 1 xs

let merge cmp xs ys =
  let rec go xs ys acc =
    match xs, ys with
    | [], _ -> rev_append acc ys
    | _, [] -> rev_append acc xs
    | x :: xt, y :: yt -> if cmp x y <= 0 then go xt ys (x :: acc) else go xs yt (y :: acc)
  in
  go xs ys []

let sort cmp xs =
  let rec split l a b = match l with [] -> (a, b) | x :: t -> split t b (x :: a) in
  let rec go l =
    match l with
    | [] -> []
    | [x] -> [x]
    | _ ->
      let (a, b) = split l [] [] in
      merge cmp (go a) (go b)
  in
  go xs

let join sep xs =
  match xs with
  | [] -> ""
  | first :: rest -> fold_left (fun acc x -> acc ^ sep ^ x) first rest

let string_of_bool b = if b then "true" else "false"
let rec string_of_list f xs = "[" ^ join "; " (map f xs) ^ "]"
