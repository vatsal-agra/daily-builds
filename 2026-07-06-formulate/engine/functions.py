"""The built-in function library. Eager functions receive a list of already
evaluated arguments (scalar or RangeValue); lazy functions (IF, IFERROR) are
handled directly by the evaluator since they must control which branches get
evaluated.
"""

import fnmatch
import math

from .errors import ErrorValue, FormulaError, DIV0, VALUE, NA, NUM, to_number, to_string, to_bool
from .values import RangeValue, flatten_args, numeric_only

LAZY_FUNCTION_NAMES = {"IF", "IFERROR"}


def _num_args(args):
    return numeric_only(flatten_args(args))


def fn_sum(args):
    return sum(_num_args(args))


def fn_average(args):
    nums = _num_args(args)
    if not nums:
        raise FormulaError(DIV0)
    return sum(nums) / len(nums)


def fn_count(args):
    return float(len(_num_args(args)))


def fn_counta(args):
    flat = flatten_args(args)
    return float(sum(1 for v in flat if v is not None))


def fn_min(args):
    nums = _num_args(args)
    return min(nums) if nums else 0.0


def fn_max(args):
    nums = _num_args(args)
    return max(nums) if nums else 0.0


def fn_and(args):
    flat = flatten_args(args)
    if not flat:
        raise FormulaError(VALUE)
    return all(to_bool(v) for v in flat)


def fn_or(args):
    flat = flatten_args(args)
    if not flat:
        raise FormulaError(VALUE)
    return any(to_bool(v) for v in flat)


def fn_not(args):
    if len(args) != 1:
        raise FormulaError(VALUE)
    return not to_bool(args[0])


def fn_round(args):
    if len(args) != 2:
        raise FormulaError(VALUE)
    n = to_number(args[0])
    digits = int(to_number(args[1]))
    factor = 10 ** digits
    return math.floor(abs(n) * factor + 0.5) / factor * (1 if n >= 0 else -1)


def fn_abs(args):
    _require(args, 1)
    return abs(to_number(args[0]))


def fn_sqrt(args):
    _require(args, 1)
    n = to_number(args[0])
    if n < 0:
        raise FormulaError(NUM)
    return math.sqrt(n)


def fn_power(args):
    _require(args, 2)
    return to_number(args[0]) ** to_number(args[1])


def fn_mod(args):
    _require(args, 2)
    a, b = to_number(args[0]), to_number(args[1])
    if b == 0:
        raise FormulaError(DIV0)
    return math.fmod(a, b) if (a < 0) == (b < 0) or math.fmod(a, b) == 0 else math.fmod(a, b) + b


def fn_int(args):
    _require(args, 1)
    return float(math.floor(to_number(args[0])))


def fn_floor(args):
    _require(args, 1)
    return float(math.floor(to_number(args[0])))


def fn_ceiling(args):
    _require(args, 1)
    return float(math.ceil(to_number(args[0])))


def fn_sign(args):
    _require(args, 1)
    n = to_number(args[0])
    return float((n > 0) - (n < 0))


def fn_concat(args):
    flat = flatten_args(args)
    return "".join(to_string(v) for v in flat)


def fn_len(args):
    _require(args, 1)
    return float(len(to_string(args[0])))


def fn_upper(args):
    _require(args, 1)
    return to_string(args[0]).upper()


def fn_lower(args):
    _require(args, 1)
    return to_string(args[0]).lower()


def fn_trim(args):
    _require(args, 1)
    return " ".join(to_string(args[0]).split())


def fn_left(args):
    s = to_string(args[0])
    n = int(to_number(args[1])) if len(args) > 1 else 1
    return s[:max(n, 0)]


def fn_right(args):
    s = to_string(args[0])
    n = int(to_number(args[1])) if len(args) > 1 else 1
    return s[-n:] if n > 0 else ""


def fn_mid(args):
    _require(args, 3)
    s = to_string(args[0])
    start = int(to_number(args[1]))
    length = int(to_number(args[2]))
    if start < 1 or length < 0:
        raise FormulaError(VALUE)
    return s[start - 1: start - 1 + length]


def fn_isblank(args):
    _require(args, 1)
    return args[0] is None


def fn_isnumber(args):
    _require(args, 1)
    return isinstance(args[0], (int, float)) and not isinstance(args[0], bool)


def fn_istext(args):
    _require(args, 1)
    return isinstance(args[0], str)


def fn_iserror(args):
    _require(args, 1)
    return isinstance(args[0], ErrorValue)


def fn_true(args):
    return True


def fn_false(args):
    return False


def _require(args, n):
    if len(args) != n:
        raise FormulaError(VALUE)


def _flat_range(arg):
    if isinstance(arg, RangeValue):
        return arg.flat()
    return [arg]


def _matches(value, criteria):
    if isinstance(criteria, ErrorValue):
        raise FormulaError(criteria.code)
    if isinstance(criteria, (int, float)) and not isinstance(criteria, bool):
        try:
            return to_number(value) == float(criteria)
        except FormulaError:
            return False
    text = to_string(criteria).strip()
    for op, cmp in ((">=", lambda a, b: a >= b), ("<=", lambda a, b: a <= b),
                    ("<>", lambda a, b: a != b), (">", lambda a, b: a > b),
                    ("<", lambda a, b: a < b), ("=", lambda a, b: a == b)):
        if text.startswith(op):
            rhs = text[len(op):].strip()
            try:
                return cmp(to_number(value), float(rhs))
            except (FormulaError, ValueError):
                return cmp(to_string(value).upper(), rhs.upper())
    if "*" in text or "?" in text:
        return fnmatch.fnmatch(to_string(value).upper(), text.upper())
    try:
        return to_number(value) == float(text)
    except (FormulaError, ValueError):
        pass
    return to_string(value).upper() == text.upper()


