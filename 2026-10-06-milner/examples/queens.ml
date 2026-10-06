(* N-queens: count solutions by building placements row by row.
   A placement is the list of column numbers chosen so far (most recent row first). *)

let rec safe col dist placed =
  match placed with
  | [] -> true
  | c :: rest ->
    c <> col && c <> col + dist && c <> col - dist && safe col (dist + 1) rest

let queens n =
  let rec place row placed =
    if row = n then [placed]
    else
      concat_map
        (fun col -> if safe col 1 placed then place (row + 1) (col :: placed) else [])
        (range 0 n)
  in
  place 0 []

let show_board n placement =
  let row col = join "" (map (fun c -> if c = col then "Q" else ".") (range 0 n)) in
  join "\n" (map row (rev placement))

let () =
  iter (fun n -> print_endline ("n=" ^ string_of_int n ^ ": " ^ string_of_int (length (queens n)) ^ " solutions"))
    [4; 5; 6; 7; 8];
  print_endline "first 6-queens solution:";
  match queens 6 with
  | first :: _ -> print_endline (show_board 6 first)
  | [] -> print_endline "none"
