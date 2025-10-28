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
from .tei_to_standoff import convert_tei_root_to_standoff, convert_tei_to_standoff, _shift_all_annotations

# Backward compatibility aliases
convert_tei_root_to_text = convert_tei_root_to_standoff
convert_tei_to_text = convert_tei_to_standoff

INDEX = "bdrc_prod"
DEBUG = False


class EtextSegment:
    """
    Helper class to represent a segment of text within an etext, defined by milestone boundaries.
    
    This class works with already-converted text and milestone annotations (not XML).
    It represents the space between two milestones and provides access to the text and
    annotations for that segment.
    
    The volume_char_offset property tracks the absolute character position of this segment
    within the entire volume (across all etexts), which ensures character coordinates are
    continuous per volume rather than being reset for each etext.
    """
    
    def __init__(self, text, annotations, start_id=None, end_id=None, etext_num=None):
        """
        Initialize an etext segment.
        
        Args:
            text: The full text of the etext (already converted from XML)
            annotations: Annotations dict with milestone positions and other data
            start_id: xml:id of the starting milestone (None means beginning of etext)
            end_id: xml:id of the ending milestone (None means end of etext)
            etext_num: The etext number this segment belongs to
        """
        self.full_text = text
        self.annotations = annotations
        self.start_id = start_id
        self.end_id = end_id
        self.etext_num = etext_num
        self.milestones = annotations.get("milestones", {})
        
        # Determine start and end positions within this etext
        self.start_pos = 0
        self.end_pos = len(text)
        
        if start_id and start_id in self.milestones:
            self.start_pos = self.milestones[start_id]
        elif start_id:
            logging.warning(f"Start milestone '{start_id}' not found in etext {etext_num}")
        
        if end_id and end_id in self.milestones:
            self.end_pos = self.milestones[end_id]
        elif end_id:
            logging.warning(f"End milestone '{end_id}' not found in etext {etext_num}")
        
        # volume_char_offset will be set externally to track absolute position in volume
        # This is the character position of start_pos within the entire volume
        self.volume_char_offset = 0
    
    def get_text(self):
        """
        Get the text for this segment.
        
        Returns:
            str: The text between start_pos and end_pos
        """
        return self.full_text[self.start_pos:self.end_pos]
    
    def get_annotations_for_segment(self, offset=0):
        """
        Get annotations adjusted for this segment.
        
        Args:
            offset: Additional offset to add to all positions (for merging multiple segments
                   into a single document). This is relative to the document being built,
                   not the volume.
        
        Returns:
            dict: Adjusted annotations for this segment
        """
        segment_annotations = {}
        
        # Handle pages
        if "pages" in self.annotations:
            segment_annotations["pages"] = []
            for page in self.annotations["pages"]:
                if page["cstart"] >= self.start_pos and page["cstart"] < self.end_pos:
                    new_page = page.copy()
                    new_page["cstart"] = page["cstart"] - self.start_pos + offset
                    new_page["cend"] = min(page["cend"], self.end_pos) - self.start_pos + offset
                    segment_annotations["pages"].append(new_page)
        
        # Handle hi (highlights)
        if "hi" in self.annotations:
            segment_annotations["hi"] = []
            for hi in self.annotations["hi"]:
                if hi["cstart"] >= self.start_pos and hi["cstart"] < self.end_pos:
                    new_hi = hi.copy()
                    new_hi["cstart"] = hi["cstart"] - self.start_pos + offset
                    new_hi["cend"] = min(hi["cend"], self.end_pos) - self.start_pos + offset
                    segment_annotations["hi"].append(new_hi)
        
        # Handle milestones
        if "milestones" in self.annotations:
            segment_annotations["milestones"] = {}
            for milestone_id, pos in self.annotations["milestones"].items():
                if pos >= self.start_pos and pos < self.end_pos:
                    segment_annotations["milestones"][milestone_id] = pos - self.start_pos + offset
        
        # Handle div_boundaries if present
        if "div_boundaries" in self.annotations:
            segment_annotations["div_boundaries"] = []
            for boundary in self.annotations["div_boundaries"]:
                if boundary["cstart"] >= self.start_pos and boundary["cstart"] < self.end_pos:
                    new_boundary = boundary.copy()
                    new_boundary["cstart"] = boundary["cstart"] - self.start_pos + offset
                    new_boundary["cend"] = min(boundary["cend"], self.end_pos) - self.start_pos + offset
                    segment_annotations["div_boundaries"].append(new_boundary)
        
        return segment_annotations
    
    def __repr__(self):
        return f"EtextSegment(etext={self.etext_num}, start_id={self.start_id}, end_id={self.end_id}, pos={self.start_pos}:{self.end_pos}, vol_offset={self.volume_char_offset})"

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

