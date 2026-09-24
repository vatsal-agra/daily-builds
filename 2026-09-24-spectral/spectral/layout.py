"""MCU (Minimum Coded Unit) geometry shared by the baseline and
progressive encoders/decoders.

JPEG interleaves multiple color components into a single scan by tiling
the image into MCUs: each MCU is an (8*Hmax) x (8*Vmax) pixel region
where Hmax/Vmax are the largest per-component sampling factors, and it
contains Hi*Vi 8x8 blocks of each component i. A component with a smaller
sampling factor than the max (chroma, when subsampled) contributes fewer
blocks per MCU -- that's the entire mechanism by which chroma
subsampling reduces file size: fewer blocks means fewer DCTs, fewer
quantized coefficients, and fewer Huffman-coded bits.
"""

SUBSAMPLING_FACTORS = {
    "444": (1, 1),  # no chroma subsampling
    "422": (2, 1),  # halved horizontally
    "420": (2, 2),  # halved in both directions (most common on the web)
}

COMPONENT_IDS = {"Y": 1, "Cb": 2, "Cr": 3}


def _ceil_div(a, b):
    return -(-a // b)


def compute_layout(width, height, subsampling):
    if subsampling not in SUBSAMPLING_FACTORS:
        raise ValueError(
            f"unknown subsampling mode {subsampling!r} (expected one of {sorted(SUBSAMPLING_FACTORS)})"
        )
    luma_h, luma_v = SUBSAMPLING_FACTORS[subsampling]
    hmax, vmax = luma_h, luma_v
    mcu_w, mcu_h = 8 * hmax, 8 * vmax
    mcus_x = _ceil_div(width, mcu_w)
    mcus_y = _ceil_div(height, mcu_h)

    components = []
    for name, h, v, qkind in (
        ("Y", luma_h, luma_v, "luma"),
        ("Cb", 1, 1, "chroma"),
        ("Cr", 1, 1, "chroma"),
    ):
        blocks_x = mcus_x * h
        blocks_y = mcus_y * v
        components.append({
            "name": name,
            "id": COMPONENT_IDS[name],
            "h": h,
            "v": v,
            "qkind": qkind,
            "blocks_x": blocks_x,
            "blocks_y": blocks_y,
            "padded_w": blocks_x * 8,
            "padded_h": blocks_y * 8,
            "hsub": hmax // h,
            "vsub": vmax // v,
        })

    return {
        "width": width,
        "height": height,
        "hmax": hmax,
        "vmax": vmax,
        "mcus_x": mcus_x,
        "mcus_y": mcus_y,
        "components": components,
    }


def noninterleaved_block_grid(width, height, hmax, vmax, comp):
    """The block grid a *non-interleaved* (single-component) scan covers
    -- required for progressive AC scans, which JPEG restricts to one
    component at a time. This is generally *smaller* than the
    interleaved grid (comp['blocks_x'/'blocks_y']): interleaved scans
    always code the full MCU-rounded grid (padding blocks included) so
    every component's block count stays in lockstep every MCU, but a
    non-interleaved scan has no such constraint and the spec (T.81
    A.2.4) defines it to cover only the component's own real (non-
    padding) resolution, rounded up to whole 8x8 blocks. Getting this
    wrong desyncs a real decoder's block count from what was actually
    encoded.
    """
    comp_w = -(-(width * comp["h"]) // hmax)
    comp_h = -(-(height * comp["v"]) // vmax)
    return -(-comp_w // 8), -(-comp_h // 8)


def iter_mcu_blocks(layout):
    """Yields (component_name, block_x, block_y) in MCU-interleaved order,
    matching JPEG's required scan order for an interleaved (multi-
    component) scan.
    """
    for my in range(layout["mcus_y"]):
        for mx in range(layout["mcus_x"]):
            for comp in layout["components"]:
                for v in range(comp["v"]):
                    by = my * comp["v"] + v
                    for h in range(comp["h"]):
                        bx = mx * comp["h"] + h
                        yield comp["name"], bx, by
