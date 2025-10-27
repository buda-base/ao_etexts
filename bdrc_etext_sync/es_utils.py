from lxml import etree
import re
import sys
import html
import re
from bisect import bisect
import os
import json
import logging
import fs.path

from opensearchpy import OpenSearch, helpers

from .chunkers import TibetanEasyChunker
from .buda_api import OutlineEtextLookup
from .fs_utils import open_filesystem

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
            use_ssl = True,
            timeout=120
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
            for doc in volume_docs:
                logging.info("send %s" % doc["_id"])
            response = helpers.bulk(get_os_client(), volume_docs, max_retries=2, request_timeout=120)
    except:
        logging.exception("The request to ES had an exception for " + ie)

def get_docs(mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum, outline_lname):
    """
    Get documents from a local or S3 path.
    
    Args:
        mw_root_lname: Master work root local name
        ie_lname: Instance etext local name
        local_dir_path: Path or URL to the directory (can be local path or S3 URL)
        ocfl_version: OCFL version
        volname_to_volnum: Mapping of volume names to numbers
        outline_lname: Outline local name
    """
    logging.info(f"get docs for {local_dir_path}")

    oel = None
    if outline_lname:
        try:
            oel = OutlineEtextLookup(outline_lname, ie_lname)
        except:
            logging.exception("could not get outline for "+outline_lname)

    # Open the filesystem
    base_fs = open_filesystem(local_dir_path)
    
    # Construct the path to the archive directory
    archive_path = "archive"

    docs_by_volume = {}
    
    # Check if the archive directory exists
    if not base_fs.exists(archive_path):
        logging.warning(f"Archive directory does not exist at {archive_path}")
        base_fs.close()
        return

    # Iterate through all subdirectories in the archive directory
    for vol_name, vol_num in volname_to_volnum.items():

        vol_path = fs.path.join(archive_path, vol_name)
        
        # Skip if not a directory
        if not base_fs.isdir(vol_path):
            logging.error(f"Skip {vol_name} (no directory with that name under archive/)")
            continue
        
        logging.info(f"Processing volume: {vol_name}")
        
        # Get all XML files in the volume subdirectory
        xml_files = []
        for filename in base_fs.listdir(vol_path):
            if filename.endswith('.xml'):
                xml_files.append(fs.path.join(vol_path, filename))
        
        # Sort the XML files alphabetically
        xml_files.sort()

        # character positions are additive
        last_cnum = 0
        last_pnum = 0 
        
        # Process each XML file
        for doc_num, xml_file_path in enumerate(xml_files):
            logging.error(f"get doc for {xml_file_path}")
            # Extract just the filename without the path
            doc_name = fs.path.basename(xml_file_path)[:-4]
            mw_lname = mw_root_lname
            if oel:
                potential_mw = oel.get_mw_for(vol_num, doc_num+1)
                if potential_mw:
                    mw_lname = potential_mw
            # Call the get_docs function - read XML content from filesystem
            with base_fs.open(xml_file_path, 'rb') as xml_file:
                # we add a page break at the end of the base string if not the last doc
                add_pb = doc_num < len(xml_files) -1
                len_basestring, doc_last_pnum, doc = get_doc_from_content(xml_file, vol_name, vol_num, ocfl_version, doc_name, doc_num+1, ie_lname, mw_lname, mw_root_lname, last_cnum, last_pnum, add_pb)
            if not doc:
                logging.error(f"could not convert {doc_name}")
                continue
            last_cnum += len_basestring
            if doc_last_pnum > 0:
                last_pnum = doc_last_pnum
            if vol_name not in docs_by_volume:
                docs_by_volume[vol_name] = []
            docs_by_volume[vol_name].append(doc)

    base_fs.close()
    return docs_by_volume

def sync_id_to_es(mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum, outline_lname):
    docs_by_volume = get_docs(mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum, outline_lname)
    if docs_by_volume:
        send_docs_to_es(docs_by_volume, ie_lname)
    else:
        logging.error(f"could not find any document for {ie_lname}")

