"""ADSR envelope generator.

Computes the envelope as a float list without a per-sample Python loop for the
attack/decay/sustain/release segments (uses list comprehensions instead).
The filter loop must still be per-sample, but the envelope itself is batch.
"""


def compute_adsr(
    gate_samples: int,
    release_samples: int,
    attack_s: float,
    decay_s: float,
    sustain_level: float,
    release_s: float,
    sr: int,
) -> list:
    """Return a float list of length gate_samples + release_n.

    The envelope rises to 1 in the attack, falls to sustain_level in the decay,
    holds sustain until the gate closes, then releases from the actual gate-off
    level (which may be < sustain if the gate closes during attack/decay).
    """
    if gate_samples <= 0:
        release_n = max(int(release_s * sr), 1)
        return [0.0] * release_n

    attack_n_natural = max(int(attack_s * sr), 1)
    attack_n = min(attack_n_natural, gate_samples)
    decay_n_natural = max(int(decay_s * sr), 0)
    decay_n = min(decay_n_natural, gate_samples - attack_n)
    sustain_n = gate_samples - attack_n - decay_n
    release_n = max(int(release_s * sr), 1)

    # Level at gate-off — use natural (uncompressed) durations for correct scaling
    if gate_samples <= attack_n_natural:
        gate_off = gate_samples / attack_n_natural
    elif gate_samples <= attack_n_natural + decay_n_natural:
        t = (gate_samples - attack_n_natural) / max(decay_n_natural, 1)
        gate_off = 1.0 - (1.0 - sustain_level) * t
    else:
        gate_off = sustain_level

    # Build each segment; ramp attack over natural length so gate_off < 1 when gate closes early
    attack_env = [(i + 1) / attack_n_natural for i in range(attack_n)]
    decay_env = [1.0 - (1.0 - sustain_level) * (i + 1) / decay_n_natural
                 for i in range(decay_n)] if decay_n else []
    sustain_env = [sustain_level] * sustain_n
    release_env = [gate_off * (1.0 - (i + 1) / release_n)
                   for i in range(release_n)] if release_n else [0.0]

    return attack_env + decay_env + sustain_env + release_env


def apply_env(samples: list, env: list) -> list:
    """Element-wise multiply samples by envelope (truncating to the shorter)."""
    n = min(len(samples), len(env))
    return [samples[i] * env[i] for i in range(n)]
