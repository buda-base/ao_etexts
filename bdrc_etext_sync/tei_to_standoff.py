"""
TEI/XML to standoff text conversion module.

This module provides functionality to convert TEI/XML format documents to plain text
with standoff annotations. It has minimal dependencies (only lxml and standard library).

Main API:
    text, annotations, source_path = convert_tei_root_to_standoff(tree)
"""

from lxml import etree
import re
import sys
from bisect import bisect
from copy import deepcopy as python_deepcopy
import logging

def deepcopy(element):
    """Helper function for deep copying XML elements."""
    return python_deepcopy(element)


def replace_element(old_element, new_element=None):
    """
    Replace or remove an XML element while preserving content structure.
    
    Args:
        old_element: The element to replace or remove
        new_element: The replacement element, or None to remove without replacement
    """
    parent = old_element.getparent()
    if parent is None:
        raise ValueError("Cannot replace/remove the root element")
    
    # Save the tail text from the old element
    tail_text = old_element.tail
    
    if new_element is None:
        # REMOVAL CASE
        # Find the node where we should append the tail text
        prev_sibling = old_element.getprevious()
        
        # Remove the old element
        parent.remove(old_element)
        
        # Handle the tail text
        if tail_text:
            if prev_sibling is not None:
                # Append to previous sibling's tail
                if prev_sibling.tail:
                    prev_sibling.tail += tail_text
                else:
                    prev_sibling.tail = tail_text
            else:
                # Append to parent's text
                if parent.text:
                    parent.text += tail_text
                else:
                    parent.text = tail_text
    else:
        # REPLACEMENT CASE
        # Set the tail on the new element
        new_element.tail = tail_text
        
        # Perform the replacement
        parent.replace(old_element, new_element)


def add_position_diff(positions, diffs, position, cumulative_diff):
    """Track position differences during text transformation."""
    if not positions or position > positions[-1]:
        positions.append(position)
        diffs.append(cumulative_diff)
    else:
        # case where we overwrite the latest diff
        diffs[-1] = cumulative_diff


def correct_position(current_position, positions, diffs):
    """Correct a position based on accumulated diffs."""
    previous_position_i = bisect(positions, current_position)
    if previous_position_i is None or previous_position_i < 1:
        return current_position
    return current_position + diffs[previous_position_i-1]


def apply_position_diffs(positions, diffs, annotations):
    """Apply position diffs to annotations, handling special keys appropriately."""
    for type, ann_list in annotations.items():
        if type == "milestones":
            # Milestones is a dict of id -> coordinate, correct each coordinate
            for milestone_id in ann_list:
                ann_list[milestone_id] = correct_position(ann_list[milestone_id], positions, diffs)
        else:
            # Regular annotations are lists of dicts with cstart/cend
            for ann in ann_list:
                ann["cstart"] = correct_position(ann["cstart"], positions, diffs)
                ann["cend"] = correct_position(ann["cend"], positions, diffs)


def get_string(orig, pattern_string, repl_fun, annotations):
    """
    Apply regex replacement to string while tracking position changes for annotations.
    
    Args:
        orig: Original string
        pattern_string: Regex pattern
        repl_fun: Replacement function that takes (match, output_len) and returns replacement
        annotations: Annotations dict to update with position diffs
    
    Returns:
        Transformed string
    """
    p = re.compile(pattern_string, flags=re.MULTILINE | re.DOTALL)
    # for diffs
    diffs = []
    positions = []
    output = ""
    output_len = 0
    cumulative = 0
    last_match_end = 0
    for m in p.finditer(orig):
        group_size = m.end() - m.start()
        skipped_size = m.start() - last_match_end
        output += orig[last_match_end:m.start()]
        last_match_end = m.end()
        output_len += skipped_size
        replacement = repl_fun(m, output_len)
        replacement_len = len(replacement)
        if replacement_len < group_size:
            ot_len = 0
            if 'ot' in m.groupdict():  # opening tag
                ot_len = len(m.group('ot'))
                add_position_diff(positions, diffs, m.start()+1, cumulative - ot_len)
            cumulative += replacement_len - group_size
            add_position_diff(positions, diffs, m.end(), cumulative)
        elif replacement_len > group_size:
            # when the replacement is large, new indexes point to
            # the last original index
            for i in range(group_size, replacement_len):
                cumulative -= 1
                add_position_diff(positions, diffs, output_len+i, cumulative)

        output += replacement
        output_len += replacement_len

    if last_match_end == 0:
        # no match (?)
        return orig

    if last_match_end < len(orig):
        output += orig[last_match_end:]

    apply_position_diffs(positions, diffs, annotations)
    return output


