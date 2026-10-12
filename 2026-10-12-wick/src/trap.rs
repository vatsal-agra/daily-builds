use std::fmt;

/// A runtime trap (or resource-limit stop).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Trap {
    Unreachable,
    IntDivZero,
    IntOverflow,
    InvalidConversion,
    MemoryOob,
    TableOob,
    UninitializedElement,
    IndirectCallTypeMismatch,
    StackExhausted,
    OutOfFuel,
    Host(String),
}

impl Trap {
    /// Coarse category used for differential comparison against V8, whose messages
    /// merge some of the spec's distinctions.
    pub fn category(&self) -> &'static str {
        match self {
            Trap::Unreachable => "unreachable",
            Trap::IntDivZero => "div_zero",
            Trap::IntOverflow => "int_overflow_or_conv",
            Trap::InvalidConversion => "conv",
            Trap::MemoryOob => "memory_oob",
            Trap::TableOob => "table_oob",
            Trap::UninitializedElement | Trap::IndirectCallTypeMismatch => "indirect",
            Trap::StackExhausted => "stack",
            Trap::OutOfFuel => "fuel",
            Trap::Host(_) => "host",
        }
    }
}

impl fmt::Display for Trap {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Trap::Unreachable => write!(f, "unreachable executed"),
            Trap::IntDivZero => write!(f, "integer divide by zero"),
            Trap::IntOverflow => write!(f, "integer overflow"),
            Trap::InvalidConversion => write!(f, "invalid conversion to integer"),
            Trap::MemoryOob => write!(f, "out of bounds memory access"),
            Trap::TableOob => write!(f, "undefined element: table index out of bounds"),
            Trap::UninitializedElement => write!(f, "uninitialized element"),
            Trap::IndirectCallTypeMismatch => write!(f, "indirect call type mismatch"),
            Trap::StackExhausted => write!(f, "call stack exhausted"),
            Trap::OutOfFuel => write!(f, "out of fuel"),
            Trap::Host(s) => write!(f, "host error: {s}"),
        }
    }
}
impl std::error::Error for Trap {}