def get_doc(xml_file_path, vol_name, vol_num, ocfl_version, doc_name, doc_num, ie_lname, mw_lname, mw_root_lname):
    """Get doc from a file path (legacy function for backward compatibility)."""
    base_string, annotations, source_path = convert_tei_to_text(xml_file_path)
    return _build_etext_doc(base_string, annotations, source_path, vol_name, vol_num, ocfl_version, doc_name, doc_num, ie_lname, mw_lname, mw_root_lname)

def get_doc_from_content(xml_file_content, vol_name, vol_num, ocfl_version, doc_name, doc_num, ie_lname, mw_lname, mw_root_lname, start_at_c=0, last_pnum=0, add_pb=False):
    """Get doc from file content (file-like object)."""
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    tree = etree.parse(xml_file_content, parser)
    root = tree.getroot()
    base_string, annotations, source_path = convert_tei_root_to_text(root)
    new_last_pnum = last_pnum
    if "pages" in annotations and annotations["pages"]:
        new_last_pnum += annotations["pages"][-1]["pnum"]
    if add_pb:
        base_string += "\n\n"
    return len(base_string), new_last_pnum, _build_etext_doc(base_string, annotations, source_path, vol_name, vol_num, ocfl_version, doc_name, doc_num, ie_lname, mw_lname, mw_root_lname, start_at_c, last_pnum)

def _build_etext_doc(base_string, annotations, source_path, vol_name, vol_num, ocfl_version, doc_name, doc_num, ie_lname, mw_lname, mw_root_lname, start_at_c=0, last_pnum=1):
    """Build the etext document structure."""
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
    etext_doc["cstart"] = start_at_c
    etext_doc["cend"] = start_at_c+len(base_string)
    _shift_all_annotations(annotations, start_at_c)
    _shift_pages(annotations, last_pnum)
    if "pages" in annotations:
        etext_doc["etext_pages"] = annotations["pages"]
    if "hi" in annotations:
        etext_doc["etext_spans"] = annotations["hi"]
    
    # Chunk the text - if div_boundaries exist, chunk each div separately
    if "div_boundaries" in annotations and annotations["div_boundaries"]:
        for boundary in annotations["div_boundaries"]:
            div_start = boundary["start"]
            div_end = boundary["end"]
            chunker = TibetanEasyChunker(base_string, 1500, div_start, div_end)
            chunk_indexes = chunker.get_chunks()
            for i in range(0, len(chunk_indexes) - 1):
                if "chunks" not in etext_doc:
                    etext_doc["chunks"] = []
                etext_doc["chunks"].append({
                    "cstart": chunk_indexes[i] + start_at_c,
                    "cend": chunk_indexes[i + 1] + start_at_c,
                    "text_bo": base_string[chunk_indexes[i]:chunk_indexes[i + 1]]
                })
    else:
        # Old behavior: chunk the entire document
        chunker = TibetanEasyChunker(base_string, 1500, 0, len(base_string))
        chunk_indexes = chunker.get_chunks()
        for i in range(0, len(chunk_indexes) - 1):
            if "chunks" not in etext_doc:
                etext_doc["chunks"] = []
            etext_doc["chunks"].append({
                "cstart": chunk_indexes[i] + start_at_c,
                "cend": chunk_indexes[i + 1] + start_at_c,
                "text_bo": base_string[chunk_indexes[i]:chunk_indexes[i + 1]]
            })
    return etext_doc

def _shift_all_annotations(annotations, start_at_c):
    """
    Shift all character coordinates by start_at_c in place.
    Handles both list-based annotations, milestone dict, and div_boundaries.
    """
    if not start_at_c:
        return annotations
    for key, anno_list in annotations.items():
        if key == "milestones":
            # Milestones is a dict of id -> coordinate
            for milestone_id in anno_list:
                anno_list[milestone_id] += start_at_c
        elif key == "div_boundaries":
            # Div boundaries are a list of dicts with start/end
            for boundary in anno_list:
                boundary['start'] += start_at_c
                boundary['end'] += start_at_c
        else:
            # Regular annotations are lists of dicts
            for anno in anno_list:
                anno['cstart'] += start_at_c
                anno['cend'] += start_at_c