def _create_docs_without_outline(converted_etexts, vol_name, vol_num, ie_lname, mw_root_lname, ocfl_version):
    """
    Create documents from converted etexts without using outline information.
    Each etext becomes a separate document using the root MW.
    """
    docs = []
    last_cnum = 0
    last_pnum = 0
    
    for etext_data in converted_etexts:
        text = etext_data["text"]
        annotations = etext_data["annotations"]
        
        # Update page numbers
        new_last_pnum = last_pnum
        if "pages" in annotations and annotations["pages"]:
            new_last_pnum += annotations["pages"][-1]["pnum"]
        
        # Create document
        doc = _build_etext_doc(
            text, annotations, etext_data["source_path"],
            vol_name, vol_num, ocfl_version,
            etext_data["doc_name"], etext_data["etext_num"],
            ie_lname, mw_root_lname, mw_root_lname,
            last_cnum, last_pnum
        )
        docs.append(doc)
        
        last_cnum += len(text)
        last_pnum = new_last_pnum
    
    return docs

def _segment_etexts_by_outline(converted_etexts, oel, vol_name, vol_num, ie_lname, mw_root_lname, ocfl_version):
    """
    Segment converted etexts based on outline information with milestone boundaries.
    
    Algorithm per @eroux:
    1. Convert all etexts (already done)
    2. Filter milestones to only those referenced in outline (to avoid creating too many segments)
    3. Iterate over each etext segment (space between two outline-referenced milestones)
    4. Detect document boundaries based on outline
    5. When outline signals end of text, finish doc and start new one
    6. Handle overlaps and gaps
    
    Character coordinates are continuous per volume.
    """
    docs = []
    content_locations = oel.get_content_locations_for_volume(vol_num)
    
    if not content_locations:
        logging.warning(f"No content locations found for volume {vol_num}, using root MW")
        return _create_docs_without_outline(converted_etexts, vol_name, vol_num, ie_lname, mw_root_lname, ocfl_version)
    
    # Build list of all milestone segments in order (only using outline-referenced milestones)
    all_segments = []
    volume_char_offset = 0
    
    for etext_data in converted_etexts:
        etext_num = etext_data["etext_num"]
        # Get all milestone IDs referenced in the outline for this volume
        # This filters out milestones not in the outline to avoid too many segments
        outline_milestone_ids = oel.get_milestone_ids_for_volume(vol_num, etext_num)
        
        text = etext_data["text"]
        annotations = etext_data["annotations"]
        milestones = annotations.get("milestones", {})
        
        if milestones and outline_milestone_ids:
            # Filter to only milestones referenced in the outline
            relevant_milestones = {m_id: pos for m_id, pos in milestones.items() 
                                  if m_id in outline_milestone_ids}
            
            if relevant_milestones:
                # Sort milestones by position
                sorted_milestones = sorted(relevant_milestones.items(), key=lambda x: x[1])
                
                # Create segments: start -> m1, m1 -> m2, ..., last_m -> end
                prev_id = None
                for i, (m_id, m_pos) in enumerate(sorted_milestones):
                    segment = EtextSegment(text, annotations, prev_id, m_id, etext_num)
                    segment.volume_char_offset = volume_char_offset + segment.start_pos
                    all_segments.append(segment)
                    prev_id = m_id
                
                # Last segment: from last milestone to end
                segment = EtextSegment(text, annotations, prev_id, None, etext_num)
                segment.volume_char_offset = volume_char_offset + segment.start_pos
                all_segments.append(segment)
            else:
                # No relevant milestones in this etext, treat whole etext as one segment
                segment = EtextSegment(text, annotations, None, None, etext_num)
                segment.volume_char_offset = volume_char_offset
                all_segments.append(segment)
        else:
            # No milestones or no outline milestone IDs: whole etext is one segment
            segment = EtextSegment(text, annotations, None, None, etext_num)
            segment.volume_char_offset = volume_char_offset
            all_segments.append(segment)
        
        volume_char_offset += len(text)
    
    # Now iterate through segments and build documents
    doc_counter = 0
    current_doc_text = ""
    current_doc_annotations = {"pages": [], "hi": [], "milestones": {}}
    current_doc_mw = None
    current_doc_start_offset = 0
    last_pnum = 0
    processed_segments = set()
    
    for segment in all_segments:
        # Find matching content location for this segment
        matching_cl = _find_matching_cl(segment, content_locations)
        
        if matching_cl:
            # Check for overlap: if a new CL starts before current one ends
            if current_doc_mw and current_doc_mw != matching_cl["mw"]:
                logging.error(f"Overlap detected: text {matching_cl['mw']} starts before {current_doc_mw} ends at etext {segment.etext_num}")
                # Finish current doc at the start of the new one
                if current_doc_text:
                    doc_counter += 1
                    doc = _create_document_from_parts(
                        current_doc_text, current_doc_annotations,
                        vol_name, vol_num, ocfl_version, doc_counter,
                        ie_lname, current_doc_mw, mw_root_lname,
                        current_doc_start_offset, last_pnum
                    )
                    docs.append(doc)
                    last_pnum = _get_last_pnum(current_doc_annotations, last_pnum)
                
                # Start new document
                current_doc_text = ""
                current_doc_annotations = {"pages": [], "hi": [], "milestones": {}}
                current_doc_mw = matching_cl["mw"]
                current_doc_start_offset = segment.volume_char_offset
            elif not current_doc_mw:
                # First document
                current_doc_mw = matching_cl["mw"]
                current_doc_start_offset = segment.volume_char_offset
            
            # Add this segment to current document
            seg_text = segment.get_text()
            seg_annotations = segment.get_annotations_for_segment(len(current_doc_text))
            current_doc_text += seg_text
            _merge_annotations(current_doc_annotations, seg_annotations)
            processed_segments.add(id(segment))
            
            # Check if this marks the end of current content location
            if _is_end_of_content_location(segment, matching_cl):
                # Finish document
                if current_doc_text:
                    doc_counter += 1
                    doc = _create_document_from_parts(
                        current_doc_text, current_doc_annotations,
                        vol_name, vol_num, ocfl_version, doc_counter,
                        ie_lname, current_doc_mw, mw_root_lname,
                        current_doc_start_offset, last_pnum
                    )
                    docs.append(doc)
                    last_pnum = _get_last_pnum(current_doc_annotations, last_pnum)
                
                # Reset for next document
                current_doc_text = ""
                current_doc_annotations = {"pages": [], "hi": [], "milestones": {}}
                current_doc_mw = None
        else:
            # Gap: not covered by any content location
            if id(segment) not in processed_segments:
                logging.error(f"Gap: etext {segment.etext_num} segment {segment.start_id}->{segment.end_id} not covered by outline")
                # Create document with root MW
                seg_text = segment.get_text()
                if seg_text.strip():  # Only if there's actual content
                    seg_annotations = segment.get_annotations_for_segment(0)
                    doc_counter += 1
                    doc = _create_document_from_parts(
                        seg_text, seg_annotations,
                        vol_name, vol_num, ocfl_version, doc_counter,
                        ie_lname, mw_root_lname, mw_root_lname,
                        segment.volume_char_offset, last_pnum
                    )
                    docs.append(doc)
                    last_pnum = _get_last_pnum(seg_annotations, last_pnum)
                processed_segments.add(id(segment))
    
    # Finish any remaining document
    if current_doc_text:
        doc_counter += 1
        doc = _create_document_from_parts(
            current_doc_text, current_doc_annotations,
            vol_name, vol_num, ocfl_version, doc_counter,
            ie_lname, current_doc_mw or mw_root_lname, mw_root_lname,
            current_doc_start_offset, last_pnum
        )
        docs.append(doc)
    
    return docs

