"""Tests for TEI to text conversion.

This test suite validates the TEI/XML to standoff text conversion functionality.
Now using the standalone tei_to_standoff module with minimal dependencies.
"""
import unittest
from lxml import etree
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the conversion function from the new standalone module
from bdrc_etext_sync.tei_to_standoff import convert_tei_root_to_standoff


class TestTEIConversionOldFormat(unittest.TestCase):
    """Test conversion of old format with xml:space='preserve'"""
    
    def test_old_format_with_preserve(self):
        """Test the old format that has xml:space='preserve'"""
        test_xml = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body xml:space="preserve">
      <pb n="122"/>
      <p>This is the first paragraph.
This is on a new line.</p>
      <pb n="123"/>
      This is on a new page.
      This is on a new line
      <pb n="124"/>
      This starts a <hi rend="small">highlight</hi> text.
    </body>
  </text>
</TEI>
"""
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
        tree = etree.fromstring(test_xml.encode('utf-8'), parser)
        
        text, annotations, source_path = convert_tei_root_to_standoff(tree)
        
        # Check that text is properly formatted
        self.assertIn("This is the first paragraph.", text)
        self.assertIn("highlight", text)
        
        # Check that pages are properly tracked
        self.assertIn("pages", annotations)
        self.assertEqual(len(annotations["pages"]), 3)
        
        # Check that hi annotations are tracked
        self.assertIn("hi", annotations)
        self.assertTrue(any(ann["rend"] == "small" for ann in annotations["hi"]))
        
        # Should not have new format features
        self.assertNotIn("milestones", annotations)
        self.assertNotIn("div_boundaries", annotations)
    
    def test_old_format_preserve_on_p_element(self):
        """Test the old format with xml:space='preserve' on p element (not on body)"""
        test_xml = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body xml:lang="bo">
      <p xml:space="preserve">
<pb n="1a"/>
<lb/>༄༅། །ཆོས་མངོན་པ་མཛོད་ཀྱི་འགྲེལ་པ་མངོན་པའི་རྒྱན་གྱི་དཀར་ཆག་དང་ས་བཅད་གླེང་བརྗོད་བཅས་བཞུགས་སོ༎
<pb n="1b"/>
<lb/>༄༅། །ཨོཾ་སྭ་སྟི། །གང་གི་མཚན་ཙམ་ལན་ཅིག་ཐོས་པས་ཀྱང་། །མཚམས་མེད་ལས་ལ་སྤྱོད་པའི་སྡིག་ཅན་ཡང་། །ཕྱི་མ་ངན་འགྲོའི་འཇིགས་ལས་སྐྱོབ་མཛད་
<pb n="2a"/>
<lb/>༄༅། །དབྱེ་བ་དང་། མཚན་ཉིད་དང་། དགོས་པ་དང་། གྲངས་ངེས་དང་། གོ་རིམས་ངེས་པ་ལྔ་བཤད་པ།
</p>
</body>
</text>
</TEI>
"""
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
        tree = etree.fromstring(test_xml.encode('utf-8'), parser)
        
        text, annotations, source_path = convert_tei_root_to_standoff(tree)
        
        # Check that Tibetan text is present
        self.assertIn("༄༅།", text)
        self.assertIn("ཆོས་མངོན་པ་མཛོད་ཀྱི་འགྲེལ་པ་མངོན་པའི་རྒྱན་གྱི་དཀར་ཆག", text)
        
        # Check that pages are properly tracked
        self.assertIn("pages", annotations)
        self.assertEqual(len(annotations["pages"]), 3)
        
        # Check page names
        page_names = [p["pname"] for p in annotations["pages"]]
        self.assertIn("1a", page_names)
        self.assertIn("1b", page_names)
        self.assertIn("2a", page_names)
        
        # Should not have new format features
        self.assertNotIn("milestones", annotations)
        self.assertNotIn("div_boundaries", annotations)


class TestTEIConversionNewFormat(unittest.TestCase):
    """Test conversion of new format without xml:space='preserve'"""
    
    def test_new_format_with_milestones_and_heads(self):
        """Test the new format with milestones, divs, and head elements"""
        test_xml = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body xml:lang="bo">
      <milestone xml:id="div1_0001" unit="section"/>
      <div>
        <head>མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།</head>
        <p>༄༅། ལྕམ་བླ་འགྱུར་མེད་རྒྱལ་མཚན་ནི། རབ་བྱུང་བཅུ་གསུམ་པའི་ནང་མི་ཉག་ལྕམ་པ་ཉི་འོད་སྡེ་བར་སྐུ་འཁྲུངས། </p>
      </div>
      <milestone xml:id="div1_0002" unit="section"/>
      <div>
        <head>སྔོན་འགྲོ་ཐར་ལམ་གསལ་བྱེད།</head>
        <p>༄༅། སྔོན་འགྲོ་ཆོས་སྤྱོད་ཀྱི་རིམ་པ་ཐར་ལམ་གསལ་བྱེད་ཕན་བདེ་ཉི་མ་ཞེས་བྱ་བ་བཞུགས་སོ། །</p>
      </div>
    </body>
  </text>
</TEI>
"""
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
        tree = etree.fromstring(test_xml.encode('utf-8'), parser)
        
        text, annotations, source_path = convert_tei_root_to_standoff(tree)
        
        # Check that text contains the content
        self.assertIn("མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།", text)
        self.assertIn("སྔོན་འགྲོ་ཐར་ལམ་གསལ་བྱེད།", text)
        
        # Check that milestones are tracked
        self.assertIn("milestones", annotations)
        self.assertIn("div1_0001", annotations["milestones"])
        self.assertIn("div1_0002", annotations["milestones"])
        self.assertEqual(len(annotations["milestones"]), 2)
        
        # Check that head elements are in hi annotations
        self.assertIn("hi", annotations)
        head_annos = [ann for ann in annotations["hi"] if ann["rend"] == "head"]
        self.assertEqual(len(head_annos), 2, "Expected 2 head annotations")
        
        # Check proper spacing (two line breaks around heads, between divs)
        # Should have proper spacing but max 2 consecutive line breaks
        self.assertNotIn("\n\n\n", text, "Should not have more than 2 consecutive line breaks")
        
        # Check that milestone elements are not in the text
        self.assertNotIn("milestone", text.lower())
        self.assertNotIn("div1_0001", text)
        self.assertNotIn("div1_0002", text)
        
        # Check that div boundaries are tracked for chunking
        self.assertIn("div_boundaries", annotations)
        self.assertEqual(len(annotations["div_boundaries"]), 2)


if __name__ == '__main__':
    unittest.main()
