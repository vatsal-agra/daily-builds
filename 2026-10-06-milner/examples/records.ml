(* Row-polymorphic records: functions work on any record that has the fields they touch. *)

let full_name p = p.first ^ " " ^ p.last
let birthday p = { p with age = p.age + 1 }
let describe { name; age; .. } = name ^ " (" ^ string_of_int age ^ ")"

let people = [
  { first = "Ada"; last = "Lovelace"; name = "ada"; age = 36 };
  { first = "Alan"; last = "Turing"; name = "alan"; age = 41 };
]

(* a different record shape works with the same function *)
let robot = { first = "R2"; last = "D2"; model = 2 }

let oldest ps =
  fold_left (fun best p -> match best with None -> Some p | Some b -> if p.age > b.age then Some p else best) None ps

let hd_default xs = match xs with x :: _ -> x | [] -> failwith "empty"

let () =
  iter (fun p -> print_endline (full_name p ^ " / " ^ describe p)) people;
  print_endline (full_name robot);
  print_endline (describe (birthday (hd_default people)));
  (match oldest people with
   | Some p -> print_endline ("oldest: " ^ p.name)
   | None -> print_endline "nobody")
