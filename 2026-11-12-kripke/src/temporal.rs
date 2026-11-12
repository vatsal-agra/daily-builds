//! CTL / LTL formula trees (generic over the atom type) and lowering from the parsed AST.

use crate::lang::*;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Ctl<A> {
    Atom(A),
    Not(Box<Ctl<A>>),
    And(Box<Ctl<A>>, Box<Ctl<A>>),
    Or(Box<Ctl<A>>, Box<Ctl<A>>),
    Imp(Box<Ctl<A>>, Box<Ctl<A>>),
    Iff(Box<Ctl<A>>, Box<Ctl<A>>),
    Xor(Box<Ctl<A>>, Box<Ctl<A>>),
    EX(Box<Ctl<A>>),
    AX(Box<Ctl<A>>),
    EF(Box<Ctl<A>>),
    AF(Box<Ctl<A>>),
    EG(Box<Ctl<A>>),
    AG(Box<Ctl<A>>),
    EU(Box<Ctl<A>>, Box<Ctl<A>>),
    AU(Box<Ctl<A>>, Box<Ctl<A>>),
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum Ltl<A> {
    Atom(A),
    Not(Box<Ltl<A>>),
    And(Box<Ltl<A>>, Box<Ltl<A>>),
    Or(Box<Ltl<A>>, Box<Ltl<A>>),
    Imp(Box<Ltl<A>>, Box<Ltl<A>>),
    Iff(Box<Ltl<A>>, Box<Ltl<A>>),
    Xor(Box<Ltl<A>>, Box<Ltl<A>>),
    X(Box<Ltl<A>>),
    F(Box<Ltl<A>>),
    G(Box<Ltl<A>>),
    U(Box<Ltl<A>>, Box<Ltl<A>>),
    R(Box<Ltl<A>>, Box<Ltl<A>>),
}

fn b<T>(x: T) -> Box<T> {
    Box::new(x)
}

/// Lower an expression into a CTL tree; `atom` compiles maximal non-temporal sub-expressions.
pub fn lower_ctl<A>(e: &Expr, atom: &mut dyn FnMut(&Expr) -> Res<A>) -> Res<Ctl<A>> {
    if !e.is_temporal() {
        return Ok(Ctl::Atom(atom(e)?));
    }
    match &e.k {
        Ek::Un(op, x) => {
            let sub = lower_ctl(x, atom)?;
            Ok(match op {
                UnOp::Not => Ctl::Not(b(sub)),
                UnOp::EX => Ctl::EX(b(sub)),
                UnOp::AX => Ctl::AX(b(sub)),
                UnOp::EF => Ctl::EF(b(sub)),
                UnOp::AF => Ctl::AF(b(sub)),
                UnOp::EG => Ctl::EG(b(sub)),
                UnOp::AG => Ctl::AG(b(sub)),
                UnOp::Neg => return Err(Error::new(e.pos, "arithmetic applied to a temporal formula")),
                UnOp::X | UnOp::F | UnOp::G => {
                    return Err(Error::new(e.pos, "LTL operator in a CTL formula: use EX/AX/EF/AF/EG/AG, or write the property as LTLSPEC"))
                }
            })
        }
        Ek::Bin(op, l, r) => {
            let (l2, r2) = match op {
                BinOp::And | BinOp::Or | BinOp::Imp | BinOp::Iff | BinOp::Xor => (lower_ctl(l, atom)?, lower_ctl(r, atom)?),
                BinOp::Until | BinOp::Release => {
                    return Err(Error::new(e.pos, "LTL operator in a CTL formula: use E[a U b] / A[a U b], or write the property as LTLSPEC"))
                }
                _ => return Err(Error::new(e.pos, "a temporal formula cannot be an operand of a comparison or arithmetic")),
            };
            Ok(match op {
                BinOp::And => Ctl::And(b(l2), b(r2)),
                BinOp::Or => Ctl::Or(b(l2), b(r2)),
                BinOp::Imp => Ctl::Imp(b(l2), b(r2)),
                BinOp::Iff => Ctl::Iff(b(l2), b(r2)),
                _ => Ctl::Xor(b(l2), b(r2)),
            })
        }
        Ek::EU(l, r) => Ok(Ctl::EU(b(lower_ctl(l, atom)?), b(lower_ctl(r, atom)?))),
        Ek::AU(l, r) => Ok(Ctl::AU(b(lower_ctl(l, atom)?), b(lower_ctl(r, atom)?))),
        _ => Err(Error::new(e.pos, "temporal operators may only be combined with boolean connectives")),
    }
}

pub fn lower_ltl<A>(e: &Expr, atom: &mut dyn FnMut(&Expr) -> Res<A>) -> Res<Ltl<A>> {
    if !e.is_temporal() {
        return Ok(Ltl::Atom(atom(e)?));
    }
    match &e.k {
        Ek::Un(op, x) => {
            let sub = lower_ltl(x, atom)?;
            Ok(match op {
                UnOp::Not => Ltl::Not(b(sub)),
                UnOp::X => Ltl::X(b(sub)),
                UnOp::F => Ltl::F(b(sub)),
                UnOp::G => Ltl::G(b(sub)),
                UnOp::Neg => return Err(Error::new(e.pos, "arithmetic applied to a temporal formula")),
                _ => return Err(Error::new(e.pos, "path quantifiers (EX/AG/...) are not allowed in LTLSPEC; use X/F/G/U/R")),
            })
        }
        Ek::Bin(op, l, r) => {
            let (l2, r2) = match op {
                BinOp::And | BinOp::Or | BinOp::Imp | BinOp::Iff | BinOp::Xor | BinOp::Until | BinOp::Release => {
                    (lower_ltl(l, atom)?, lower_ltl(r, atom)?)
                }
                _ => return Err(Error::new(e.pos, "a temporal formula cannot be an operand of a comparison or arithmetic")),
            };
            Ok(match op {
                BinOp::And => Ltl::And(b(l2), b(r2)),
                BinOp::Or => Ltl::Or(b(l2), b(r2)),
                BinOp::Imp => Ltl::Imp(b(l2), b(r2)),
                BinOp::Iff => Ltl::Iff(b(l2), b(r2)),
                BinOp::Xor => Ltl::Xor(b(l2), b(r2)),
                BinOp::Until => Ltl::U(b(l2), b(r2)),
                _ => Ltl::R(b(l2), b(r2)),
            })
        }
        Ek::EU(..) | Ek::AU(..) => Err(Error::new(e.pos, "path quantifiers are not allowed in LTLSPEC")),
        _ => Err(Error::new(e.pos, "temporal operators may only be combined with boolean connectives")),
    }
}

impl<A> Ctl<A> {
    /// Does the formula contain a temporal operator?
    pub fn is_pathy(&self) -> bool {
        !matches!(self, Ctl::Atom(_))
            && match self {
                Ctl::Not(a) => a.is_pathy(),
                Ctl::And(a, b) | Ctl::Or(a, b) | Ctl::Imp(a, b) | Ctl::Iff(a, b) | Ctl::Xor(a, b) => a.is_pathy() || b.is_pathy(),
                _ => true,
            }
    }
}
