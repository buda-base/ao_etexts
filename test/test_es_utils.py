"""Tests for TEI to text conversion in es_utils.py"""
import unittest
import sys
import os
from lxml import etree

# Add parent directory to path to import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from bdrc_etext_sync.es_utils import convert_tei_root_to_text


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
        
        text, annotations, source_path = convert_tei_root_to_text(tree)
        
        # Check that text is properly formatted
        self.assertIn("This is the first paragraph.", text)
        self.assertIn("highlight", text)
        
        # Check that pages are properly tracked
        self.assertIn("pages", annotations)
        self.assertEqual(len(annotations["pages"]), 3)
        
        # Check that hi annotations are tracked
        self.assertIn("hi", annotations)
        self.assertTrue(any(ann["rend"] == "small" for ann in annotations["hi"]))


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
        
        text, annotations, source_path = convert_tei_root_to_text(tree)
        
        # Check that text contains the content
        self.assertIn("མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།", text)
        self.assertIn("སྔོན་འགྲོ་ཐར་ལམ་གསལ་བྱེད།", text)
        
        # Check that milestones are tracked
        self.assertIn("milestones", annotations)
        self.assertIn("div1_0001", annotations["milestones"])
        self.assertIn("div1_0002", annotations["milestones"])
        
        # Check that head elements are in hi annotations
        self.assertIn("hi", annotations)
        head_annos = [ann for ann in annotations["hi"] if ann["rend"] == "head"]
        self.assertEqual(len(head_annos), 2)
        
        # Check proper spacing (two line breaks around heads, between divs)
        # Should have proper spacing but max 2 consecutive line breaks
        self.assertNotIn("\n\n\n", text)
        
        # Check that milestone elements are not in the text
        self.assertNotIn("milestone", text)
        self.assertNotIn("div1_0001", text)


if __name__ == '__main__':
    unittest.main()
