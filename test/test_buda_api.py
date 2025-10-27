"""Tests for OutlineEtextLookup in buda_api.py

This test suite validates the handling of contentLocationIdInEtext and
contentLocationEndIdInEtext for extracting specific text segments based on
milestone markers in XML files.
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
from lxml import etree
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rdflib import Graph, Namespace, Literal, URIRef
from bdrc_etext_sync.buda_api import OutlineEtextLookup, EtextSegment

BDR = Namespace("http://purl.bdrc.io/resource/")
BDO = Namespace("http://purl.bdrc.io/ontology/core/")


class TestEtextSegment(unittest.TestCase):
    """Test the EtextSegment helper class for extracting text between milestones"""
    
    def test_extract_full_etext(self):
        """Test extracting entire etext when no IDs specified"""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <milestone xml:id="m1" unit="section"/>
      <p>Text before milestone 2</p>
      <milestone xml:id="m2" unit="section"/>
      <p>Text after milestone 2</p>
      <milestone xml:id="m3" unit="section"/>
    </body>
  </text>
</TEI>"""
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        # Extract full text (no start/end IDs)
        segment = EtextSegment(tree, None, None)
        text = segment.extract_text()
        
        self.assertIn("Text before milestone 2", text)
        self.assertIn("Text after milestone 2", text)
    
    def test_extract_between_milestones(self):
        """Test extracting text between two specific milestones"""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <p>Text before m1</p>
      <milestone xml:id="m1" unit="section"/>
      <p>Text between m1 and m2</p>
      <milestone xml:id="m2" unit="section"/>
      <p>Text after m2</p>
    </body>
  </text>
</TEI>"""
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        # Extract text between m1 and m2
        segment = EtextSegment(tree, "m1", "m2")
        text = segment.extract_text()
        
        self.assertNotIn("Text before m1", text)
        self.assertIn("Text between m1 and m2", text)
        self.assertNotIn("Text after m2", text)
    
    def test_extract_from_start_to_milestone(self):
        """Test extracting from beginning to a specific milestone"""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <p>Text at start</p>
      <milestone xml:id="m1" unit="section"/>
      <p>Text after m1</p>
    </body>
  </text>
</TEI>"""
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        # Extract from start to m1 (start_id is None)
        segment = EtextSegment(tree, None, "m1")
        text = segment.extract_text()
        
        self.assertIn("Text at start", text)
        self.assertNotIn("Text after m1", text)
    
    def test_extract_from_milestone_to_end(self):
        """Test extracting from a specific milestone to the end"""
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <p>Text before m1</p>
      <milestone xml:id="m1" unit="section"/>
      <p>Text after m1 until end</p>
    </body>
  </text>
