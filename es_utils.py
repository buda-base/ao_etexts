from lxml import etree
import re
import sys
import html
import re
from bisect import bisect

DEBUG = False

def add_position_diff(positions, diffs, position, cumulative_diff):
    if not positions or position > positions[-1]:
        positions.append(position)
        diffs.append(cumulative_diff)
    else:
        # case where we overwrite the latest diff
        diffs[-1] = cumulative_diff

def correct_position(current_position, positions, diffs):
    previous_position_i = bisect(positions, current_position)
    if previous_position_i is None or previous_position_i < 1:
        return current_position
    return current_position + diffs[previous_position_i-1]

def apply_position_diffs(positions, diffs, annotations):
    for type, ann_list in annotations.items():
        for ann in ann_list:
            ann["c_start"] = correct_position(ann["c_start"], positions, diffs)
            ann["c_end"] = correct_position(ann["c_end"], positions, diffs) 

def get_string(orig, pattern_string , repl_fun, annotations):
    p = re.compile(pattern_string, flags = re.MULTILINE | re.DOTALL)
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
            if 'ot' in m.groupdict(): # opening tag
                ot_len = len(m.group('ot'))
                add_position_diff(positions, diffs, m.start()+1, cumulative - ot_len)
            cumulative += replacement_len - group_size
            add_position_diff(positions, diffs, m.end(), cumulative)
        elif replacement_len > group_size:
            # when the replacement is large, new indexes point to
            # the last original index
            # TODO: not sure what's supposed to happen with 'ot' here
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

    if DEBUG:
        print("\n\nXXX\n\n")
        print(positions, diffs)
        print(output)
        debug_annotations(output, annotations)
    apply_position_diffs(positions, diffs, annotations)
    if DEBUG:
        print("\n\nYYY\n\n")
        debug_annotations(output, annotations)
        print("\n\nZZZ\n\n")
    return output

def debug_annotations(text, annotations):
    # Create a list of annotation boundaries to insert
    boundaries = []
    
    for anno_type, anno_list in annotations.items():
        for anno in anno_list:
            # Store both the position and what to insert
            boundaries.append((anno['c_start'], f"[{anno_type}]"))
            boundaries.append((anno['c_end'], f"[/{anno_type}]"))
    
    # Sort boundaries by position (descending)
    # We process from end to beginning to avoid shifting positions
    boundaries.sort(reverse=True)
    
    # Insert the markers
    result = text
    for position, marker in boundaries:
        result = result[:position] + marker + result[position:]
    return result

def convert_pages(text, annotations):
    """
    replaces <pb_marker>{pname}</pb_marker> with 
    """
    page_annotations = []
    def repl_pb_marker(m, c_start):
        pname = m.group("pname")
        c_start = c_start
        # don't replace the first one
        repl = "\n\n" if c_start > 0 else ""
        page_annotations.append({"pname": pname, "c_start": c_start + 2 if c_start > 0 else 0})
        return repl
    pat_str = r'[\r\n\s]*<pb_marker>(?P<pname>.*?)</pb_marker>[\r\n\s]*'
    output = get_string(text, pat_str, repl_pb_marker, annotations)
    for i, p_ann in enumerate(page_annotations):
        p_ann["pnum"] = i+1
        # assert that the first page starts at the beginning
        if i < len(page_annotations)-1:
            p_ann["c_end"] = page_annotations[i+1]["c_start"] - 2
        else:
            p_ann["c_end"] = len(output)
    annotations["pages"] = page_annotations
    return output

def convert_hi(text, annotations):
    """
    replaces <hi_{rend}>{content}</hi_{rend}> with {content} and saves annotation text coordinates 
    """
    if "hi" not in annotations:
        annotations["hi"] = []
    hi_annotations = annotations["hi"]
    def repl_hi_marker(m, c_start):
        rend = m.group("rend")
        hi_annotations.append({"rend": rend, "c_start": m.start(), "c_end": m.end()})
        repl = m.group('content')
        return repl
    pat_str = r'(?P<ot><hi_(?P<rend>[^>]+)>)(?P<content>.*?)</hi_(?P=rend)>'
    output = get_string(text, pat_str, repl_hi_marker, annotations)
    return output

def remove_other_markers(text, annotations):
    """
    remove all xml markers
    """
    def repl_xml_marker(m, c_start):
        return ""
    pat_str = r'</?[^>]*?>'
    output = get_string(text, pat_str, repl_xml_marker, annotations)
    return output

def normalize_new_lines(text, annotations):
    """
    remove all xml markers
    """
    def repl_nl_marker(m, c_start):
        return "\n"
    pat_str = r'[\t \r]*\n[\t \r]*'
    output = get_string(text, pat_str, repl_nl_marker, annotations)
    return output

