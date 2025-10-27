# Usage Example: Content Location with Milestone-based Segmentation

This document demonstrates how to use the enhanced `OutlineEtextLookup` class with support for `contentLocationIdInEtext` and `contentLocationEndIdInEtext`.

## Basic Concepts

### Milestone-based Segmentation

The BUDA ontology now supports fine-grained content location using milestone markers:

- `contentLocationIdInEtext`: Specifies the starting `xml:id` within an etext
- `contentLocationEndIdInEtext`: Specifies the ending `xml:id` within an etext
- Empty/missing values mean beginning or end of the etext respectively

### Volume-level Cutting

Segments are always cut at volume boundaries. If a content location spans multiple volumes, it will be processed as separate segments per volume.

## Example 1: Simple Single-etext Segment

```python
from bdrc_etext_sync.buda_api import OutlineEtextLookup, EtextSegment
from lxml import etree

# Initialize the lookup
oel = OutlineEtextLookup("O12345", "IE67890")

# Get segments for volume 1
segments = oel.get_volume_segments(1)

# Process each segment
for segment in segments:
    mw_lname = segment["mw"]  # Master work identifier
    should_merge = segment["merge"]  # Whether to merge etexts
    
    for etext_num, start_id, end_id in segment["etexts"]:
        # Load the etext XML
        xml_tree = load_etext_xml(etext_num)
        
        # Extract the text segment
        extractor = EtextSegment(xml_tree, start_id, end_id)
        text = extractor.extract_text()
        
        print(f"MW: {mw_lname}, Etext: {etext_num}")
        print(f"Text segment: {text[:100]}...")
```

## Example 2: Merging Multiple Etexts

When a content location spans multiple etexts in the same volume, they should be merged:

```python
# Given: contentLocationVolume=1, contentLocationEtext=1, 
#        contentLocationEndEtext=3, contentLocationIdInEtext="m1",
#        contentLocationEndIdInEtext="m3"

segments = oel.get_volume_segments(1)

for segment in segments:
    if segment["merge"]:
        # This segment spans multiple etexts, merge them
        all_text_parts = []
        
        for etext_num, start_id, end_id in segment["etexts"]:
            xml_tree = load_etext_xml(etext_num)
            extractor = EtextSegment(xml_tree, start_id, end_id)
            text = extractor.extract_text()
            all_text_parts.append(text)
        
        # Merge the parts
        merged_text = "\n\n".join(all_text_parts)
        
        # Process as a single document
        process_document(segment["mw"], merged_text)
    else:
        # Single etext, no merge needed
        etext_num, start_id, end_id = segment["etexts"][0]
        xml_tree = load_etext_xml(etext_num)
        extractor = EtextSegment(xml_tree, start_id, end_id)
        text = extractor.extract_text()
        process_document(segment["mw"], text)
```

## Example 3: Spanning Volumes

When a content location spans multiple volumes, process each volume separately:

```python
# Given: contentLocationVolume=1, contentLocationEndVolume=3,
#        contentLocationEtext=2, contentLocationEndEtext=1,
#        contentLocationIdInEtext="a", contentLocationEndIdInEtext="b"

# Process volume 1
segments_v1 = oel.get_volume_segments(1)
for segment in segments_v1:
    # Volume 1: etext 2 from marker "a" to end
    etext_num, start_id, end_id = segment["etexts"][0]
    # start_id="a", end_id=None (to end)
    process_segment(1, etext_num, start_id, end_id)

# Process volume 2 (if content location doesn't have specific etext numbers for middle volumes)
segments_v2 = oel.get_volume_segments(2)
# Middle volumes get all content

# Process volume 3
segments_v3 = oel.get_volume_segments(3)
for segment in segments_v3:
    # Volume 3: etext 1 from beginning to marker "b"
    etext_num, start_id, end_id = segment["etexts"][0]
    # start_id=None (from beginning), end_id="b"
    process_segment(3, etext_num, start_id, end_id)
```

## Example 4: Extract Text from XML with Milestones

```python
from lxml import etree
from bdrc_etext_sync.buda_api import EtextSegment

# Sample XML with milestones
xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <p>Text before milestone 1</p>
      <milestone xml:id="m1" unit="section"/>
      <p>Text between m1 and m2</p>
      <milestone xml:id="m2" unit="section"/>
      <p>Text after milestone 2</p>
    </body>
  </text>
</TEI>"""

parser = etree.XMLParser(remove_blank_text=True)
tree = etree.fromstring(xml_content.encode('utf-8'), parser)

# Extract text between m1 and m2
segment = EtextSegment(tree, "m1", "m2")
text = segment.extract_text()
# Result: "Text between m1 and m2"

# Extract from beginning to m1
segment = EtextSegment(tree, None, "m1")
text = segment.extract_text()
# Result: "Text before milestone 1"

# Extract from m2 to end
segment = EtextSegment(tree, "m2", None)
text = segment.extract_text()
# Result: "Text after milestone 2"

# Extract entire text
segment = EtextSegment(tree, None, None)
text = segment.extract_text()
# Result: "Text before milestone 1 Text between m1 and m2 Text after milestone 2"
```

## Backward Compatibility

The old `get_mw_for(vnum, etextnum)` method is still available but deprecated:

```python
# Old way (still works for simple cases)
mw = oel.get_mw_for(1, 1)

# New way (recommended)
segments = oel.get_volume_segments(1)
for segment in segments:
    mw = segment["mw"]
    # ... process with full segment information
```

## Integration with Existing Code

For minimal changes to existing code that uses `get_mw_for`:

```python
# In es_utils.py or similar
if oel:
    # Old code:
    # potential_mw = oel.get_mw_for(vol_num, doc_num+1)
    
    # Can keep using get_mw_for for simple cases
    potential_mw = oel.get_mw_for(vol_num, doc_num+1)
    if potential_mw:
        mw_lname = potential_mw
```

For full feature support including milestone-based segmentation:

```python
# At volume processing level
if oel:
    segments = oel.get_volume_segments(vol_num)
    
    # Group etexts by content location
    for segment in segments:
        mw_lname = segment["mw"]
        
        if segment["merge"]:
            # Merge multiple etexts into one document
            merged_content = []
            for etext_num, start_id, end_id in segment["etexts"]:
                xml_tree = load_etext_xml(vol_name, etext_num)
                extractor = EtextSegment(xml_tree, start_id, end_id)
                merged_content.append(extractor.extract_text())
            
            # Process merged document
            process_merged_document(mw_lname, merged_content)
        else:
            # Single etext with possible ID-based extraction
            etext_num, start_id, end_id = segment["etexts"][0]
            xml_tree = load_etext_xml(vol_name, etext_num)
            extractor = EtextSegment(xml_tree, start_id, end_id)
            text = extractor.extract_text()
            process_document(mw_lname, text)
```

## Testing

The test suite in `test/test_buda_api.py` provides comprehensive examples:

- `TestEtextSegment`: Tests for milestone-based text extraction
- `TestOutlineEtextLookupWithIds`: Tests for content location with IDs
- `TestComplexScenarios`: Tests for complex real-world cases

Run tests with:
```bash
python -m unittest test.test_buda_api -v
```
