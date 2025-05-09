from lxml import etree
import re
import sys
import html
import re
from bisect import bisect
import os
import glob
import json
import logging

from opensearchpy import OpenSearch, helpers

from .chunkers import TibetanEasyChunker

INDEX = "bdrc_prod"
DEBUG = False

CLIENT = None
def get_os_client():
    global CLIENT
    if not CLIENT:
        CLIENT = OpenSearch(
            hosts = [{'host': "opensearch.bdrc.io", 'port': 443}],
            http_compress = True, # enables gzip compression for request bodies
            http_auth = (os.getenv("OPENSEARCH_USER"), os.getenv("OPENSEARCH_PASS")),
            use_ssl = True
        )
    return CLIENT

def remove_previous_etext_es(ie):
    try:
        response = get_os_client().delete_by_query(
            index=INDEX,
            body={
                "query": {
                    "term": {
                        "etext_instance": {
                            "value": ie
                        }
                    }
                }
            }
        )
        logging.info(f"Deleted {response['deleted']} documents for {ie}.")
    except Exception as e:
        logging.error(f"An error occurred in deletion: {e}")

def send_docs_to_es(docs_by_volume, ie):
    if ie:
        remove_previous_etext_es(ie)
    try:
        for vol_name, volume_docs in docs_by_volume.items():
            logging.info("sending %d documents in bulk" % len(volume_docs))
            if DEBUG:
                print(json.dumps(volume_docs, indent=2, ensure_ascii=False))
            response = helpers.bulk(get_os_client(), volume_docs, max_retries=3, request_timeout=60)
    except:
        logging.exception("The request to ES had an exception for " + ie)

def get_docs(mw_lname, mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum):
    """
    """
    logging.info(f"get docs for {local_dir_path}")
    # Construct the path to the archive directory
    archive_path = os.path.join(local_dir_path, "archive")

    docs_by_volume = {}
    
    # Check if the archive directory exists
    if not os.path.exists(archive_path):
        logging.warning(f"Archive directory does not exist at {archive_path}")
        return

    # Iterate through all subdirectories in the archive directory
    for vol_name, vol_num in volname_to_volnum.items():

        vol_path = os.path.join(archive_path, vol_name)
        
        # Skip if not a directory
        if not os.path.isdir(vol_path):
            logging.error(f"Skip {vol_name} (no directory with that name under archive/)")
            continue
        
        logging.info(f"Processing volume: {vol_name}")
        
        # Get all XML files in the current subdirectory
        xml_files = glob.glob(os.path.join(vol_path, "*.xml"))
        
        # Sort the XML files alphabetically
        xml_files.sort()
        
        # Process each XML file
        for doc_num, xml_file_path in enumerate(xml_files):
            logging.info(f"get doc for {xml_file_path}")
            # Extract just the filename without the path
            doc_name = os.path.basename(xml_file_path)
            
            # Call the get_docs function
            doc = get_doc(xml_file_path, vol_name, vol_num, ocfl_version, doc_name, doc_num+1, ie_lname, mw_lname, mw_root_lname)
            if not doc:
                logging.error(f"could not convert {doc_name}")
                continue
            if vol_name not in docs_by_volume:
                docs_by_volume[vol_name] = []
            docs_by_volume[vol_name].append(doc)

    return docs_by_volume

def sync_id_to_es(mw_lname, mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum):
    docs_by_volume = get_docs(mw_lname, mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum)
    if docs_by_volume:
        send_docs_to_es(docs_by_volume, ie_lname)
    else:
        logging.error(f"could not find any document for {ie_lname}")

