"""Tests for OutlineEtextLookup in buda_api.py

This test suite validates the handling of contentLocationIdInEtext and
contentLocationEndIdInEtext in the outline lookup structure.
"""
import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rdflib import Graph, Namespace, Literal, URIRef
from bdrc_etext_sync.buda_api import OutlineEtextLookup

BDR = Namespace("http://purl.bdrc.io/resource/")
BDO = Namespace("http://purl.bdrc.io/ontology/core/")


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
    def test_get_content_locations_for_volume(self, mock_get_outline):
        """Test getting content locations for a specific volume"""
        mock_get_outline.return_value = self.create_mock_graph_simple()
        
        oel = OutlineEtextLookup("O1", "IE1")
        cls = oel.get_content_locations_for_volume(1)
        
        self.assertEqual(len(cls), 1)
        cl = cls[0]
        self.assertEqual(cl["mw"], "MW1")
        self.assertEqual(cl["id_in_etext"], "m1")
        self.assertEqual(cl["end_id_in_etext"], "m2")
    
    @patch('bdrc_etext_sync.buda_api.get_outline_graph')
    def test_spanning_etexts_with_ids(self, mock_get_outline):
        """Test extracting segment spanning multiple etexts with IDs"""
        mock_get_outline.return_value = self.create_mock_graph_spanning_etexts()
        
        oel = OutlineEtextLookup("O1", "IE1")
        cls = oel.get_content_locations_for_volume(1)
        
        self.assertEqual(len(cls), 1)
        cl = cls[0]
        self.assertEqual(cl["mw"], "MW1")
        self.assertEqual(cl["etextnum_start"], 1)
        self.assertEqual(cl["etextnum_end"], 3)
        self.assertEqual(cl["id_in_etext"], "m1")
        self.assertEqual(cl["end_id_in_etext"], "m2")
    
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
        cls = oel.get_content_locations_for_volume(1)
        
        self.assertEqual(len(cls), 1)
        cl = cls[0]
        # start_id should be None (meaning from beginning)
        self.assertIsNone(cl["id_in_etext"])
        self.assertEqual(cl["end_id_in_etext"], "m1")
    
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
        cls = oel.get_content_locations_for_volume(1)
        
        self.assertEqual(len(cls), 1)
        cl = cls[0]
        # end_id should be None (meaning to end)
        self.assertEqual(cl["id_in_etext"], "m1")
        self.assertIsNone(cl["end_id_in_etext"])


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
        cls = oel.get_content_locations_for_volume(1)
        
        # Should get 2 content locations
        self.assertEqual(len(cls), 2)
        
        # Check that we have both MWs
        mws = [cl["mw"] for cl in cls]
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


if __name__ == '__main__':
    unittest.main()