def convert_pages(text, annotations):
    """Replace <pb_marker>{pname}</pb_marker> with spacing and track page boundaries."""
    page_annotations = []
    
    def repl_pb_marker(m, cstart):
        pname = m.group("pname")
        # don't replace the first one
        repl = "\n\n" if cstart > 0 else ""
        page_annotations.append({"pname": pname, "cstart": cstart + 2 if cstart > 0 else 0})
        return repl
    
    pat_str = r'[\r\n\s]*<pb_marker>(?P<pname>.*?)</pb_marker>[\r\n\s]*'
    output = get_string(text, pat_str, repl_pb_marker, annotations)
    for i, p_ann in enumerate(page_annotations):
        p_ann["pnum"] = i+1
        # assert that the first page starts at the beginning
        if i < len(page_annotations)-1:
            p_ann["cend"] = page_annotations[i+1]["cstart"] - 2
        else:
            p_ann["cend"] = len(output)
    annotations["pages"] = page_annotations
    return output


def convert_milestones(text, annotations):
    """
    Replace <milestone_marker>{id}</milestone_marker> with empty string
    and track the milestone coordinates in annotations.
    Only consumes leading whitespace to avoid eating spacing between elements.
    """
    milestone_coords = {}
    
    def repl_milestone_marker(m, cstart):
        milestone_id = m.group("id")
        milestone_coords[milestone_id] = cstart
        return ""
    
    # Only consume leading whitespace, not trailing
    pat_str = r'[\r\n\s]*<milestone_marker>(?P<id>.*?)</milestone_marker>'
    output = get_string(text, pat_str, repl_milestone_marker, annotations)
    if milestone_coords:
        annotations["milestones"] = milestone_coords
    return output


def convert_div_boundaries(text, annotations):
    """
    Replace <div_start_marker/> and <div_end_marker/> with empty strings
    and track div boundaries for chunking.
    Div end markers add spacing to separate adjacent divs.
    """
    div_boundaries = []
    current_div_index = [-1]  # Use list to allow modification in nested function
    
    def repl_div_marker(m, cstart):
        marker = m.group(0)
        if 'div_start_marker' in marker:
            div_boundaries.append({"cstart": cstart, "cend": -1})
            current_div_index[0] += 1
            return ""  # No spacing needed at div start
        elif 'div_end_marker' in marker:
            if current_div_index[0] >= 0 and current_div_index[0] < len(div_boundaries):
                # Record the position before adding spacing
                div_boundaries[current_div_index[0]]["cend"] = cstart
            return "\n\n"  # Add spacing after div end to separate adjacent divs
        return ""
    
    # Remove both markers in one pass
    pat_str = r'<div_(start|end)_marker\s*/>'
    output = get_string(text, pat_str, repl_div_marker, annotations)
    
    # Filter out any incomplete boundaries
    div_boundaries = [b for b in div_boundaries if b["cend"] != -1]
    
    if div_boundaries:
        annotations["div_boundaries"] = div_boundaries
    return output


def convert_hi(text, annotations):
    """Replace <hi_{rend}>{content}</hi_{rend}> with {content} and save annotation coordinates."""
    if "hi" not in annotations:
        annotations["hi"] = []
    hi_annotations = annotations["hi"]
    
    def repl_hi_marker(m, cstart):
        rend = m.group("rend")
        hi_annotations.append({"rend": rend, "cstart": m.start(), "cend": m.end()})
        repl = m.group('content')
        return repl
    
    pat_str = r'(?P<ot><hi_(?P<rend>[^>]+)>)(?P<content>.*?)</hi_(?P=rend)>'
    output = get_string(text, pat_str, repl_hi_marker, annotations)
    return output


