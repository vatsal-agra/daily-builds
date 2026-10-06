(* Mutable state with refs and closures: counters, a bank account and a two-list functional queue. *)

let make_counter start =
  let n = ref start in
  (fun () -> n := !n + 1; !n)

type account = { owner : string; balance : int ref; history : string list ref }

let open_account owner deposit =
  { owner; balance = ref deposit; history = ref ["open:" ^ string_of_int deposit] }

let withdraw acct amount =
  if amount > !(acct.balance) then Error ("insufficient funds for " ^ acct.owner)
  else begin
    acct.balance := !(acct.balance) - amount;
    acct.history := ("withdraw:" ^ string_of_int amount) :: !(acct.history);
    Ok !(acct.balance)
  end

(* a queue as a pair of lists: amortised O(1) push/pop *)
type 'a queue = Queue of 'a list * 'a list

let empty = Queue ([], [])
let push x (Queue (front, back)) = Queue (front, x :: back)
let pop q =
  match q with
  | Queue ([], []) -> None
  | Queue ([], back) -> (match rev back with x :: front -> Some (x, Queue (front, [])) | [] -> None)
  | Queue (x :: front, back) -> Some (x, Queue (front, back))

let rec drain q =
  match pop q with
  | None -> []
  | Some (x, q') -> x :: drain q'

let () =
  let next = make_counter 10 in
  let a = next () in
  let b = next () in
  let c = next () in
  print_endline ("counter: " ^ string_of_list string_of_int [a; b; c]);
  let acct = open_account "ada" 100 in
  (match withdraw acct 30 with Ok b -> print_endline ("balance " ^ string_of_int b) | Error e -> print_endline e);
  (match withdraw acct 100 with Ok b -> print_endline ("balance " ^ string_of_int b) | Error e -> print_endline e);
  print_endline ("history: " ^ join ", " (rev !(acct.history)));
  let q = fold_left (fun q x -> push x q) empty [1; 2; 3] in
  let (first, q') = (match pop q with Some p -> p | None -> failwith "empty") in
  let q'' = push 4 q' in
  print_endline ("queue: first=" ^ string_of_int first ^ " rest=" ^ string_of_list string_of_int (drain q''))