def unescape_xml(text, annotations):
    # Common character entities
    simple_replacements = {
        '&quot;': '"',
        '&apos;': "'",
        '&lt;': '<',
        '&gt;': '>',
        '&amp;': '&'
    }

    def repl_esc_xml(m, c_start):
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

# Helper function for deep copying elements
def deepcopy(element):
    from copy import deepcopy as python_deepcopy
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

def convert_tei_to_text(xml_file_path):
    """
    Convert a TEI/XML file to plain text with the following rules:
    - Only content within the body tags is processed
    - Line breaks (<lb/>) become newline characters
    - Page breaks (<pb/>) become two newline characters
    - Notes (<note>...</note>) are removed
    - <figure><caption><p>foo</p></caption></figure> becomes "foo"
    - <gap /> elements are removed
    - <unclear><supplied>foo</supplied></unclear> becomes "foo"
    - <choice><orig>foo</orig><corr>bar</corr></choice> becomes "bar"
    - All other XML tags are stripped
    - XML-encoded characters (&gt;, etc.) are converted to their normal representation
    
    Args:
        xml_file_path: Path to the XML file
        
    Returns:
        String containing the plain text representation
    """
    # Parse the XML file
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    tree = etree.parse(xml_file_path, parser)
    root = tree.getroot()
    
    # Find the body element (handle TEI namespace if present)
    namespaces = {'tei': 'http://www.tei-c.org/ns/1.0'}
    body = root.xpath('//tei:body', namespaces=namespaces)
        
    if not body:
        print("No body element found in the TEI document", file=sys.stderr)
        return None
    
    # Create a deep copy of the body to avoid modifying the original tree
    body_copy = etree.Element("body")
    body_copy.extend(body[0].xpath("./*"))
    
    # Process the TEI elements

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
        render_val = hi.get('render')
        if render_val:
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
        supplied = unclear.xpath('.//tei:supplied', namespaces=namespaces)
        if supplied:
            text = "".join(supplied[0].itertext())
            text_element = etree.Element("text_marker")
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
    xml_str = etree.tostring(body_copy, encoding="unicode", method="xml")

    # Simple substitutions
    xml_str = re.sub(r'[\r\n\t ]*</?body>[\r\n\t ]*', "", xml_str) # this also normalizes spaces at the beginning and end
    xml_str = re.sub(r'<text_marker>(.*?)</text_marker>', r'\1', xml_str)
    xml_str = re.sub(r'[\r\n\t ]*<lb_marker>(.*?)</lb_marker>[\r\n\t ]*', r'\1', xml_str)
    
    annotations = {}
    xml_str = convert_pages(xml_str, annotations)
    xml_str = convert_hi(xml_str, annotations)
    xml_str = remove_other_markers(xml_str, annotations)
    xml_str = unescape_xml(xml_str, annotations)
    xml_str = normalize_new_lines(xml_str, annotations)

    return xml_str, annotations

def test_conversion():
    """Test the TEI to text conversion with a sample XML string"""
    test_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title>Sample Document</title>
          </titleStmt>
        </fileDesc>
      </teiHeader>
      <text>
        <body>
          <p>This is the first paragraph.<lb/>This is on a new line.</p>
          <pb n="123"/>
          This is on a new <random_tag/>page.
          This <!-- comment to be removed -->starts a <hi render="small">highlight
          <note>This note should be removed.</note>
          Special characters: &lt;tag&gt; &amp; &quot;quoted&quot;
          This note <note>with inline content</note> should be </hi>partially removed.
          There was a <gap reason="illegible"/> in the text.
          <figure>
            <caption><p>This is a figure caption</p></caption>
          </figure>
          <p>The word is <unclear><supplied>probably</supplied></unclear> correct.</p>
          <p>The spelling <choice><orig>katt</orig><corr>cat</corr></choice> was fixed.</p>
        </body>
      </text>
    </TEI>
    """
    
    # Save test XML to a temporary file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as tmp:
        tmp.write(test_xml)
        tmp_path = tmp.name
    
    # Convert the test file
    text, annotations = convert_tei_to_text(tmp_path)
    text_with_anns = debug_annotations(text, annotations)
    
    # Clean up
    import os
    os.unlink(tmp_path)
    
    # Print result
    print("Test Result:")
    print("-" * 40)
    print(text_with_anns)
    print("-" * 40)
    
    expected = """This is the first paragraph.
This is on a new line.

[pages]This is on a new page.
This starts a [hi]highlight

Special characters: <tag> & "quoted"
This note  should be [/hi]partially removed.
There was a X in the text.
This is a figure caption
The word is probably correct.
The spelling cat was fixed.[/pages]"""
    
    print("Test passed!" if text_with_anns == expected else "Test failed!")

    
if __name__ == "__main__":
    # Run the test function
    test_conversion()
    
    # If command line arguments provided, process the specified file
    if len(sys.argv) > 1:
        result = convert_tei_to_text(sys.argv[1])
        if result:
            print(result)