def remove_other_markers(text, annotations):
    """Remove all remaining XML markers."""
    def repl_xml_marker(m, cstart):
        return ""
    
    pat_str = r'</?[^>]*?>'
    output = get_string(text, pat_str, repl_xml_marker, annotations)
    return output


def normalize_new_lines(text, annotations):
    """Normalize newlines by removing surrounding whitespace."""
    def repl_nl_marker(m, cstart):
        return "\n"

    def repl_nl_marker_multi(m, cstart):
        return "\n\n"
    
    pat_str = r'[\t \r]*\n[\t \r]*'
    output = get_string(text, pat_str, repl_nl_marker, annotations)
    pat_str = r'\n{3,}'
    output = get_string(output, pat_str, repl_nl_marker_multi, annotations)
    return output


def unescape_xml(text, annotations):
    """Unescape XML entities."""
    # Common character entities
    simple_replacements = {
        '&quot;': '"',
        '&apos;': "'",
        '&lt;': '<',
        '&gt;': '>',
        '&amp;': '&'
    }

    def repl_esc_xml(m, cstart):
        escaped_entity = m.group(0)
        repl = ''
        if escaped_entity in simple_replacements:
            repl = simple_replacements[escaped_entity]
        else:
            num = escaped_entity[2:-1]
            repl = str(chr(int(num, 16)))
        return repl

    pat_str = r'&(quot|apos|lt|gt|amp|#\d+);'
    output = get_string(text, pat_str, repl_esc_xml, annotations)
    return output


def _shift_all_annotations(annotations, offset):
    """
    Shift all character coordinates by offset in place.
    Handles both list-based annotations, milestone dict, and div_boundaries.
    
    Args:
        annotations: The annotations dict to modify
        offset: The amount to shift coordinates (can be negative)
    """
    if not offset:
        return
    
    for key, anno_list in annotations.items():
        if key == "milestones":
            # Milestones is a dict of id -> coordinate
            for milestone_id in anno_list:
                new_pos = anno_list[milestone_id] + offset
                # Clamp to 0 if negative
                anno_list[milestone_id] = max(0, new_pos)
        else:
            # Regular annotations are lists of dicts with cstart/cend
            for anno in anno_list:
                if 'cstart' in anno:
                    anno['cstart'] = max(0, anno['cstart'] + offset)
                if 'cend' in anno:
                    anno['cend'] = max(0, anno['cend'] + offset)


def align_div_milestones_nl(text, annotations):
    """
    Adjust div boundaries to align with milestones and skip trailing newlines.
    
    This is a postprocessing step that ensures div boundaries properly align with
    milestones. The issue is that during the multi-step text transformation process,
    position tracking can become misaligned due to tag removal, whitespace normalization,
    etc. This function corrects the div boundaries as a final step.
    
    For each div, we adjust both cend and the next div's cstart to align with any
    milestones that fall between them. This ensures that milestones properly mark
    div boundaries.
    
    Args:
        text: The final text string
        annotations: The annotations dict with div_boundaries and milestones
    """
    div_boundaries = annotations.get("div_boundaries")
    milestones = annotations.get("milestones")
    
    if not div_boundaries or not milestones:
        return
    
    def _skip_newlines(position):
        while position < len(text) and text[position] == "\n":
            position += 1
        return position

    # Adjust milestones to skip newline characters
    for milestone_id, coord in milestones.items():
        milestones[milestone_id] = _skip_newlines(coord)

    # Adjust div boundaries (cend) to skip newline characters
    for boundary in div_boundaries:
        if "cend" in boundary and boundary["cend"] is not None:
            boundary["cend"] = _skip_newlines(boundary["cend"])

    # Get all milestone positions sorted once (after adjustment)
    milestone_positions = sorted(milestones.values())
    text_length = len(text)
    
    # For each div (except the last), check if there's a milestone between
    # its current end and the next div's start
    for i in range(len(div_boundaries) - 1):
        div = div_boundaries[i]
        next_div = div_boundaries[i + 1]
        current_end = div["cend"]
        next_start = next_div["cstart"]
        
        # Find milestones between this div's end and the next div's start (inclusive)
        # In the "new format", milestones can be exactly at div boundaries
        milestones_in_gap = [m for m in milestone_positions 
                            if current_end < m <= next_start and m <= text_length]
        
        if milestones_in_gap:
            # Use the first milestone as the boundary point
            boundary_pos = milestones_in_gap[0]
            # Extend this div to the milestone
            adjusted_boundary = _skip_newlines(boundary_pos)
            div["cend"] = adjusted_boundary
            # Move the next div's start to the milestone (also skip newlines)
            next_div["cstart"] = adjusted_boundary
    
    # Handle the last div - check if there's a milestone after its current end
    # but before the end of text (milestones at text_length are boundary markers)
    if div_boundaries:
        last_div = div_boundaries[-1]
        current_end = last_div["cend"]
        
        # Find milestones strictly after the last div's current end but before text end
        milestones_after = [m for m in milestone_positions 
                           if current_end < m < text_length]
        
        if milestones_after:
            adjusted_last = _skip_newlines(milestones_after[0])
            last_div["cend"] = adjusted_last


