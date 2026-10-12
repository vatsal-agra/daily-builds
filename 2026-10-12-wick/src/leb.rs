//! LEB128 encoding and bounds-checked decoding.

pub fn write_u(out: &mut Vec<u8>, mut v: u64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        if v == 0 {
            out.push(b);
            return;
        }
        out.push(b | 0x80);
    }
}

pub fn write_s(out: &mut Vec<u8>, mut v: i64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        let done = (v == 0 && b & 0x40 == 0) || (v == -1 && b & 0x40 != 0);
        if done {
            out.push(b);
            return;
        }
        out.push(b | 0x80);
    }
}

/// Read an unsigned LEB of at most `bits` bits starting at `*pos`.
pub fn read_u(data: &[u8], pos: &mut usize, bits: u32) -> Result<u64, String> {
    let mut result: u64 = 0;
    let mut shift = 0u32;
    let max_bytes = (bits + 6) / 7;
    for i in 0..max_bytes {
        let b = *data.get(*pos).ok_or("unexpected end of LEB128")?;
        *pos += 1;
        let low = (b & 0x7f) as u64;
        if i == max_bytes - 1 {
            // Unused high bits of the final byte must be zero, and no continuation.
            let used = bits - shift;
            if b & 0x80 != 0 {
                return Err("LEB128 too long".into());
            }
            if used < 7 && (low >> used) != 0 {
                return Err("LEB128 integer too large".into());
            }
        }
        result |= low << shift;
        if b & 0x80 == 0 {
            return Ok(result);
        }
        shift += 7;
    }
    Err("LEB128 too long".into())
}

pub fn read_s(data: &[u8], pos: &mut usize, bits: u32) -> Result<i64, String> {
    let mut result: i64 = 0;
    let mut shift = 0u32;
    let max_bytes = (bits + 6) / 7;
    for i in 0..max_bytes {
        let b = *data.get(*pos).ok_or("unexpected end of LEB128")?;
        *pos += 1;
        let low = (b & 0x7f) as i64;
        if i == max_bytes - 1 {
            if b & 0x80 != 0 {
                return Err("LEB128 too long".into());
            }
            // Final byte: bits beyond `bits` must be a sign extension of the top used bit.
            let used = bits - shift; // number of meaningful bits in this byte (<=7)
            if used < 7 {
                let sign_and_rest = (b as i8) << 1 >> 1; // sign-extend 7 bits
                let top = (sign_and_rest as i64) >> (used - 1);
                if top != 0 && top != -1 {
                    return Err("LEB128 integer too large".into());
                }
            }
        }
        result |= low << shift;
        shift += 7;
        if b & 0x80 == 0 {
            if shift < 64 && (b & 0x40) != 0 {
                result |= -1i64 << shift;
            }
            return Ok(result);
        }
    }
    Err("LEB128 too long".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip() {
        for &v in &[0i64, 1, -1, 63, 64, -64, -65, 127, 128, i32::MIN as i64, i32::MAX as i64, i64::MIN, i64::MAX] {
            let mut b = vec![];
            write_s(&mut b, v);
            let mut p = 0;
            assert_eq!(read_s(&b, &mut p, 64).unwrap(), v);
            assert_eq!(p, b.len());
        }
        for &v in &[0u64, 1, 127, 128, 624485, u32::MAX as u64, u64::MAX] {
            let mut b = vec![];
            write_u(&mut b, v);
            let mut p = 0;
            assert_eq!(read_u(&b, &mut p, 64).unwrap(), v);
        }
    }
    #[test]
    fn rejects_overlong_and_oversized() {
        // 6-byte u32
        assert!(read_u(&[0x80, 0x80, 0x80, 0x80, 0x80, 0x00], &mut 0, 32).is_err());
        // u32 with bits set above 32
        assert!(read_u(&[0xff, 0xff, 0xff, 0xff, 0x1f], &mut 0, 32).is_err());
        assert_eq!(read_u(&[0xff, 0xff, 0xff, 0xff, 0x0f], &mut 0, 32).unwrap(), u32::MAX as u64);
        // i32 final byte must sign-extend
        assert!(read_s(&[0x80, 0x80, 0x80, 0x80, 0x70], &mut 0, 32).is_err());
        assert_eq!(read_s(&[0x80, 0x80, 0x80, 0x80, 0x78], &mut 0, 32).unwrap(), i32::MIN as i64);
        assert_eq!(read_s(&[0x7f], &mut 0, 32).unwrap(), -1);
        assert!(read_u(&[0x80], &mut 0, 32).is_err());
    }
}
