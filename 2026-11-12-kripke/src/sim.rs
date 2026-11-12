//! Random simulation: print one random execution of a model.

use crate::bdd::{Bdd, FALSE};
use crate::check::{Checker, Trace};
use crate::fuzz::Rng;
use crate::lang::*;
use crate::model::Model;

fn random_cube(md: &mut Model, set: Bdd, rng: &mut Rng) -> Bdd {
    let mut cur = set;
    let mut lits: Vec<(u32, bool)> = vec![];
    for &v in &md.cur_vars.clone() {
        let (t, f) = {
            let pv = md.m.var(v);
            let nv = md.m.not(pv);
            (md.m.and(cur, pv), md.m.and(cur, nv))
        };
        let val = match (t != FALSE, f != FALSE) {
            (true, true) => rng.chance(1, 2),
            (true, false) => true,
            _ => false,
        };
        cur = if val { t } else { f };
        lits.push((v, val));
    }
    md.m.literals(&lits)
}

pub fn simulate(src: &str, steps: usize, seed: u64) -> Res<Trace> {
    let prog = parse(src)?;
    let mut md = Model::compile(prog, false)?;
    let mut rng = Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1);
    let init = md.init;
    if init == FALSE {
        return Err(Error::new(Pos { line: 1, col: 1 }, "the model has no initial state"));
    }
    let mut cubes = vec![random_cube(&mut md, init, &mut rng)];
    for _ in 0..steps {
        let last = *cubes.last().unwrap();
        let img = md.image(last);
        if img == FALSE {
            break;
        }
        cubes.push(random_cube(&mut md, img, &mut rng));
    }
    for &c in &cubes {
        md.m.pin(c);
    }
    let mut ck = Checker::new(&mut md);
    Ok(ck.to_trace(&cubes, None))
}