def _format_context_snippet(text, position, marker, radius=10):
    """Return a snippet of text around position with marker inserted."""
    position = max(0, min(len(text), position))
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    before = text[start:position]
    after = text[position:end]
    snippet = f"{before}{marker}{after}"
    return snippet.replace("\n", "\\n")


def _debug_log_annotations(text, annotations):
    """Emit detailed debug logs for milestones and div boundaries."""
    logger = logging.getLogger()
    if not logger.isEnabledFor(logging.DEBUG):
        return

    milestones = annotations.get("milestones", {})
    if milestones:
        logger.debug("Milestones (%d entries):", len(milestones))
        for milestone_id, coord in sorted(milestones.items(), key=lambda item: item[1]):
            marker = f'<id="{milestone_id}">'  # no closing tag per requirements
            snippet = _format_context_snippet(text, coord, marker)
            logger.debug("  %s at %d -> %s", milestone_id, coord, snippet)
    else:
        logger.debug("Milestones: none found")

    divs = annotations.get("div_boundaries", [])
    if divs:
        logger.debug("Div boundaries (%d entries):", len(divs))
        for idx, div in enumerate(divs, start=1):
            cstart = div.get("cstart", 0)
            cend = div.get("cend", 0)
            start_marker = f'<div_{idx}_start>'
            end_marker = f'<div_{idx}_end>'
            start_snippet = _format_context_snippet(text, cstart, start_marker)
            end_snippet = _format_context_snippet(text, cend, end_marker)
            logger.debug("  Div %d start %d -> %s", idx, cstart, start_snippet)
            logger.debug("  Div %d end %d -> %s", idx, cend, end_snippet)
    else:
        logger.debug("Div boundaries: none found")


def trim_text_and_adjust_annotations(text, annotations):
    """
    Remove leading and trailing whitespace from text and adjust annotation coordinates.
    
    Args:
        text: The text string to trim
        annotations: The annotations dict to adjust
    
    Returns:
        Trimmed text string
    """
    # Calculate how much we're trimming from the beginning
    s_count = len(re.match(r'^[\s\n]*', text).group())
    
    # Trim leading whitespace
    if s_count > 0:
        # Shift annotations by negative offset (subtract the trimmed amount)
        _shift_all_annotations(annotations, -s_count)
        text = text[s_count:]
    
    # Trim trailing whitespace
    e_match = re.search(r'[\s\n]*$', text)
    if e_match and e_match.group():
        e_count = len(e_match.group())
        if e_count > 0:
            # New text length after trimming
            new_length = len(text) - e_count
            text = text[:new_length]
            
            # Adjust any annotations that extend beyond the new end
            # (though this shouldn't normally happen)
            for key, anno_list in annotations.items():
                if key == "milestones":
                    # Milestones are a dict of id -> coordinate
                    for milestone_id in anno_list:
                        if anno_list[milestone_id] > new_length:
                            anno_list[milestone_id] = new_length
                else:
                    # Regular annotations are lists of dicts with cstart/cend
                    for anno in anno_list:
                        if 'cstart' in anno and anno['cstart'] > new_length:
                            anno['cstart'] = new_length
                        if 'cend' in anno and anno['cend'] > new_length:
                            anno['cend'] = new_length
    
    return text


