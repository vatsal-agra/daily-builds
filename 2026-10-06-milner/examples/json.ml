(* A JSON parser and pretty-printer: recursive descent over a list of characters, with errors as values. *)

type json =
  | Null
  | Bool of bool
  | Number of int
  | Str of string
  | List of json list
  | Obj of (string * json) list

let is_digit c = let n = char_code c in n >= 48 && n <= 57
let is_space c = c = " " || c = "\n" || c = "\t"

let rec skip_ws cs = match cs with c :: rest when is_space c -> skip_ws rest | _ -> cs

(* every parser returns Ok (value, remaining input) or Error message *)
let rec parse_value cs =
  match skip_ws cs with
  | "n" :: "u" :: "l" :: "l" :: rest -> Ok (Null, rest)
  | "t" :: "r" :: "u" :: "e" :: rest -> Ok (Bool true, rest)
  | "f" :: "a" :: "l" :: "s" :: "e" :: rest -> Ok (Bool false, rest)
  | "\"" :: rest -> (match parse_string rest [] with Ok (s, r) -> Ok (Str s, r) | Error e -> Error e)
  | "[" :: rest -> parse_list (skip_ws rest) []
  | "{" :: rest -> parse_obj (skip_ws rest) []
  | "-" :: rest -> (match parse_number rest 0 false with Ok (n, r) -> Ok (Number (-n), r) | Error e -> Error e)
  | c :: _ as all when is_digit c ->
    (match parse_number all 0 false with Ok (n, r) -> Ok (Number n, r) | Error e -> Error e)
  | c :: _ -> Error ("unexpected character " ^ c)
  | [] -> Error "unexpected end of input"

and parse_number cs acc seen =
  match cs with
  | c :: rest when is_digit c -> parse_number rest (acc * 10 + char_code c - 48) true
  | _ -> if seen then Ok (acc, cs) else Error "expected digits"

and parse_string cs acc =
  match cs with
  | "\"" :: rest -> Ok (join "" (rev acc), rest)
  | "\\" :: "n" :: rest -> parse_string rest ("\n" :: acc)
  | "\\" :: "\"" :: rest -> parse_string rest ("\"" :: acc)
  | "\\" :: "\\" :: rest -> parse_string rest ("\\" :: acc)
  | c :: rest -> parse_string rest (c :: acc)
  | [] -> Error "unterminated string"

and parse_list cs acc =
  match cs with
  | "]" :: rest -> Ok (List (rev acc), rest)
  | _ ->
    (match parse_value cs with
     | Error e -> Error e
     | Ok (v, rest) ->
       (match skip_ws rest with
        | "," :: rest' -> parse_list (skip_ws rest') (v :: acc)
        | "]" :: rest' -> Ok (List (rev (v :: acc)), rest')
        | _ -> Error "expected , or ] in list"))

and parse_obj cs acc =
  match cs with
  | "}" :: rest -> Ok (Obj (rev acc), rest)
  | "\"" :: rest ->
    (match parse_string rest [] with
     | Error e -> Error e
     | Ok (key, rest1) ->
       (match skip_ws rest1 with
        | ":" :: rest2 ->
          (match parse_value rest2 with
           | Error e -> Error e
           | Ok (v, rest3) ->
             (match skip_ws rest3 with
              | "," :: rest4 -> parse_obj (skip_ws rest4) ((key, v) :: acc)
              | "}" :: rest4 -> Ok (Obj (rev ((key, v) :: acc)), rest4)
              | _ -> Error "expected , or } in object"))
        | _ -> Error ("expected : after key " ^ key)))
  | _ -> Error "expected a string key"

let parse s =
  match parse_value (string_explode s) with
  | Error e -> Error e
  | Ok (v, rest) -> (match skip_ws rest with [] -> Ok v | c :: _ -> Error ("trailing input at " ^ c))

let rec to_string j =
  match j with
  | Null -> "null"
  | Bool b -> string_of_bool b
  | Number n -> string_of_int n
  | Str s -> "\"" ^ s ^ "\""
  | List xs -> "[" ^ join "," (map to_string xs) ^ "]"
  | Obj kvs -> "{" ^ join "," (map (fun (k, v) -> "\"" ^ k ^ "\":" ^ to_string v) kvs) ^ "}"

let rec depth j =
  match j with
  | List xs -> 1 + fold_left (fun m x -> max m (depth x)) 0 xs
  | Obj kvs -> 1 + fold_left (fun m (_, v) -> max m (depth v)) 0 kvs
  | _ -> 0

(* follow a path of keys through nested objects *)
let rec get path j =
  match path, j with
  | [], _ -> Some j
  | k :: rest, Obj kvs -> (match assoc_opt k kvs with Some v -> get rest v | None -> None)
  | _ -> None

let rec sum_numbers j =
  match j with
  | Number n -> n
  | List xs -> sum (map sum_numbers xs)
  | Obj kvs -> sum (map (fun (_, v) -> sum_numbers v) kvs)
  | _ -> 0

let () =
  let doc = "{ \"name\": \"milner\", \"tags\": [\"ml\", \"types\"], \"stats\": { \"files\": 12, \"deps\": 0, \"ok\": true }, \"neg\": -5, \"none\": null }" in
  (match parse doc with
   | Error e -> print_endline ("parse error: " ^ e)
   | Ok j ->
     print_endline (to_string j);
     print_endline ("depth: " ^ string_of_int (depth j));
     print_endline ("sum of numbers: " ^ string_of_int (sum_numbers j));
     (match get ["stats"; "files"] j with
      | Some (Number n) -> print_endline ("stats.files = " ^ string_of_int n)
      | _ -> print_endline "stats.files missing");
     (match get ["stats"; "nope"] j with None -> print_endline "stats.nope: not found" | Some _ -> ()));
  iter (fun bad -> match parse bad with
    | Ok _ -> print_endline ("unexpectedly parsed: " ^ bad)
    | Error e -> print_endline (bad ^ "  =>  " ^ e))
    ["[1, 2"; "{\"a\" 1}"; "tru"; "\"open"; "[1] x"; "{1: 2}"]