</TEI>"""
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        # Extract from m1 to end (end_id is None)
        segment = EtextSegment(tree, "m1", None)
        text = segment.extract_text()
        
        self.assertNotIn("Text before m1", text)
        self.assertIn("Text after m1 until end", text)


class TestOutlineEtextLookupWithIds(unittest.TestCase):
    """Test OutlineEtextLookup with contentLocationIdInEtext support"""
    
    def create_mock_graph_simple(self):
        """Create a simple mock RDF graph with content location IDs in a single volume/etext"""
        g = Graph()
        
        # MW1 -> CL1 with IDs in single etext
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEtext, Literal(1)))
        g.add((cl1, BDO.contentLocationIdInEtext, Literal("m1")))
        g.add((cl1, BDO.contentLocationEndIdInEtext, Literal("m2")))
        
        return g
    
    def create_mock_graph_spanning_etexts(self):
        """Create a mock graph with content location spanning multiple etexts in same volume"""
        g = Graph()
        
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEtext, Literal(1)))
        g.add((cl1, BDO.contentLocationEndEtext, Literal(3)))
        g.add((cl1, BDO.contentLocationIdInEtext, Literal("m1")))
        g.add((cl1, BDO.contentLocationEndIdInEtext, Literal("m2")))
        
        return g
    
    def create_mock_graph_spanning_volumes(self):
        """Create a mock graph spanning multiple volumes"""
        g = Graph()
        
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEndVolume, Literal(2)))
        g.add((cl1, BDO.contentLocationEtext, Literal(2)))
        g.add((cl1, BDO.contentLocationEndEtext, Literal(1)))
        g.add((cl1, BDO.contentLocationIdInEtext, Literal("a")))
        g.add((cl1, BDO.contentLocationEndIdInEtext, Literal("b")))
        
        return g
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_init_extracts_ids(self, mock_get_outline):
        """Test that __init__ extracts contentLocationIdInEtext properly"""
        mock_get_outline.return_value = self.create_mock_graph_simple()
        
        oel = OutlineEtextLookup("O1", "IE1")
        
        self.assertEqual(len(oel.cls), 1)
        cl = oel.cls[0]
        self.assertEqual(cl["mw"], "MW1")
        self.assertEqual(cl["vnum_start"], 1)
        self.assertEqual(cl["vnum_end"], 1)
        self.assertEqual(cl["etextnum_start"], 1)
        self.assertEqual(cl["etextnum_end"], 1)
        self.assertEqual(cl["id_in_etext"], "m1")
        self.assertEqual(cl["end_id_in_etext"], "m2")
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_simple_single_etext_with_ids(self, mock_get_outline):
        """Test getting segments from a single etext with start/end IDs"""
        mock_get_outline.return_value = self.create_mock_graph_simple()
        
        oel = OutlineEtextLookup("O1", "IE1")
        segments = oel.get_volume_segments(1)
        
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        self.assertEqual(seg["mw"], "MW1")
        self.assertFalse(seg["merge"])  # Single etext, no merge needed
        self.assertEqual(len(seg["etexts"]), 1)
        etext_info = seg["etexts"][0]
        self.assertEqual(etext_info[0], 1)  # etext num
        self.assertEqual(etext_info[1], "m1")  # start_id
        self.assertEqual(etext_info[2], "m2")  # end_id
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_spanning_etexts_with_ids(self, mock_get_outline):
        """Test extracting segment spanning multiple etexts with IDs"""
        mock_get_outline.return_value = self.create_mock_graph_spanning_etexts()
        
        oel = OutlineEtextLookup("O1", "IE1")
        segments = oel.get_volume_segments(1)
        
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        self.assertEqual(seg["mw"], "MW1")
        self.assertTrue(seg["merge"])  # Multiple etexts, should merge
        self.assertEqual(len(seg["etexts"]), 3)
        
        # Check first etext: has start ID, no end ID
        self.assertEqual(seg["etexts"][0], (1, "m1", None))
        # Check middle etext: no IDs (full etext)
        self.assertEqual(seg["etexts"][1], (2, None, None))
        # Check last etext: no start ID, has end ID
        self.assertEqual(seg["etexts"][2], (3, None, "m2"))
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_spanning_volumes_separate_segments(self, mock_get_outline):
        """Test that segments in different volumes are kept separate"""
        mock_get_outline.return_value = self.create_mock_graph_spanning_volumes()
        
        oel = OutlineEtextLookup("O1", "IE1")
        
        # Get segments for volume 1
        segments_v1 = oel.get_volume_segments(1)
        self.assertEqual(len(segments_v1), 1)
        self.assertEqual(segments_v1[0]["mw"], "MW1")
        # Volume 1, etext 2 with start_id="a", no end
        self.assertEqual(segments_v1[0]["etexts"][0], (2, "a", None))
        
        # Get segments for volume 2
        segments_v2 = oel.get_volume_segments(2)
        self.assertEqual(len(segments_v2), 1)
        self.assertEqual(segments_v2[0]["mw"], "MW1")
        # Volume 2, etext 1 with no start, end_id="b"
        self.assertEqual(segments_v2[0]["etexts"][0], (1, None, "b"))
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_no_start_id_means_beginning(self, mock_get_outline):
        """Test that empty/missing start ID means beginning of etext"""
        g = Graph()
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEtext, Literal(1)))
        # No contentLocationIdInEtext
        g.add((cl1, BDO.contentLocationEndIdInEtext, Literal("m1")))
        
        mock_get_outline.return_value = g
        
        oel = OutlineEtextLookup("O1", "IE1")
        segments = oel.get_volume_segments(1)
        
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        # start_id should be None (meaning from beginning)
        self.assertEqual(seg["etexts"][0], (1, None, "m1"))
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_no_end_id_means_end(self, mock_get_outline):
        """Test that empty/missing end ID means end of etext"""
        g = Graph()
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEtext, Literal(1)))
        g.add((cl1, BDO.contentLocationIdInEtext, Literal("m1")))
        # No contentLocationEndIdInEtext
        
        mock_get_outline.return_value = g
        
        oel = OutlineEtextLookup("O1", "IE1")
        segments = oel.get_volume_segments(1)
        
        self.assertEqual(len(segments), 1)
        seg = segments[0]
        # end_id should be None (meaning to end)
        self.assertEqual(seg["etexts"][0], (1, "m1", None))


class TestComplexScenarios(unittest.TestCase):
    """Test complex real-world scenarios"""
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_multiple_content_locations_same_volume(self, mock_get_outline):
        """Test handling multiple content locations in the same volume"""
        g = Graph()
        
        # First content location
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEtext, Literal(1)))
        g.add((cl1, BDO.contentLocationIdInEtext, Literal("m1")))
        g.add((cl1, BDO.contentLocationEndIdInEtext, Literal("m2")))
        
        # Second content location
        mw2 = BDR.MW2
        cl2 = BDR.CL2
        
        g.add((mw2, BDO.contentLocation, cl2))
        g.add((cl2, BDO.contentLocationInstance, ie1))
        g.add((cl2, BDO.contentLocationVolume, Literal(1)))
        g.add((cl2, BDO.contentLocationEtext, Literal(2)))
        g.add((cl2, BDO.contentLocationIdInEtext, Literal("m3")))
        g.add((cl2, BDO.contentLocationEndIdInEtext, Literal("m4")))
        
        mock_get_outline.return_value = g
        
        oel = OutlineEtextLookup("O1", "IE1")
        segments = oel.get_volume_segments(1)
        
        # Should get 2 segments
        self.assertEqual(len(segments), 2)
        
        # Check that we have both MWs
        mws = [seg["mw"] for seg in segments]
        self.assertIn("MW1", mws)
        self.assertIn("MW2", mws)
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_backward_compatibility_get_mw_for(self, mock_get_outline):
        """Test that deprecated get_mw_for still works for simple cases"""
        g = Graph()
        mw1 = BDR.MW1
        cl1 = BDR.CL1
        ie1 = BDR.IE1
        
        g.add((mw1, BDO.contentLocation, cl1))
        g.add((cl1, BDO.contentLocationInstance, ie1))
        g.add((cl1, BDO.contentLocationVolume, Literal(1)))
        g.add((cl1, BDO.contentLocationEtext, Literal(1)))
        g.add((cl1, BDO.contentLocationEndEtext, Literal(3)))
        
        mock_get_outline.return_value = g
        
        oel = OutlineEtextLookup("O1", "IE1")
        
        # Test that get_mw_for returns the right MW for etexts in range
        self.assertEqual(oel.get_mw_for(1, 1), "MW1")
        self.assertEqual(oel.get_mw_for(1, 2), "MW1")
        self.assertEqual(oel.get_mw_for(1, 3), "MW1")
        # Outside range should return None
        self.assertIsNone(oel.get_mw_for(1, 4))
        self.assertIsNone(oel.get_mw_for(2, 1))
    
    def test_integration_full_flow(self):
        """Integration test: Full flow from outline to text extraction"""
        # Create a simple XML document
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      <p>Introduction text</p>
      <milestone xml:id="chapter1" unit="section"/>
      <p>Chapter 1 content goes here</p>
      <milestone xml:id="chapter2" unit="section"/>
      <p>Chapter 2 content goes here</p>
      <milestone xml:id="chapter3" unit="section"/>
      <p>Chapter 3 content goes here</p>
    </body>
  </text>
</TEI>"""
        
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.fromstring(xml_content.encode('utf-8'), parser)
        
        # Test extracting different segments
        # Extract introduction (before chapter1)
        intro_seg = EtextSegment(tree, None, "chapter1")
        intro_text = intro_seg.extract_text()
        self.assertIn("Introduction", intro_text)
        self.assertNotIn("Chapter 1", intro_text)
        
        # Extract chapter 1 (between chapter1 and chapter2)
        ch1_seg = EtextSegment(tree, "chapter1", "chapter2")
        ch1_text = ch1_seg.extract_text()
        self.assertIn("Chapter 1", ch1_text)
        self.assertNotIn("Introduction", ch1_text)
        self.assertNotIn("Chapter 2", ch1_text)
        
        # Extract from chapter 2 to end
        ch2_to_end = EtextSegment(tree, "chapter2", None)
        ch2_text = ch2_to_end.extract_text()
        self.assertIn("Chapter 2", ch2_text)
        self.assertIn("Chapter 3", ch2_text)
        self.assertNotIn("Introduction", ch2_text)


if __name__ == '__main__':
    unittest.main()
