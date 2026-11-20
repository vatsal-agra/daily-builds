"""Striate — from-scratch 1D barcode encoder and image scanner (pure stdlib)."""
from .symbologies import encode, Barcode, EncodeError
from .scan import scan_image, Detection
from . import png, raster, svg

__all__ = ["encode", "Barcode", "EncodeError", "scan_image", "Detection", "png", "raster", "svg"]
__version__ = "1.0.0"
