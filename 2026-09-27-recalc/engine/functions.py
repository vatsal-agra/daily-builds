"""Built-in function library. Each function receives the list of already-
evaluated argument values exactly as they appeared in the call (scalars
for direct arguments, 2D row-lists for range arguments) and returns a
runtime Value.

Two collection helpers set the Excel-authentic rule used throughout:
aggregate functions (SUM, AVERAGE, MIN, MAX, COUNT...) *ignore* text and
blanks when they arrive via a range, but *error* on non-numeric text
passed directly as a scalar argument — `SUM(A1:A10)` silently skips a
text cell in the range, but `SUM("abc")` is `#VALUE!`.
"""

import math

from . import values as V


def _numeric_from_ranges_or_error_scalars(args):
    """Yield numeric floats found in range args (ignoring text/blank/bool
    silently), while scalar args must coerce to a number or the whole
    function call errors. Returns (numbers, error_or_None)."""
    numbers = []
    for a in args:
        if isinstance(a, list):
            for v in V.flatten([a]):
                if V.is_error(v):
                    return None, v
                if isinstance(v, float):
                    numbers.append(v)
                # text / bool / blank inside a range: silently ignored
        else:
            if V.is_error(a):
                return None, a
            n = V.to_number(a)
            if V.is_error(n):
                return None, n
            numbers.append(n)
    return numbers, None


def fn_sum(args):
    numbers, err = _numeric_from_ranges_or_error_scalars(args)
    if err is not None:
        return err
    return float(sum(numbers))


def fn_average(args):
    numbers, err = _numeric_from_ranges_or_error_scalars(args)
    if err is not None:
        return err
    if not numbers:
        return V.DIV0
    return sum(numbers) / len(numbers)


def fn_min(args):
    numbers, err = _numeric_from_ranges_or_error_scalars(args)
    if err is not None:
        return err
    return min(numbers) if numbers else 0.0


def fn_max(args):
    numbers, err = _numeric_from_ranges_or_error_scalars(args)
    if err is not None:
        return err
    return max(numbers) if numbers else 0.0


def fn_count(args):
    """Counts numeric values only, from ranges and direct arguments alike
    (unlike SUM, COUNT never errors on a non-numeric direct argument — it
    simply doesn't count it, matching Excel's actual COUNT semantics)."""
    n = 0
    for a in args:
        if isinstance(a, list):
            for v in V.flatten([a]):
                if isinstance(v, float):
                    n += 1
        else:
            if isinstance(a, float):
                n += 1
    return float(n)


def fn_counta(args):
    n = 0
    for a in args:
        if isinstance(a, list):
            for v in V.flatten([a]):
                if v is not None:
                    n += 1
        else:
            if a is not None:
                n += 1
    return float(n)


def _criteria_match(cell_value, criteria):
    """Excel COUNTIF/SUMIF criteria: a bare number/text -> equality
    (case-insensitive for text); a string beginning with a comparison
    operator -> that comparison against the remainder, numeric if the
    remainder parses as a number, else text comparison."""
    if isinstance(criteria, float):
        return isinstance(cell_value, float) and cell_value == criteria
    if isinstance(criteria, bool):
        return isinstance(cell_value, bool) and cell_value == criteria
    text = criteria if isinstance(criteria, str) else V.to_text(criteria)
    for op in (">=", "<=", "<>", ">", "<", "="):
        if text.startswith(op):
            rhs = text[len(op):]
            try:
                rhs_num = float(rhs)
                lhs_num = cell_value if isinstance(cell_value, float) else None
                if lhs_num is None:
                    return op == "<>"
                return {
                    ">=": lhs_num >= rhs_num, "<=": lhs_num <= rhs_num,
                    "<>": lhs_num != rhs_num, ">": lhs_num > rhs_num,
                    "<": lhs_num < rhs_num, "=": lhs_num == rhs_num,
                }[op]
            except ValueError:
                lhs_text = cell_value.upper() if isinstance(cell_value, str) else None
                if lhs_text is None:
                    return op == "<>"
                rhs_up = rhs.upper()
                return {
                    ">=": lhs_text >= rhs_up, "<=": lhs_text <= rhs_up,
                    "<>": lhs_text != rhs_up, ">": lhs_text > rhs_up,
                    "<": lhs_text < rhs_up, "=": lhs_text == rhs_up,
                }[op]
    # bare equality
    if isinstance(cell_value, str):
        return cell_value.upper() == text.upper()
    if isinstance(cell_value, float):
        try:
            return cell_value == float(text)
        except ValueError:
            return False
    return False