def convert_tei_root_to_standoff(root):
    """
    Convert a TEI/XML file to plain text with standoff annotations.
    
    Conversion rules:
    - Only content within the body tags is processed
    - Line breaks (<lb/>) become newline characters
    - Page breaks (<pb/>) become two newline characters
    - Notes (<note>...</note>) are removed
    - <figure><caption><p>foo</p></caption></figure> becomes "foo"
    - <gap /> elements are removed
    - <unclear><supplied>foo</supplied></unclear> becomes "foo"
    - <choice><orig>foo</orig><corr>bar</corr></choice> becomes "bar"
    - Milestones are tracked in annotations but removed from text
    - Head elements are converted to hi annotations with rend='head'
    - All other XML tags are stripped
    - XML-encoded characters (&gt;, etc.) are converted to their normal representation
    
    Args:
        root: an etree root element
        
    Returns:
        tuple: (text, annotations, source_path)
            - text: String containing the plain text representation
            - annotations: Dict representing the annotations
            - source_path: The path of the source file (or None)
    """
    # Find the body element (handle TEI namespace if present)
    namespaces = {'tei': 'http://www.tei-c.org/ns/1.0'}

    source_path = root.xpath('//tei:idno[@type="src_path"]/text()', namespaces=namespaces)
    source_path = source_path[0] if source_path else None

    body = root.xpath('//tei:body', namespaces=namespaces)
        
    if not body:
        logging.error("No body element found in the TEI document")
        return None, None, None
    
    # Check if xml:space="preserve" is present
    xml_space_preserve = body[0].get('{http://www.w3.org/XML/1998/namespace}space') == 'preserve'
    
    # Create a deep copy of the body to avoid modifying the original tree
    body_copy = etree.Element("body")
    body_copy.extend(body[0].xpath("./*"))
    
    # Process the TEI elements
    
    # Handle div elements - mark boundaries for chunking if not xml:space="preserve"
    if not xml_space_preserve:
        for div in body_copy.xpath('.//tei:div', namespaces=namespaces):
            # Add markers to track div boundaries
            div_start_marker = etree.Element("div_start_marker")
            div_end_marker = etree.Element("div_end_marker")
            
            # Insert start marker as first child
            if len(div) > 0:
                div.insert(0, div_start_marker)
            else:
                div_start_marker.text = div.text if div.text else ""
                div.text = ""
                div.append(div_start_marker)
            
            # Append end marker as last child
            div.append(div_end_marker)
    
    # Handle milestone elements - convert to markers for coordinate tracking
    for milestone in body_copy.xpath('.//tei:milestone', namespaces=namespaces):
        milestone_id = milestone.get('{http://www.w3.org/XML/1998/namespace}id')
        if milestone_id:
            milestone_marker = etree.Element("milestone_marker")
            milestone_marker.text = milestone_id
            replace_element(milestone, milestone_marker)
        else:
            replace_element(milestone, None)
    
    # Handle head elements - convert to hi_head for annotation tracking
    for head in body_copy.xpath('.//tei:head', namespaces=namespaces):
        new_tag = etree.Element('hi_head')
        new_tag.text = head.text
        for child in head:
            new_tag.append(deepcopy(child))
        new_tag.tail = head.tail
        replace_element(head, new_tag)

    # Remove all note elements
    for note in body_copy.xpath('.//tei:note', namespaces=namespaces):
        replace_element(note, None)

    # Remove all gap elements
    for gap in body_copy.xpath('.//tei:gap', namespaces=namespaces):
        text_element = etree.Element("text_marker")
        text_element.text = "X"
        replace_element(gap, text_element)
    
    # Process figure elements - extract caption text
    for figure in body_copy.xpath('.//tei:figure', namespaces=namespaces):
        caption_text = ""
        captions = figure.xpath('.//tei:caption//text()', namespaces=namespaces)
        if captions:
            caption_text = " ".join([t.strip() for t in captions if t.strip()])
        
        text_element = etree.Element("text_marker")
        text_element.text = caption_text
        replace_element(figure, text_element)

    for hi in body_copy.xpath('.//tei:hi', namespaces=namespaces):
        render_val = hi.get('rend')
        if not render_val:
            render_val = ""
        # Create new element with the format hi_xxx
        new_tag = etree.Element(f'hi_{render_val}')
        # Copy the text content
        new_tag.text = hi.text
        # Copy all child elements
        for child in hi:
            new_tag.append(deepcopy(child))
        # Copy any tail text
        new_tag.tail = hi.tail
        replace_element(hi, new_tag)

    # Process unclear/supplied elements - keep supplied text
    for unclear in body_copy.xpath('.//tei:unclear', namespaces=namespaces):
        text = "".join(unclear.itertext())
        text_element = etree.Element("hi_unclear")
        text_element.text = text
        replace_element(unclear, text_element)
    
    # Process choice elements - use corr instead of orig
    for choice in body_copy.xpath('.//tei:choice', namespaces=namespaces):
        corr = choice.xpath('.//tei:corr', namespaces=namespaces)
        if corr:
            text = "".join(corr[0].itertext())
            text_element = etree.Element("text_marker")
            text_element.text = text
            replace_element(choice, text_element)
    
    # Replace all pb elements with custom markers
    for pb in body_copy.xpath('.//tei:pb', namespaces=namespaces):
        pb_marker = etree.Element("pb_marker")
        pnum = pb.get('n')
        if pnum:
            pb_marker.text = pnum
        replace_element(pb, pb_marker)
    
    # Replace all lb elements with custom markers
    for lb in body_copy.xpath('.//tei:lb', namespaces=namespaces):
        lb_marker = etree.Element("lb_marker")
        lb_marker.text = "\n"
        replace_element(lb, lb_marker)
        
    # Get the text content
    etree.cleanup_namespaces(body_copy, top_nsmap={None: "http://www.tei-c.org/ns/1.0"})
    xml_str = etree.tostring(body_copy, encoding="unicode", method="xml", pretty_print=False)
    
    # Simple substitutions
    xml_str = xml_str.replace("\uFEFF", "")
    # Handle div and p tags based on xml:space attribute
    if xml_space_preserve:
        # Old behavior: just remove tags, normalize spaces at beginning and end
        xml_str = re.sub(r'[\r\n\t ]*</?(?:body|p|div)(?: +[^>]+)*>[\r\n\t ]*', "", xml_str, flags=re.DOTALL)
    else:
        # New behavior: add two line breaks around divs and ps
        xml_str = re.sub(r'<div(?: +[^>]+)*>', "\n\n", xml_str, flags=re.DOTALL)
        xml_str = re.sub(r'</div>', "\n\n", xml_str, flags=re.DOTALL)
        xml_str = re.sub(r'<p(?: +[^>]+)*>', "\n\n", xml_str, flags=re.DOTALL)
        xml_str = re.sub(r'</p>', "\n\n", xml_str, flags=re.DOTALL)
        xml_str = re.sub(r'</?body(?: +[^>]+)*>', "", xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'(?:\n\s*)?<text_marker>(.*?)</text_marker>(?:\n\s*)?', r'\1', xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'[\r\n\t ]*<lb_marker>(.*?)</lb_marker>[\r\n\t ]*', r'\1', xml_str, flags=re.DOTALL)

    annotations = {}
    if not xml_space_preserve:
        xml_str = convert_div_boundaries(xml_str, annotations)
    xml_str = convert_milestones(xml_str, annotations)
    xml_str = convert_pages(xml_str, annotations)
    xml_str = convert_hi(xml_str, annotations)
    xml_str = remove_other_markers(xml_str, annotations)
    xml_str = unescape_xml(xml_str, annotations)
    xml_str = normalize_new_lines(xml_str, annotations)
    
    # Trim leading and trailing whitespace and adjust annotations
    xml_str = trim_text_and_adjust_annotations(xml_str, annotations)
    
    # Align div boundaries with milestones (postprocessing)
    if not xml_space_preserve:
        align_div_milestones_nl(xml_str, annotations)
    
    _debug_log_annotations(xml_str, annotations)

    return xml_str, annotations, source_path


def convert_tei_to_standoff(xml_file_path):
    """
    Convert a TEI/XML file to plain text with standoff annotations.
    
    Args:
        xml_file_path: Path to the XML file
        
    Returns:
        tuple: (text, annotations, source_path)
    """
    # Parse the XML file
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    tree = etree.parse(xml_file_path, parser)
    root = tree.getroot()
    return convert_tei_root_to_standoff(root)