def _find_matching_cl(segment, content_locations):
    """
    Find which content location this segment belongs to.
    
    Args:
        segment: EtextSegment instance
        content_locations: List of content location dicts
    
    Returns:
        Content location dict or None if no match
    """
    etext_num = segment.etext_num
    start_id = segment.start_id
    end_id = segment.end_id
    
    for cl in content_locations:
        cl_start_etext = cl["etextnum_start"] or 1
        cl_end_etext = cl["etextnum_end"] or etext_num
        cl_start_id = cl["id_in_etext"]
        cl_end_id = cl["end_id_in_etext"]
        
        # Check if etext is in range
        if etext_num < cl_start_etext or etext_num > cl_end_etext:
            continue
        
        # If at start etext, check milestone
        if etext_num == cl_start_etext and cl_start_id:
            # This segment should start at or after the cl_start_id
            if cl_start_id in segment.milestones:
                # Check if segment starts before the CL start
                if start_id and segment.milestones.get(start_id, 0) < segment.milestones[cl_start_id]:
                    continue
            else:
                continue  # Start milestone not found
        
        # If at end etext, check milestone
        if etext_num == cl_end_etext and cl_end_id:
            # This segment should end at or before cl_end_id
            if cl_end_id in segment.milestones:
                # Check if segment ends after the CL end
                if end_id and segment.milestones.get(end_id, float('inf')) > segment.milestones[cl_end_id]:
                    continue
            else:
                continue  # End milestone not found
        
        return cl
    
    return None

