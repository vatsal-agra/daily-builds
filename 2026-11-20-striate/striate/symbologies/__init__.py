from .common import Barcode, EncodeError
from . import code128, ean, code39, itf

NAMES = ["code128", "ean13", "upca", "ean8", "code39", "itf"]


def encode(kind, text, **opts):
    """Encode text as the named symbology; returns a Barcode."""
    k = kind.lower().replace("-", "").replace(" ", "").replace("_", "")
    if k == "code128":
        return code128.encode(text)
    if k == "ean13":
        return ean.encode_ean13(text)
    if k in ("upca", "upc"):
        return ean.encode_upca(text)
    if k == "ean8":
        return ean.encode_ean8(text)
    if k == "code39":
        return code39.encode(text, mod43=opts.get("mod43", False))
    if k in ("itf", "i25", "interleaved2of5"):
        return itf.encode(text, check=opts.get("check", False))
    raise EncodeError(f"unknown symbology {kind!r}; choose from {', '.join(NAMES)}")
