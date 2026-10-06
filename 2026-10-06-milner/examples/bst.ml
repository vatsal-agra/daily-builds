(* A polymorphic binary search tree with insertion, deletion, traversal and a balance check. *)

type 'a tree = Leaf | Node of 'a tree * 'a * 'a tree

let rec insert x t =
  match t with
  | Leaf -> Node (Leaf, x, Leaf)
  | Node (l, v, r) ->
    let c = compare x v in
    if c < 0 then Node (insert x l, v, r)
    else if c > 0 then Node (l, v, insert x r)
    else t

let rec min_elt t =
  match t with
  | Leaf -> None
  | Node (Leaf, v, _) -> Some v
  | Node (l, _, _) -> min_elt l

let rec remove x t =
  match t with
  | Leaf -> Leaf
  | Node (l, v, r) ->
    let c = compare x v in
    if c < 0 then Node (remove x l, v, r)
    else if c > 0 then Node (l, v, remove x r)
    else
      (match l, r with
       | Leaf, _ -> r
       | _, Leaf -> l
       | _ -> (match min_elt r with Some m -> Node (l, m, remove m r) | None -> l))

let rec to_list t =
  match t with
  | Leaf -> []
  | Node (l, v, r) -> to_list l @ [v] @ to_list r

let rec height t = match t with Leaf -> 0 | Node (l, _, r) -> 1 + max (height l) (height r)
let rec mem x t =
  match t with
  | Leaf -> false
  | Node (l, v, r) -> let c = compare x v in c = 0 || (if c < 0 then mem x l else mem x r)

let of_list xs = fold_left (fun t x -> insert x t) Leaf xs

let () =
  let t = of_list [50; 30; 70; 20; 40; 60; 80; 30; 65] in
  print_endline ("sorted:   " ^ string_of_list string_of_int (to_list t));
  print_endline ("height:   " ^ string_of_int (height t));
  print_endline ("mem 60/61: " ^ string_of_bool (mem 60 t) ^ "/" ^ string_of_bool (mem 61 t));
  let t2 = remove 50 (remove 20 t) in
  print_endline ("after removing 20 and 50: " ^ string_of_list string_of_int (to_list t2));
  let words = of_list ["pear"; "apple"; "fig"; "banana"; "cherry"] in
  print_endline ("words:    " ^ string_of_list (fun s -> s) (to_list words));
  let degenerate = of_list (range 0 64) in
  print_endline ("sorted input of 64 -> height " ^ string_of_int (height degenerate) ^ " (no rebalancing)")
