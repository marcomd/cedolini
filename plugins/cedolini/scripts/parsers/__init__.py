from .base import detect_format, parse_pdf
# Import parser modules to trigger register_parser() calls
from . import sistemi, zucchetti, cud, hornet, adp_legacy, csspaghe  # noqa: F401