def _shift_pages(annotations, p_shift):
    """
    We have a list of annotations and we shift all character coordinates by start_at_c in place
    """
    if not p_shift or "pages" not in annotations:
        return annotations
    for anno in annotations["pages"]:
        anno['pnum'] += p_shift

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
    """Apply position diffs to annotations, skipping special keys."""
    for type, ann_list in annotations.items():
        if type in ("milestones", "div_boundaries"):
            # These have special structure, skip them
            continue
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

def convert_milestones(text, annotations):
    """
    Replaces <milestone_marker>{id}</milestone_marker> with empty string
    and tracks the milestone coordinates in annotations
    """
    milestone_coords = {}
    def repl_milestone_marker(m, cstart):
        milestone_id = m.group("id")
        milestone_coords[milestone_id] = cstart
        return ""
    pat_str = r'[\r\n\s]*<milestone_marker>(?P<id>.*?)</milestone_marker>[\r\n\s]*'
    output = get_string(text, pat_str, repl_milestone_marker, annotations)
    if milestone_coords:
        annotations["milestones"] = milestone_coords
    return output

def convert_div_boundaries(text, annotations):
    """
    Replaces <div_start_marker/> and <div_end_marker/> with empty strings
    and tracks div boundaries for chunking
    """
    div_boundaries = []
    def repl_div_start_marker(m, cstart):
        div_boundaries.append({"start": cstart})
        return ""
    def repl_div_end_marker(m, cstart):
        if div_boundaries:
            div_boundaries[-1]["end"] = cstart
        return ""
    
    # Remove start markers
    pat_str = r'<div_start_marker\s*/>'
    output = get_string(text, pat_str, repl_div_start_marker, annotations)
    # Remove end markers
    pat_str = r'<div_end_marker\s*/>'
    output = get_string(output, pat_str, repl_div_end_marker, annotations)
    
    if div_boundaries:
        annotations["div_boundaries"] = div_boundaries
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
    # TODO: we should ignore previous / next characters if we're not in a xml:space="preserve" environment
    pat_str = r'(?P<ot><hi_(?P<rend>[^>]+)>)(?P<content>.*?)</hi_(?P=rend)>'
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
    # Parse the XML file
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    tree = etree.parse(xml_file_path, parser)
    root = tree.getroot()
    return convert_tei_root_to_text(root)

def convert_tei_root_to_text(root):
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
    - Milestones are tracked in annotations but removed from text
    - Head elements are converted to hi annotations with rend='head'
    - All other XML tags are stripped
    - XML-encoded characters (&gt;, etc.) are converted to their normal representation
    
    Args:
        root: an etree root
        
    Returns 3 values:
        String containing the plain text representation
        a dict representing the annotations
        the path of the source file
    """
    # Find the body element (handle TEI namespace if present)
    namespaces = {'tei': 'http://www.tei-c.org/ns/1.0'}

    source_path = root.xpath('//tei:idno[@type="src_path"]/text()', namespaces=namespaces)
    source_path = source_path[0] if source_path else None

    body = root.xpath('//tei:body', namespaces=namespaces)
        
    if not body:
        logging.error("No body element found in the TEI document", file=sys.stderr)
        return None
    
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
    #print(debug_annotations(xml_str, annotations))
    if not xml_space_preserve:
        xml_str = convert_div_boundaries(xml_str, annotations)
    xml_str = convert_milestones(xml_str, annotations)
    xml_str = convert_pages(xml_str, annotations)
    #print(debug_annotations(xml_str, annotations))
    xml_str = convert_hi(xml_str, annotations)
    xml_str = remove_other_markers(xml_str, annotations)
    xml_str = unescape_xml(xml_str, annotations)
    xml_str = normalize_new_lines(xml_str, annotations)
    
    # Limit to max 2 consecutive line breaks if not xml:space="preserve"
    if not xml_space_preserve:
        xml_str = re.sub(r'\n{3,}', '\n\n', xml_str)

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