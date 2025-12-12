"""
TEI subset validation module.

This module validates that XML files only use tags and attributes that are
documented in the conventions expressed in doc/. Any tag or attribute that is
undocumented in the documentation should be considered an error, both in the
header and body.
"""

import logging
from lxml import etree
from typing import List, Tuple


# Allowed tags in the TEI header (from doc/tei_xml_spec_header.md)
ALLOWED_HEADER_TAGS = {
    'teiHeader',
    'fileDesc',
    'titleStmt',
    'title',
    'publicationStmt',
    'p',
    'sourceDesc',
    'bibl',
    'idno',
    'encodingDesc',
    'ref',
}

# Allowed tags in the TEI body (from doc/tei_xml_spec_paginated.md)
ALLOWED_BODY_TAGS = {
    'TEI',
    'text',
    'body',
    'p',
    'pb',
    'lb',
    'note',
    'milestone',
    'figure',
    'head',
    'gap',
    'unclear',
    'hi',
    'choice',
    'orig',
    'corr',
    'reg',
    'abbr',
    'expan',
}

# Allowed attributes per tag (from documentation)
# Format: {tag_name: {set of allowed attribute names}}
ALLOWED_ATTRIBUTES = {
    # Header attributes
    'idno': {'type'},  # type="src_path", "src_sha256", "bdrc_ie", "bdrc_ve", "bdrc_ut"
    'ref': {'target'},
    
    # Body attributes
    'body': {'xml:lang'},
    'p': {'xml:space'},
    'pb': {'n'},  # n="1a", "1b", etc.
    'note': {'type', 'xml:lang'},  # type="editorial", xml:lang for language
    'milestone': {'xml:id', 'unit'},  # xml:id="XXX", unit="section"
    'head': {'xml:lang'},
    'gap': {'reason', 'unit', 'quantity'},  # reason="illegible", unit="syllable", quantity="N"
    'unclear': {'reason', 'cert'},  # reason="illegible", cert="low|medium|high"
    'hi': {'rend', 'type'},  # rend="small", type="italic|bold|head|head_1|head_2|..."
    'corr': {'cert'},  # cert="low|medium|high"
}

# XML namespace (standard attributes that are always allowed)
# These are the local names (without xml: prefix) of XML namespace attributes
XML_NAMESPACE_ATTR_LOCAL_NAMES = {'lang', 'space', 'id'}

# TEI namespace
TEI_NAMESPACE = 'http://www.tei-c.org/ns/1.0'


def _get_local_name(tag: str) -> str:
    """Extract local name from a namespaced tag."""
    if '}' in tag:
        return tag.split('}')[1]
    return tag


def _get_attribute_name(attr: str) -> str:
    """Extract local name from a namespaced attribute."""
    if '}' in attr:
        return attr.split('}')[1]
    return attr


def _is_in_header(element: etree._Element) -> bool:
    """Check if an element is in the TEI header section."""
    current = element
    while current is not None:
        local_name = _get_local_name(current.tag)
        if local_name == 'teiHeader':
            return True
        if local_name in ('body', 'text', 'TEI'):
            return False
        current = current.getparent()
    return False