def fn_sumif(args):
    if len(args) not in (2, 3):
        raise FormulaError(VALUE)
    rng = _flat_range(args[0])
    criteria = args[1]
    sum_rng = _flat_range(args[2]) if len(args) == 3 else rng
    if len(sum_rng) != len(rng):
        raise FormulaError(VALUE)
    total = 0.0
    for v, s in zip(rng, sum_rng):
        if _matches(v, criteria):
            total += to_number(s)
    return total


def fn_countif(args):
    _require(args, 2)
    rng = _flat_range(args[0])
    criteria = args[1]
    return float(sum(1 for v in rng if _matches(v, criteria)))


def fn_averageif(args):
    if len(args) not in (2, 3):
        raise FormulaError(VALUE)
    rng = _flat_range(args[0])
    criteria = args[1]
    avg_rng = _flat_range(args[2]) if len(args) == 3 else rng
    matched = [to_number(s) for v, s in zip(rng, avg_rng) if _matches(v, criteria)]
    if not matched:
        raise FormulaError(DIV0)
    return sum(matched) / len(matched)


def fn_index(args):
    if len(args) not in (2, 3):
        raise FormulaError(VALUE)
    rng = args[0]
    if not isinstance(rng, RangeValue):
        rng = RangeValue([[rng]])
    row = int(to_number(args[1]))
    col = int(to_number(args[2])) if len(args) == 3 else 1
    if row < 0 or col < 0:
        raise FormulaError(VALUE)
    if row == 0 and col == 0:
        raise FormulaError(VALUE)
    rows = rng.rows
    if row == 0:
        # whole-column reference collapsed to a single value only when 1 row
        if len(rows) != 1:
            raise FormulaError(VALUE)
        row = 1
    if col == 0:
        if len(rows[0]) != 1:
            raise FormulaError(VALUE)
        col = 1
    if row - 1 >= len(rows) or col - 1 >= len(rows[0]):
        raise FormulaError(NA)
    return rows[row - 1][col - 1]


def fn_match(args):
    if len(args) not in (2, 3):
        raise FormulaError(VALUE)
    target = args[0]
    rng = _flat_range(args[1])
    match_type = int(to_number(args[2])) if len(args) == 3 else 1
    if match_type == 0:
        for i, v in enumerate(rng):
            if _values_equal(v, target):
                return float(i + 1)
        raise FormulaError(NA)
    if match_type == 1:
        best = None
        for i, v in enumerate(rng):
            try:
                if to_number(v) <= to_number(target):
                    best = i + 1
                else:
                    break
            except FormulaError:
                break
        if best is None:
            raise FormulaError(NA)
        return float(best)
    # match_type == -1: range assumed descending
    best = None
    for i, v in enumerate(rng):
        try:
            if to_number(v) >= to_number(target):
                best = i + 1
            else:
                break
        except FormulaError:
            break
    if best is None:
        raise FormulaError(NA)
    return float(best)


def _values_equal(a, b):
    try:
        return to_number(a) == to_number(b)
    except FormulaError:
        return to_string(a).upper() == to_string(b).upper()


def fn_vlookup(args):
    if len(args) not in (3, 4):
        raise FormulaError(VALUE)
    target = args[0]
    table = args[1]
    if not isinstance(table, RangeValue):
        raise FormulaError(VALUE)
    col_index = int(to_number(args[2]))
    approx = to_bool(args[3]) if len(args) == 4 else True
    if col_index < 1:
        raise FormulaError(VALUE)
    first_col = [row[0] if row else None for row in table.rows]
    if approx:
        best_row = None
        for i, v in enumerate(first_col):
            try:
                if to_number(v) <= to_number(target):
                    best_row = i
                else:
                    break
            except FormulaError:
                break
        if best_row is None:
            raise FormulaError(NA)
        row = table.rows[best_row]
    else:
        row = None
        for r in table.rows:
            if r and _values_equal(r[0], target):
                row = r
                break
        if row is None:
            raise FormulaError(NA)
    if col_index - 1 >= len(row):
        raise FormulaError(VALUE)
    return row[col_index - 1]


EAGER_FUNCTIONS = {
    "SUM": fn_sum,
    "AVERAGE": fn_average,
    "COUNT": fn_count,
    "COUNTA": fn_counta,
    "MIN": fn_min,
    "MAX": fn_max,
    "AND": fn_and,
    "OR": fn_or,
    "NOT": fn_not,
    "ROUND": fn_round,
    "ABS": fn_abs,
    "SQRT": fn_sqrt,
    "POWER": fn_power,
    "MOD": fn_mod,
    "INT": fn_int,
    "FLOOR": fn_floor,
    "CEILING": fn_ceiling,
    "SIGN": fn_sign,
    "CONCAT": fn_concat,
    "CONCATENATE": fn_concat,
    "LEN": fn_len,
    "UPPER": fn_upper,
    "LOWER": fn_lower,
    "TRIM": fn_trim,
    "LEFT": fn_left,
    "RIGHT": fn_right,
    "MID": fn_mid,
    "ISBLANK": fn_isblank,
    "ISNUMBER": fn_isnumber,
    "ISTEXT": fn_istext,
    "ISERROR": fn_iserror,
    "TRUE": fn_true,
    "FALSE": fn_false,
    "SUMIF": fn_sumif,
    "COUNTIF": fn_countif,
    "AVERAGEIF": fn_averageif,
    "INDEX": fn_index,
    "MATCH": fn_match,
    "VLOOKUP": fn_vlookup,
}
