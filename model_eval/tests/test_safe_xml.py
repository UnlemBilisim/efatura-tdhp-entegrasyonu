import xml.etree.ElementTree as ET

import pytest

from core.safe_xml import reject_unsafe_xml, validate_tree_complexity


def test_dtd_and_entity_are_rejected():
    xml = '<!DOCTYPE x [<!ENTITY a "boom">]><Invoice>&a;</Invoice>'
    with pytest.raises(ET.ParseError, match="DTD"):
        reject_unsafe_xml(xml)


def test_normal_ubl_like_xml_is_allowed():
    reject_unsafe_xml("<Invoice><ID>1</ID></Invoice>")


def test_excessive_depth_is_rejected():
    root = ET.fromstring("<a><b><c/></b></a>")
    with pytest.raises(ET.ParseError, match="derinligi"):
        validate_tree_complexity(root, max_depth=2)


def test_excessive_element_count_is_rejected():
    root = ET.fromstring("<a><b/><c/></a>")
    with pytest.raises(ET.ParseError, match="eleman sayisini"):
        validate_tree_complexity(root, max_elements=2)