def fn_countif(args):
    if len(args) != 2:
        return V.VALUE
    rng, criteria = args
    if not isinstance(rng, list):
        rng = [[rng]]
    if isinstance(criteria, list):
        flat = V.flatten([criteria])
        criteria = flat[0] if flat else None
    if V.is_error(criteria):
        return criteria
    n = 0
    for row in rng:
        for v in row:
            if V.is_error(v):
                return v
            if _criteria_match(v, criteria):
                n += 1
    return float(n)


def fn_sumif(args):
    if len(args) not in (2, 3):
        return V.VALUE
    rng = args[0]
    criteria = args[1]
    sum_rng = args[2] if len(args) == 3 else rng
    if not isinstance(rng, list):
        rng = [[rng]]
    if not isinstance(sum_rng, list):
        sum_rng = [[sum_rng]]
    if isinstance(criteria, list):
        flat = V.flatten([criteria])
        criteria = flat[0] if flat else None
    if V.is_error(criteria):
        return criteria
    flat_rng = V.flatten([rng])
    flat_sum = V.flatten([sum_rng])
    if len(flat_rng) != len(flat_sum):
        return V.VALUE
    total = 0.0
    for v, s in zip(flat_rng, flat_sum):
        if V.is_error(v):
            return v
        if V.is_error(s):
            return s
        if _criteria_match(v, criteria):
            n = V.to_number(s)
            if V.is_error(n):
                return n
            total += n
    return total


def fn_if(args):
    if len(args) < 2 or len(args) > 3:
        return V.VALUE
    cond = args[0]
    if isinstance(cond, list):
        flat = V.flatten([cond])
        cond = flat[0] if len(flat) == 1 else V.VALUE
    if V.is_error(cond):
        return cond
    b = V.to_bool(cond)
    if V.is_error(b):
        return b
    if b:
        return args[1]
    return args[2] if len(args) == 3 else None


def _coerce_bools(args):
    out = []
    for a in args:
        vals = V.flatten([a]) if isinstance(a, list) else [a]
        for v in vals:
            if v is None:
                continue  # blanks are ignored by AND/OR, matching Excel
            b = V.to_bool(v)
            if V.is_error(b):
                return None, b
            out.append(b)
    return out, None


def fn_and(args):
    bools, err = _coerce_bools(args)
    if err is not None:
        return err
    if not bools:
        return V.VALUE
    return all(bools)


def fn_or(args):
    bools, err = _coerce_bools(args)
    if err is not None:
        return err
    if not bools:
        return V.VALUE
    return any(bools)


def fn_not(args):
    if len(args) != 1:
        return V.VALUE
    v = args[0]
    if isinstance(v, list):
        flat = V.flatten([v])
        v = flat[0] if len(flat) == 1 else V.VALUE
    b = V.to_bool(v)
    if V.is_error(b):
        return b
    return not b


def fn_iferror(args):
    if len(args) != 2:
        return V.VALUE
    value, fallback = args
    if isinstance(value, list):
        flat = V.flatten([value])
        if len(flat) == 1 and V.is_error(flat[0]):
            return fallback
        if any(V.is_error(v) for v in flat):
            return fallback
        return value
    if V.is_error(value):
        return fallback
    return value


def fn_iserror(args):
    if len(args) != 1:
        return V.VALUE
    v = args[0]
    if isinstance(v, list):
        return any(V.is_error(x) for x in V.flatten([v]))
    return V.is_error(v)


def fn_concatenate(args):
    parts = []
    for a in args:
        if isinstance(a, list):
            return V.VALUE  # CONCATENATE does not accept range arguments
        t = V.to_text(a)
        if V.is_error(t):
            return t
        parts.append(t)
    return "".join(parts)


def _one_text_arg(args, transform):
    if len(args) != 1:
        return V.VALUE
    v = args[0]
    if isinstance(v, list):
        flat = V.flatten([v])
        v = flat[0] if len(flat) == 1 else V.VALUE
    t = V.to_text(v)
    if V.is_error(t):
        return t
    return transform(t)


def fn_len(args):
    return _one_text_arg(args, lambda t: float(len(t)))


def fn_upper(args):
    return _one_text_arg(args, lambda t: t.upper())


def fn_lower(args):
    return _one_text_arg(args, lambda t: t.lower())


