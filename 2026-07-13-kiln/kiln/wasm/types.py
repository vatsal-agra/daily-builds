"""Value types and the in-memory Module IR shared by the decoder, encoder,
interpreter, assembler and Pebble compiler."""

from dataclasses import dataclass, field

# WASM value type encodings (MVP numeric types only — Kiln does not
# implement the reference-types / SIMD proposals).
I32 = 0x7F
I64 = 0x7E
F32 = 0x7D
F64 = 0x7C

VALTYPE_NAMES = {I32: "i32", I64: "i64", F32: "f32", F64: "f64"}
NAME_TO_VALTYPE = {v: k for k, v in VALTYPE_NAMES.items()}

# Section ids, in the fixed order they must appear in a binary module.
SEC_CUSTOM = 0
SEC_TYPE = 1
SEC_IMPORT = 2
SEC_FUNCTION = 3
SEC_TABLE = 4
SEC_MEMORY = 5
SEC_GLOBAL = 6
SEC_EXPORT = 7
SEC_START = 8
SEC_ELEMENT = 9
SEC_CODE = 10
SEC_DATA = 11

WASM_MAGIC = b"\x00asm"
WASM_VERSION = b"\x01\x00\x00\x00"


@dataclass
class FuncType:
    params: tuple
    results: tuple

    def key(self):
        return (self.params, self.results)


@dataclass
class Import:
    module: str
    name: str
    kind: str  # "func" | "memory" | "global"
    type_index: int = None
    mem_min: int = None
    mem_max: int = None
    global_type: int = None
    global_mutable: bool = False


@dataclass
class Global:
    val_type: int
    mutable: bool
    init: list  # constant-expression instruction list


@dataclass
class Export:
    name: str
    kind: str  # "func" | "memory" | "global"
    index: int


@dataclass
class Memory:
    min: int
    max: int = None


@dataclass
class Table:
    min: int
    max: int = None


@dataclass
class Element:
    table_index: int
    offset: list  # constant-expression instruction list
    func_indices: list


@dataclass
class Function:
    type_index: int
    locals: list  # list of valtype ints, one per additional local (params excluded)
    body: list  # decoded instruction list


@dataclass
class Data:
    memory_index: int
    offset: list  # constant-expression instruction list
    init: bytes


@dataclass
class Module:
    types: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    functions: list = field(default_factory=list)  # Function objects (defined only)
    tables: list = field(default_factory=list)
    memories: list = field(default_factory=list)
    globals: list = field(default_factory=list)
    exports: list = field(default_factory=list)
    elements: list = field(default_factory=list)
    data: list = field(default_factory=list)
    start: int = None

    def imported_funcs(self):
        return [i for i in self.imports if i.kind == "func"]

    def func_type_index(self, func_index):
        """Map a *global* function index (imports first, then defined
        functions) to its FuncType index."""
        n_imported = len(self.imported_funcs())
        if func_index < n_imported:
            return self.imported_funcs()[func_index].type_index
        return self.functions[func_index - n_imported].type_index

    def num_imported_funcs(self):
        return len(self.imported_funcs())