def _is_end_of_content_location(segment, cl):
    """
    Check if this segment marks the end of a content location.
    
    Args:
        segment: EtextSegment instance
        cl: Content location dict
    
    Returns:
        bool: True if this is the last segment of the CL
    """
    etext_num = segment.etext_num
    end_id = segment.end_id
    cl_end_etext = cl["etextnum_end"] or etext_num
    cl_end_id = cl["end_id_in_etext"]
    
    # If we're at the end etext and segment ends at the end milestone
    if etext_num == cl_end_etext:
        if cl_end_id:
            # Check if segment ends at the CL end
            return end_id == cl_end_id
        else:
            # No end milestone specified, check if we're at end of etext
            return end_id is None
    
    return False

def _merge_annotations(target, source):
    """Merge source annotations into target."""
    for key in ["pages", "hi", "div_boundaries"]:
        if key in source:
            if key not in target:
                target[key] = []
            target[key].extend(source[key])
    
    if "milestones" in source:
        if "milestones" not in target:
            target["milestones"] = {}
        target["milestones"].update(source["milestones"])

def _get_last_pnum(annotations, current_last):
    """Get the last page number from annotations."""
    if "pages" in annotations and annotations["pages"]:
        return annotations["pages"][-1]["pnum"]
    return current_last

def _create_document_from_parts(text, annotations, vol_name, vol_num, ocfl_version,
                                doc_num, ie_lname, mw_lname, mw_root_lname,
                                start_at_c, last_pnum):
    """Create a document from accumulated text and annotations."""
    doc_name = f"{vol_name}_{doc_num:03d}"
    
    # Shift page numbers
    _shift_pages(annotations, last_pnum)
    
    # Build document
    doc = _build_etext_doc(
        text, annotations, None,  # source_path
        vol_name, vol_num, ocfl_version,
        doc_name, doc_num,
        ie_lname, mw_lname, mw_root_lname,
        start_at_c, last_pnum
    )
    
    return doc


def get_docs(mw_root_lname, ie_lname, local_dir_path, ocfl_version, volname_to_volnum, outline_lname):
    """
    Process etexts for all volumes using outline-based segmentation.
    
    New algorithm:
    1. For each volume, convert all etexts to text with annotations (keeping milestones)
    2. Use outline information to segment the text based on milestone boundaries
    3. Create documents that may span multiple etexts
    4. Handle gaps in outline by using root MW
    
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

        # STEP 1: Convert all etexts in this volume to text with annotations
        converted_etexts = []
        for doc_num, xml_file_path in enumerate(xml_files):
            logging.info(f"Converting etext {doc_num+1}: {xml_file_path}")
            doc_name = fs.path.basename(xml_file_path)[:-4]
            
            with base_fs.open(xml_file_path, 'rb') as xml_file:
                parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
                tree = etree.parse(xml_file, parser)
                root = tree.getroot()
                base_string, annotations, source_path = convert_tei_root_to_text(root)
                
                converted_etexts.append({
                    "etext_num": doc_num + 1,
                    "doc_name": doc_name,
                    "text": base_string,
                    "annotations": annotations,
                    "source_path": source_path
                })
        
        # STEP 2: Use outline to segment the converted etexts
        if oel:
            docs = _segment_etexts_by_outline(
                converted_etexts, oel, vol_name, vol_num, ie_lname, 
                mw_root_lname, ocfl_version
            )
        else:
            # No outline: treat each etext as a separate document with root MW
            docs = _create_docs_without_outline(
                converted_etexts, vol_name, vol_num, ie_lname,
                mw_root_lname, ocfl_version
            )
        
        if vol_name not in docs_by_volume:
            docs_by_volume[vol_name] = []
        docs_by_volume[vol_name].extend(docs)

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
            div_start = boundary["cstart"]
            div_end = boundary["cend"]
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

def _shift_pages(annotations, p_shift):
    """
    We have a list of annotations and we shift all character coordinates by start_at_c in place
    """
    if not p_shift or "pages" not in annotations:
        return annotations
    for anno in annotations["pages"]:
        anno['pnum'] += p_shift

if __name__ == "__main__":
    # If command line arguments provided, process the specified file
    if len(sys.argv) > 1:
        result = convert_tei_to_text(sys.argv[1])
        if result:
            print(result)