def fn_trim(args):
    def _trim(t):
        return " ".join(t.split())
    return _one_text_arg(args, _trim)


def _one_number_arg(args, transform):
    if len(args) != 1:
        return V.VALUE
    v = args[0]
    if isinstance(v, list):
        flat = V.flatten([v])
        v = flat[0] if len(flat) == 1 else V.VALUE
    n = V.to_number(v)
    if V.is_error(n):
        return n
    return transform(n)


def fn_abs(args):
    return _one_number_arg(args, abs)


def fn_int(args):
    return _one_number_arg(args, math.floor)


def fn_sqrt(args):
    def _sqrt(n):
        if n < 0:
            return V.NUM
        return math.sqrt(n)
    return _one_number_arg(args, _sqrt)


def _scalar_number(v):
    if isinstance(v, list):
        flat = V.flatten([v])
        v = flat[0] if len(flat) == 1 else V.VALUE
    return V.to_number(v)


def fn_round(args):
    if len(args) != 2:
        return V.VALUE
    n = _scalar_number(args[0])
    if V.is_error(n):
        return n
    d = _scalar_number(args[1])
    if V.is_error(d):
        return d
    digits = int(d)
    factor = 10 ** digits
    if n >= 0:
        return math.floor(n * factor + 0.5) / factor
    return math.ceil(n * factor - 0.5) / factor


def fn_mod(args):
    if len(args) != 2:
        return V.VALUE
    n = _scalar_number(args[0])
    if V.is_error(n):
        return n
    d = _scalar_number(args[1])
    if V.is_error(d):
        return d
    if d == 0:
        return V.DIV0
    return n - d * math.floor(n / d)


def fn_vlookup(args):
    if len(args) not in (3, 4):
        return V.VALUE
    lookup_value = args[0]
    if isinstance(lookup_value, list):
        flat = V.flatten([lookup_value])
        lookup_value = flat[0] if len(flat) == 1 else V.VALUE
    if V.is_error(lookup_value):
        return lookup_value
    table = args[1]
    if not isinstance(table, list) or not table:
        return V.VALUE
    col_index = _scalar_number(args[2])
    if V.is_error(col_index):
        return col_index
    col_index = int(col_index)
    if col_index < 1:
        return V.VALUE
    if col_index > len(table[0]):
        return V.REF
    range_lookup = True
    if len(args) == 4:
        rl = args[3]
        if isinstance(rl, list):
            flat = V.flatten([rl])
            rl = flat[0] if len(flat) == 1 else V.VALUE
        b = V.to_bool(rl)
        if V.is_error(b):
            return b
        range_lookup = b

    def key(v):
        return v.upper() if isinstance(v, str) else v

    if not range_lookup:
        for row in table:
            if V.is_error(row[0]):
                return row[0]
            if _exact_lookup_eq(row[0], lookup_value):
                return row[col_index - 1]
        return V.NA
    else:
        best = None
        for row in table:
            first = row[0]
            if V.is_error(first):
                return first
            if _type_compatible(first, lookup_value) and key(first) <= key(lookup_value):
                if best is None or key(first) > key(best[0]):
                    best = row
        if best is None:
            return V.NA
        return best[col_index - 1]


def _type_compatible(a, b):
    return (isinstance(a, float) and isinstance(b, float)) or (
        isinstance(a, str) and isinstance(b, str)
    )


def _exact_lookup_eq(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a.upper() == b.upper()
    if isinstance(a, float) and isinstance(b, float):
        return a == b
    if isinstance(a, bool) and isinstance(b, bool):
        return a == b
    return False


FUNCTIONS = {
    "SUM": fn_sum,
    "AVERAGE": fn_average,
    "MIN": fn_min,
    "MAX": fn_max,
    "COUNT": fn_count,
    "COUNTA": fn_counta,
    "COUNTIF": fn_countif,
    "SUMIF": fn_sumif,
    "IF": fn_if,
    "AND": fn_and,
    "OR": fn_or,
    "NOT": fn_not,
    "IFERROR": fn_iferror,
    "ISERROR": fn_iserror,
    "CONCATENATE": fn_concatenate,
    "LEN": fn_len,
    "UPPER": fn_upper,
    "LOWER": fn_lower,
    "TRIM": fn_trim,
    "ROUND": fn_round,
    "ABS": fn_abs,
    "SQRT": fn_sqrt,
    "MOD": fn_mod,
    "INT": fn_int,
    "VLOOKUP": fn_vlookup,
}
