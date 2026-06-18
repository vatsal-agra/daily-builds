"""Bytecode definitions: the OpCode set and the Chunk container.

A Chunk is a flat list of integers: opcodes interleaved with their operands.
A parallel `lines` list maps each *opcode* byte's offset to a source line so
the VM can report where a runtime error happened.
"""

from enum import IntEnum


class Op(IntEnum):
    CONSTANT = 0      # operand: const index -> push constant
    NIL = 1
    TRUE = 2
    FALSE = 3
    POP = 4
    DEFINE_GLOBAL = 5  # operand: name const index
    GET_GLOBAL = 6     # operand: name const index
    SET_GLOBAL = 7     # operand: name const index
    GET_LOCAL = 8      # operand: stack slot
    SET_LOCAL = 9      # operand: stack slot
    GET_UPVALUE = 10   # operand: upvalue index
    SET_UPVALUE = 11   # operand: upvalue index
    EQUAL = 12
    NOT_EQUAL = 13
    GREATER = 14
    GREATER_EQUAL = 15
    LESS = 16
    LESS_EQUAL = 17
    ADD = 18
    SUB = 19
    MUL = 20
    DIV = 21
    MOD = 22
    NEGATE = 23
    NOT = 24
    PRINT = 25
    JUMP = 26            # operand: absolute target
    JUMP_IF_FALSE = 27   # operand: absolute target (peeks, does not pop)
    JUMP_IF_FALSE_POP = 28  # operand: absolute target (pops condition)
    CALL = 29            # operand: arg count
    CLOSURE = 30         # operand: function const index; then pairs (is_local, index)
    GET_INDEX = 31
    SET_INDEX = 32
    BUILD_LIST = 33      # operand: element count
    BUILD_MAP = 34       # operand: pair count
    CLOSE_UPVALUE = 35   # close the topmost stack local as an upvalue
    RETURN = 36
    DUP = 37


# opcodes that take exactly one integer operand
_ONE_OPERAND = {
    Op.CONSTANT, Op.DEFINE_GLOBAL, Op.GET_GLOBAL, Op.SET_GLOBAL,
    Op.GET_LOCAL, Op.SET_LOCAL, Op.GET_UPVALUE, Op.SET_UPVALUE,
    Op.JUMP, Op.JUMP_IF_FALSE, Op.JUMP_IF_FALSE_POP, Op.CALL,
    Op.BUILD_LIST, Op.BUILD_MAP,
}


def has_operand(op):
    return op in _ONE_OPERAND


class Chunk:
    def __init__(self, name="<chunk>"):
        self.name = name
        self.code = []       # list[int]
        self.lines = []      # parallel to code
        self.constants = []  # list of runtime values

    def write(self, byte, line):
        self.code.append(int(byte))
        self.lines.append(line)
        return len(self.code) - 1

    def add_constant(self, value):
        # de-duplicate simple immutable constants
        for i, c in enumerate(self.constants):
            if type(c) is type(value) and c == value and not isinstance(c, bool):
                return i
            if isinstance(c, bool) and isinstance(value, bool) and c is value:
                return i
        self.constants.append(value)
        return len(self.constants) - 1
