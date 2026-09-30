//! Human-friendly unit parsing for the CLI: "10mbit", "50ms", "1.5%", "2MB".

fn split_num(s: &str) -> Result<(f64, &str), String> {
    let s = s.trim();
    let end = s
        .find(|c: char| !(c.is_ascii_digit() || c == '.'))
        .unwrap_or(s.len());
    if end == 0 {
        return Err(format!("expected a number in '{s}'"));
    }
    let n: f64 = s[..end].parse().map_err(|_| format!("bad number in '{s}'"))?;
    Ok((n, s[end..].trim()))
}

/// Bits per second: 500kbit, 10mbit, 1gbit, 8000 (bare = bit/s).
pub fn parse_rate(s: &str) -> Result<u64, String> {
    let (n, u) = split_num(s)?;
    let mult = match u.to_ascii_lowercase().as_str() {
        "" | "bit" | "bps" => 1.0,
        "kbit" | "kbps" | "k" => 1e3,
        "mbit" | "mbps" | "m" => 1e6,
        "gbit" | "gbps" | "g" => 1e9,
        other => return Err(format!("unknown rate unit '{other}'")),
    };
    let v = (n * mult) as u64;
    if v == 0 {
        return Err("rate must be > 0".into());
    }
    Ok(v)
}

/// Microseconds: 50ms, 1.5s, 200us, bare = ms.
pub fn parse_duration_us(s: &str) -> Result<u64, String> {
    let (n, u) = split_num(s)?;
    let mult = match u.to_ascii_lowercase().as_str() {
        "us" => 1.0,
        "" | "ms" => 1e3,
        "s" => 1e6,
        other => return Err(format!("unknown time unit '{other}'")),
    };
    Ok((n * mult) as u64)
}

/// Bytes: 512, 64KB, 2MB (binary multiples, as is conventional for buffers).
pub fn parse_size(s: &str) -> Result<usize, String> {
    let (n, u) = split_num(s)?;
    let mult = match u.to_ascii_lowercase().as_str() {
        "" | "b" => 1.0,
        "k" | "kb" | "kib" => 1024.0,
        "m" | "mb" | "mib" => 1024.0 * 1024.0,
        "g" | "gb" | "gib" => 1024.0 * 1024.0 * 1024.0,
        other => return Err(format!("unknown size unit '{other}'")),
    };
    Ok((n * mult) as usize)
}

/// Probability: "2%" or "0.02".
pub fn parse_prob(s: &str) -> Result<f64, String> {
    let s = s.trim();
    let p = if let Some(pct) = s.strip_suffix('%') {
        pct.trim().parse::<f64>().map_err(|_| format!("bad percentage '{s}'"))? / 100.0
    } else {
        s.parse::<f64>().map_err(|_| format!("bad probability '{s}'"))?
    };
    if !(0.0..=1.0).contains(&p) {
        return Err(format!("probability '{s}' out of range 0..1"));
    }
    Ok(p)
}

pub fn fmt_rate(bps: f64) -> String {
    if bps >= 1e9 {
        format!("{:.2} Gbit/s", bps / 1e9)
    } else if bps >= 1e6 {
        format!("{:.2} Mbit/s", bps / 1e6)
    } else if bps >= 1e3 {
        format!("{:.1} kbit/s", bps / 1e3)
    } else {
        format!("{:.0} bit/s", bps)
    }
}

pub fn fmt_bytes(n: u64) -> String {
    if n >= 1 << 30 {
        format!("{:.2} GiB", n as f64 / (1u64 << 30) as f64)
    } else if n >= 1 << 20 {
        format!("{:.2} MiB", n as f64 / (1u64 << 20) as f64)
    } else if n >= 1 << 10 {
        format!("{:.1} KiB", n as f64 / 1024.0)
    } else {
        format!("{n} B")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rates() {
        assert_eq!(parse_rate("10mbit").unwrap(), 10_000_000);
        assert_eq!(parse_rate("1.5Mbps").unwrap(), 1_500_000);
        assert_eq!(parse_rate("500kbit").unwrap(), 500_000);
        assert_eq!(parse_rate("9600").unwrap(), 9600);
        assert!(parse_rate("0mbit").is_err());
        assert!(parse_rate("fast").is_err());
        assert!(parse_rate("5furlongs").is_err());
    }
    #[test]
    fn durations() {
        assert_eq!(parse_duration_us("50ms").unwrap(), 50_000);
        assert_eq!(parse_duration_us("1.5s").unwrap(), 1_500_000);
        assert_eq!(parse_duration_us("200us").unwrap(), 200);
        assert_eq!(parse_duration_us("7").unwrap(), 7_000);
        assert!(parse_duration_us("ms").is_err());
        assert!(parse_duration_us("3parsecs").is_err());
    }
    #[test]
    fn sizes_and_probs() {
        assert_eq!(parse_size("64KB").unwrap(), 65536);
        assert_eq!(parse_size("2MB").unwrap(), 2 * 1024 * 1024);
        assert_eq!(parse_size("100").unwrap(), 100);
        assert!((parse_prob("2%").unwrap() - 0.02).abs() < 1e-12);
        assert!((parse_prob("0.25").unwrap() - 0.25).abs() < 1e-12);
        assert!(parse_prob("150%").is_err());
        assert!(parse_prob("-1").is_err());
        assert!(parse_prob("x%").is_err());
    }
    #[test]
    fn formatting() {
        assert_eq!(fmt_rate(2.5e6), "2.50 Mbit/s");
        assert_eq!(fmt_bytes(1536), "1.5 KiB");
    }
}
