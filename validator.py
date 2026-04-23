"""
validator.py
------------
Validates XML files against the chip_layout.xsd schema.
Returns structured result dicts consumed by both CLI and Streamlit.
"""

from pathlib import Path
from lxml import etree
import xmlschema
import time

SCHEMA_PATH = Path(__file__).parent / "schemas" / "chip_layout.xsd"

_schema_cache: xmlschema.XMLSchema | None = None


def _get_schema() -> xmlschema.XMLSchema:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = xmlschema.XMLSchema(str(SCHEMA_PATH))
    return _schema_cache


def validate_file(xml_path: str) -> dict:
    """
    Validate a single XML file against the XSD.

    Returns
    -------
    {
        "file":    str,
        "valid":   bool,
        "errors":  list[str],   # human-readable error messages
        "elapsed": float,       # seconds
        "stats":   dict,        # element counts extracted from XML
    }
    """
    t0 = time.perf_counter()
    schema = _get_schema()
    errors = []
    stats  = {}

    try:
        tree = etree.parse(xml_path)
        root = tree.getroot()

        # XSD validation
        try:
            schema.validate(xml_path)
        except xmlschema.XMLSchemaValidationError as exc:
            # Collect all errors (not just first)
            for err in schema.iter_errors(xml_path):
                errors.append(_format_error(err))

        # Extract stats even from invalid files (best effort)
        ns = {"tns": "http://amtc.example.com/ChipLayout"}
        stats = {
            "layout_id":    root.get("layout_id", "unknown"),
            "version":      root.get("version", "?"),
            "layers":       len(root.findall(".//tns:Layer",     ns)),
            "components":   len(root.findall(".//tns:Component", ns)),
            "test_points":  len(root.findall(".//tns:TestPoint", ns)),
            "project_name": _find_text(root, ".//tns:ProjectName", ns),
            "created_by":   _find_text(root, ".//tns:CreatedBy",   ns),
            "created_at":   _find_text(root, ".//tns:CreatedAt",   ns),
        }

    except etree.XMLSyntaxError as exc:
        errors.append(f"XML syntax error: {exc}")
    except Exception as exc:
        errors.append(f"Unexpected error: {exc}")

    return {
        "file":    str(xml_path),
        "valid":   len(errors) == 0,
        "errors":  errors,
        "elapsed": round(time.perf_counter() - t0, 4),
        "stats":   stats,
    }


def validate_directory(dir_path: str, pattern: str = "*.xml") -> list[dict]:
    """Validate all XML files matching pattern in a directory."""
    files = sorted(Path(dir_path).glob(pattern))
    return [validate_file(str(f)) for f in files]


def _find_text(root, xpath, ns) -> str:
    el = root.find(xpath, ns)
    return el.text if el is not None and el.text else ""


def _format_error(err: xmlschema.XMLSchemaValidationError) -> str:
    """Turn an xmlschema error into a readable one-liner."""
    reason = str(err.reason) if err.reason else str(err)
    path   = err.path or "unknown path"
    line   = f" (line {err.sourceline})" if err.sourceline else ""
    return f"[{path}]{line} {reason}"