def get_doc(xml_file_path, vol_name, vol_num, ocfl_version, doc_name, doc_num, ie_lname, mw_lname, mw_root_lname):
    base_string, annotations, source_path = convert_tei_to_text(xml_file_path)
    etext_doc = {}
    etext_doc["_id"] = doc_name
    etext_doc["_index"] = INDEX
    etext_doc["routing"] = mw_lname
    etext_doc["type"] = ["Etext"]
    etext_doc["etext_quality"] = 4.0 # ?
    etext_doc["etext_instance"] = ie_lname
    etext_doc["etext_for_root_instance"] = mw_root_lname
    etext_doc["etext_for_instance"] = mw_lname
    etext_doc["join_field"] = { "name": "etext", "parent": mw_lname }
    etext_doc["etextNumber"] = doc_num
    etext_doc["etext_vol"] = vol_name
    etext_doc["volumeNumber"] = vol_num
    etext_doc["ocfl_version"] = ocfl_version
    etext_doc["source_path"] = source_path
    if "pages" in annotations:
        etext_doc["etext_pages"] = annotations["pages"]
    if "hi" in annotations:
        etext_doc["etext_spans"] = annotations["hi"]
    # TODO: handle non-Tibetan
    chunker = TibetanEasyChunker(base_string, 1500, 0, len(base_string))
    chunk_indexes = chunker.get_chunks()
    for i in range(0, len(chunk_indexes) - 1):
        if "chunks" not in etext_doc:
            etext_doc["chunks"] = []
        etext_doc["chunks"].append({
            "cstart": chunk_indexes[i],
            "cend": chunk_indexes[i + 1],
            "text_bo": base_string[chunk_indexes[i]:chunk_indexes[i + 1]]
        })
    return etext_doc


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
            ann["cstart"] = correct_position(ann["cstart"], positions, diffs)
            ann["cend"] = correct_position(ann["cend"], positions, diffs) 

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
            boundaries.append((anno['cstart'], f"[{anno_type}]"))
            boundaries.append((anno['cend'], f"[/{anno_type}]"))
    
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

def convert_hi(text, annotations):
    """
    replaces <hi_{rend}>{content}</hi_{rend}> with {content} and saves annotation text coordinates 
    """
    if "hi" not in annotations:
        annotations["hi"] = []
    hi_annotations = annotations["hi"]
    def repl_hi_marker(m, cstart):
        rend = m.group("rend")
        hi_annotations.append({"rend": rend, "cstart": m.start(), "cend": m.end()})
        repl = m.group('content')
        return repl
    pat_str = r'(?P<ot>(\n\s*)?<hi_(?P<rend>[^>]+)>)(?P<content>.*?)</hi_(?P=rend)>(\n\s*)?'
    output = get_string(text, pat_str, repl_hi_marker, annotations)
    return output

def remove_other_markers(text, annotations):
    """
    remove all xml markers
    """
    def repl_xml_marker(m, cstart):
        return ""
    pat_str = r'</?[^>]*?>'
    output = get_string(text, pat_str, repl_xml_marker, annotations)
    return output

def normalize_new_lines(text, annotations):
    """
    remove all xml markers
    """
    def repl_nl_marker(m, cstart):
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

    source_path = root.xpath('//tei:idno[@type="SRC_PATH"]/text()', namespaces=namespaces)
    source_path = source_path[0] if source_path else None

    body = root.xpath('//tei:body', namespaces=namespaces)
        
    if not body:
        logging.error("No body element found in the TEI document", file=sys.stderr)
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
    # this also normalizes spaces at the beginning and end
    xml_str = re.sub(r'[\r\n\t ]*</?(?:body|p)(?: +[^>]+)*>[\r\n\t ]*', "", xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'(?:\n\s*)?<text_marker>(.*?)</text_marker>(?:\n\s*)?', r'\1', xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'[\r\n\t ]*<lb_marker>(.*?)</lb_marker>[\r\n\t ]*', r'\1', xml_str, flags=re.DOTALL)

    annotations = {}
    #print(debug_annotations(xml_str, annotations))
    xml_str = convert_pages(xml_str, annotations)
    #print(debug_annotations(xml_str, annotations))
    xml_str = convert_hi(xml_str, annotations)
    xml_str = remove_other_markers(xml_str, annotations)
    xml_str = unescape_xml(xml_str, annotations)
    xml_str = normalize_new_lines(xml_str, annotations)

    return xml_str, annotations, source_path

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
          <pb n="122"/>
          <p>This is the first paragraph.<lb/>This is on a new line.</p>
          <pb n="123"/>
          <lb/>
          This is on a new <random_tag/>page.
          <lb/>
          This is on a new line
          <pb n="124"/>
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
    text, annotations, source_path = convert_tei_to_text(tmp_path)
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