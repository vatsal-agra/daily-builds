"""The DC-differential / AC-run-length symbol stream shared by frequency
counting (for optimized Huffman tables) and actual bitstream writing.

Both the "count what symbols this image would produce" pass and the
"actually write those symbols" pass need to derive *exactly* the same
sequence of (category, extra-bits) tokens from the same quantized
coefficients -- if they ever disagreed, an optimized table could be built
for symbols the writer doesn't actually emit. Factoring the token
sequence out into one function that both passes call removes that whole
class of bug by construction, rather than relying on two hand-written
copies staying in sync.
"""
from .bitstream import bits_for_value

DC = "dc"
AC = "ac"
ZRL = 0xF0  # AC run-length escape: 16 zero coefficients, no value follows
EOB = 0x00  # AC end-of-block: all remaining coefficients in this block are 0


def block_symbols(zigzag_block, prev_dc):
    """Given one block's 64 zigzag-order quantized coefficients and the
    running DC predictor for this component, return (new_dc_predictor,
    [(kind, symbol, extra_bits_value, extra_bits_count), ...]) -- exactly
    the tokens JPEG's baseline/progressive-DC-refinement entropy coder
    emits for this block.
    """
    tokens = []
    dc_diff = zigzag_block[0] - prev_dc
    nbits, coded = bits_for_value(dc_diff)
    tokens.append((DC, nbits, coded, nbits))

    run = 0
    for k in range(1, 64):
        v = zigzag_block[k]
        if v == 0:
            run += 1
            continue
        while run > 15:
            tokens.append((AC, ZRL, 0, 0))
            run -= 16
        nb, coded_ac = bits_for_value(v)
        symbol = (run << 4) | nb
        tokens.append((AC, symbol, coded_ac, nb))
        run = 0
    if run > 0:
        tokens.append((AC, EOB, 0, 0))

    return zigzag_block[0], tokens
