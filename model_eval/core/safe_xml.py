"""UBL girdileri icin DTD/entity genislemesini parser'dan once engeller."""

import re
import xml.etree.ElementTree as ET

_FORBIDDEN_DECLARATION = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def reject_unsafe_xml(xml_text: str) -> None:
    if _FORBIDDEN_DECLARATION.search(xml_text):
        raise ET.ParseError("DTD ve ENTITY bildirimlerine izin verilmiyor")


def validate_tree_complexity(
    root: ET.Element,
    *,
    max_elements: int = 100_000,
    max_depth: int = 128,
) -> None:
    """Asiri buyuk veya derin agaclarin CPU/bellek tuketmesini sinirlar."""
    seen = 0
    stack = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        seen += 1
        if seen > max_elements:
            raise ET.ParseError("XML izin verilen eleman sayisini asiyor")
        if depth > max_depth:
            raise ET.ParseError("XML izin verilen derinligi asiyor")
        stack.extend((child, depth + 1) for child in element)
