"""
Hand-written big-integer number theory: modular exponentiation via
square-and-multiply, the extended Euclidean algorithm, modular inverse,
Miller-Rabin primality testing, random prime generation, and the Chinese
Remainder Theorem. Python's arbitrary-precision `int` is used as storage
(reimplementing schoolbook long division would make RSA keygen
impractically slow without teaching anything new) but every *algorithm*
here is written from the definition, not delegated to a math library.
"""
import os


def modexp(base, exp, mod):
    """Square-and-multiply modular exponentiation: base**exp % mod."""
    if mod == 1:
        return 0
    if exp < 0:
        base = modinv(base, mod)
        exp = -exp
    result = 1
    base %= mod
    while exp > 0:
        if exp & 1:
            result = (result * base) % mod
        base = (base * base) % mod
        exp >>= 1
    return result


def egcd(a, b):
    """Extended Euclidean algorithm. Returns (g, x, y) with a*x + b*y = g = gcd(a, b)."""
    old_r, r = a, b
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
        old_t, t = t, old_t - q * t
    return old_r, old_s, old_t


def modinv(a, m):
    """Modular multiplicative inverse of a mod m via extended Euclid."""
    a %= m
    g, x, _ = egcd(a, m)
    if g != 1:
        raise ValueError(f"modular inverse does not exist: gcd({a}, {m}) = {g}")
    return x % m


_SMALL_PRIMES = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67,
    71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139,
    149, 151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223,
    227, 229, 233, 239, 241, 251,
]


def is_probable_prime(n, rounds=40, rng=None):
    """Miller-Rabin probabilistic primality test. False-positive
    probability is at most 4**-rounds."""
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n == p:
            return True
        if n % p == 0:
            return False

    # write n - 1 = 2^r * d with d odd
    r, d = 0, n - 1
    while d % 2 == 0:
        d //= 2
        r += 1

    rand_below = (rng.randrange if rng is not None else _os_randrange)
    for _ in range(rounds):
        a = rand_below(2, n - 1)
        x = modexp(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = modexp(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _os_randrange(lo, hi):
    """Uniform random integer in [lo, hi] using os.urandom (no `random` module)."""
    span = hi - lo
    if span <= 0:
        return lo
    nbytes = (span.bit_length() + 7) // 8 + 1
    while True:
        raw = int.from_bytes(os.urandom(nbytes), "big")
        if raw <= span * ((1 << (nbytes * 8)) // (span + 1)):
            return lo + raw % (span + 1)


def gen_prime(bits, rng=None):
    """Generate a random `bits`-bit probable prime with the top two bits
    and the bottom bit set (standard RSA-prime shaping)."""
    if bits < 8:
        raise ValueError("bits must be >= 8")
    rand_bits = (rng.getrandbits if rng is not None else _os_getrandbits)
    while True:
        cand = rand_bits(bits)
        cand |= (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if is_probable_prime(cand, rng=rng):
            return cand


def _os_getrandbits(bits):
    nbytes = (bits + 7) // 8
    raw = int.from_bytes(os.urandom(nbytes), "big")
    return raw & ((1 << bits) - 1)


def crt(residues, moduli):
    """Chinese Remainder Theorem: given x = residues[i] (mod moduli[i])
    for pairwise-coprime moduli, return the unique x mod prod(moduli)."""
    if len(residues) != len(moduli):
        raise ValueError("residues and moduli must have the same length")
    M = 1
    for m in moduli:
        M *= m
    x = 0
    for r_i, m_i in zip(residues, moduli):
        M_i = M // m_i
        x += r_i * M_i * modinv(M_i, m_i)
    return x % M


def bytes_to_int(b):
    return int.from_bytes(b, "big")


def int_to_bytes(n, length):
    return n.to_bytes(length, "big")
