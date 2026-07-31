"""The builtin function library. Each function receives a list of already-
evaluated argument values -- a scalar (int/float/str/bool/None) or a
`RangeValue` (a flattenable 2D block from a range reference) -- and returns
a scalar, or raises TrellisError for a genuine error condition."""

from .errors import TrellisError, DIV0, VALUE, NUM


class RangeValue:
    """A 2D block of cell values pulled in by a RangeRef argument."""

    __slots__ = ("rows",)

    def __init__(self, rows):
        self.rows = rows  # list[list[scalar]]

    def flatten(self):
        out = []
        for row in self.rows:
            out.extend(row)
        return out


def _flatten_args(args):
    out = []
    for a in args:
        if isinstance(a, RangeValue):
            out.extend(a.flatten())
        else:
            out.append(a)
    return out


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_is_number = is_number  # internal alias used throughout this module


def _numbers(args):
    return [v for v in _flatten_args(args) if _is_number(v)]


def to_number(v):
    if _is_number(v):
        return v
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            raise TrellisError(VALUE)
    if v is None:
        return 0
    raise TrellisError(VALUE)


def to_bool(v):
    if isinstance(v, bool):
        return v
    if _is_number(v):
        return v != 0
    if isinstance(v, str):
        u = v.strip().upper()
        if u == "TRUE":
            return True
        if u == "FALSE":
            return False
        raise TrellisError(VALUE)
    if v is None:
        return False
    raise TrellisError(VALUE)


def to_display_str(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    return str(v)


def fn_sum(args):
    return sum(_numbers(args)) if args else 0


def fn_average(args):
    nums = _numbers(args)
    if not nums:
        raise TrellisError(DIV0)
    return sum(nums) / len(nums)


def fn_count(args):
    return len(_numbers(args))


def fn_counta(args):
    return sum(1 for v in _flatten_args(args) if v is not None)


def fn_min(args):
    nums = _numbers(args)
    return min(nums) if nums else 0


def fn_max(args):
    nums = _numbers(args)
    return max(nums) if nums else 0


def fn_round(args):
    if len(args) not in (1, 2):
        raise TrellisError(VALUE)
    x = to_number(args[0])
    digits = int(to_number(args[1])) if len(args) == 2 else 0
    result = round(x, digits)
    return int(result) if digits <= 0 and isinstance(result, float) and result == int(result) else result


def fn_abs(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    return abs(to_number(args[0]))


def fn_sqrt(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    x = to_number(args[0])
    if x < 0:
        raise TrellisError(NUM)
    return x ** 0.5


def fn_power(args):
    if len(args) != 2:
        raise TrellisError(VALUE)
    base, exp = to_number(args[0]), to_number(args[1])
    try:
        return base ** exp
    except (ValueError, OverflowError, ZeroDivisionError):
        raise TrellisError(NUM)


def fn_mod(args):
    if len(args) != 2:
        raise TrellisError(VALUE)
    a, b = to_number(args[0]), to_number(args[1])
    if b == 0:
        raise TrellisError(DIV0)
    return a - b * (a // b)


def fn_len(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    return len(to_display_str(args[0]) if not isinstance(args[0], str) else args[0])


def fn_upper(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    v = args[0]
    return (v if isinstance(v, str) else to_display_str(v)).upper()


def fn_lower(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    v = args[0]
    return (v if isinstance(v, str) else to_display_str(v)).lower()


def fn_trim(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    v = args[0]
    s = v if isinstance(v, str) else to_display_str(v)
    return " ".join(s.split())


def fn_concat(args):
    return "".join(to_display_str(v) for v in _flatten_args(args))


def fn_and(args):
    vals = _flatten_args(args)
    if not vals:
        raise TrellisError(VALUE)
    return all(to_bool(v) for v in vals)


def fn_or(args):
    vals = _flatten_args(args)
    if not vals:
        raise TrellisError(VALUE)
    return any(to_bool(v) for v in vals)


def fn_not(args):
    if len(args) != 1:
        raise TrellisError(VALUE)
    return not to_bool(args[0])


def fn_vlookup(args):
    if len(args) not in (3, 4):
        raise TrellisError(VALUE)
    key, table, col_index = args[0], args[1], args[2]
    # Real Excel defaults the 4th arg (range_lookup) to TRUE/approximate
    # when omitted -- a well-known footgun (an unsorted or non-numeric
    # first lookup column silently returns a wrong row instead of erroring).
    # Trellis deliberately defaults to exact-match instead; approximate
    # matching is opt-in via a truthy 4th argument.
    approximate = to_bool(args[3]) if len(args) == 4 else False
    if not isinstance(table, RangeValue):
        raise TrellisError(VALUE)
    col_index = int(to_number(col_index))
    if col_index < 1:
        raise TrellisError(VALUE)

    for row in table.rows:
        if col_index > len(row):
            raise TrellisError(REF_ERR)
        if _loose_eq(row[0], key):
            return row[col_index - 1]

    if approximate:
        # Fall back to the largest first-column value <= key (table assumed
        # sorted ascending, the same precondition real VLOOKUP has).
        candidates = [r for r in table.rows if is_number(r[0]) and is_number(key) and r[0] <= key]
        if candidates:
            best_row = max(candidates, key=lambda r: r[0])
            if col_index > len(best_row):
                raise TrellisError(REF_ERR)
            return best_row[col_index - 1]

    from .errors import NA
    raise TrellisError(NA)


def _loose_eq(a, b):
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a.upper() == b.upper()
    return a == b


REF_ERR = "#REF!"

FUNCTIONS = {
    "SUM": fn_sum,
    "AVERAGE": fn_average,
    "COUNT": fn_count,
    "COUNTA": fn_counta,
    "MIN": fn_min,
    "MAX": fn_max,
    "ROUND": fn_round,
    "ABS": fn_abs,
    "SQRT": fn_sqrt,
    "POWER": fn_power,
    "MOD": fn_mod,
    "LEN": fn_len,
    "UPPER": fn_upper,
    "LOWER": fn_lower,
    "TRIM": fn_trim,
    "CONCAT": fn_concat,
    "CONCATENATE": fn_concat,
    "AND": fn_and,
    "OR": fn_or,
    "NOT": fn_not,
    "VLOOKUP": fn_vlookup,
}