def validate_tei_root_subset(root: etree._Element, filepath: str = None) -> Tuple[List[str], List[str]]:
    """
    Validate that the XML root element only uses documented tags and attributes.
    
    Args:
        root: Parsed lxml etree root element
        filepath: Optional filepath for error messages (if None, errors won't include filepath prefix)
        
    Returns:
        tuple: (errors, warnings) where each is a list of error/warning messages
    """
    logger = logging.getLogger(__name__)
    file_display = filepath if filepath else "XML root"
    logger.debug("Validating TEI subset for %s", file_display)
    
    errors = []
    warnings = []
    
    try:
        # Get namespace map
        nsmap = root.nsmap if hasattr(root, 'nsmap') else {}
        logger.debug("Namespace map: %s", nsmap)
        
        # Check if TEI namespace is used
        tei_ns_used = False
        if 'tei' in nsmap and nsmap['tei'] == TEI_NAMESPACE:
            tei_ns_used = True
        elif None in nsmap and nsmap[None] == TEI_NAMESPACE:
            tei_ns_used = True
        
        if tei_ns_used:
            logger.debug("TEI namespace detected")
        else:
            logger.debug("TEI namespace not detected (may use default namespace)")
        
        element_count = 0
        # Iterate through all elements in the document
        for element in root.iter():
            element_count += 1
            local_name = _get_local_name(element.tag)
            is_header = _is_in_header(element)
            
            # Determine which set of allowed tags to check against
            if is_header:
                allowed_tags = ALLOWED_HEADER_TAGS
            else:
                allowed_tags = ALLOWED_BODY_TAGS
            
            # Check if tag is allowed
            if local_name not in allowed_tags:
                # Get element location for better error reporting
                line_num = element.sourceline if hasattr(element, 'sourceline') and element.sourceline else 'unknown'
                if filepath:
                    location = f"{filepath}:{line_num}"
                else:
                    location = f"line {line_num}"
                error_msg = (
                    f"{location}: Undocumented tag '<{local_name}>' found in "
                    f"{'header' if is_header else 'body'}"
                )
                logger.debug("  Found undocumented tag: %s at %s", local_name, location)
                errors.append(error_msg)
            
            # Check attributes
            for attr_name, attr_value in element.attrib.items():
                attr_local = _get_attribute_name(attr_name)
                
                # XML namespace attributes are always allowed
                # These can appear as 'xml:lang', '{http://www.w3.org/XML/1998/namespace}lang', etc.
                # Also allow xmlns attributes (namespace declarations)
                if (attr_local in XML_NAMESPACE_ATTR_LOCAL_NAMES or 
                    attr_name.startswith('xml:') or 
                    attr_name.startswith('{http://www.w3.org/XML/1998/namespace}') or
                    attr_name == 'xmlns' or attr_name.startswith('xmlns:')):
                    continue
                
                # Check if attribute is allowed for this tag
                allowed_attrs = ALLOWED_ATTRIBUTES.get(local_name, set())
                
                if attr_local not in allowed_attrs:
                    # Get element location for better error reporting
                    line_num = element.sourceline if hasattr(element, 'sourceline') and element.sourceline else 'unknown'
                    if filepath:
                        location = f"{filepath}:{line_num}"
                    else:
                        location = f"line {line_num}"
                    error_msg = (
                        f"{location}: Undocumented attribute '{attr_local}' on "
                        f"tag '<{local_name}>' in {'header' if is_header else 'body'}"
                    )
                    logger.debug("  Found undocumented attribute: %s on %s at %s", attr_local, local_name, location)
                    errors.append(error_msg)
        
        logger.debug("Checked %d element(s) in %s", element_count, file_display)
        if errors:
            logger.info("TEI subset validation for %s: %d error(s) found", file_display, len(errors))
        else:
            logger.debug("TEI subset validation for %s: passed", file_display)
        
        return errors, warnings
        
    except Exception as e:
        logger.error("Error validating TEI subset for %s: %s", file_display, str(e), exc_info=True)
        if filepath:
            return [f"{filepath}: Error processing file: {str(e)}"], []
        else:
            return [f"Error processing file: {str(e)}"], []


def validate_tei_subset(filepath: str) -> Tuple[List[str], List[str]]:
    """
    Validate that the XML file only uses documented tags and attributes.
    
    Args:
        filepath: Path to the TEI XML file
        
    Returns:
        tuple: (errors, warnings) where each is a list of error/warning messages
    """
    logger = logging.getLogger(__name__)
    logger.debug("Parsing XML file for TEI subset validation: %s", filepath)
    
    try:
        # Parse the XML file
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(filepath, parser)
        root = tree.getroot()
        logger.debug("Successfully parsed XML file: %s", filepath)
        
        # Use the root-based validation function
        return validate_tei_root_subset(root, filepath)
        
    except etree.XMLSyntaxError as e:
        logger.error("XML syntax error in %s: %s", filepath, str(e))
        return [f"{filepath}: XML syntax error: {str(e)}"], []
    except Exception as e:
        logger.error("Error parsing file %s: %s", filepath, str(e), exc_info=True)
        return [f"{filepath}: Error parsing file: {str(e)}"], []

