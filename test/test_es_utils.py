"""Tests for TEI to text conversion in es_utils.py

Note: Due to complex dependencies (fs, opensearchpy, rdflib, etc.), this test
imports and tests only the core conversion function by directly loading the needed
components from es_utils.py.
"""
import unittest
from lxml import etree
import re
from bisect import bisect
from copy import deepcopy as python_deepcopy

# Import just the functions we need for testing
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# We'll import the functions directly by executing just the conversion-related code
# This avoids all the OpenSearch, fs, and other dependencies


def deepcopy(element):
    return python_deepcopy(element)


def replace_element(old_element, new_element=None):
    """Replace or remove an XML element while preserving content structure."""
    parent = old_element.getparent()
    if parent is None:
        raise ValueError("Cannot replace/remove the root element")
    tail_text = old_element.tail
    if new_element is None:
        prev_sibling = old_element.getprevious()
        parent.remove(old_element)
        if tail_text:
            if prev_sibling is not None:
                if prev_sibling.tail:
                    prev_sibling.tail += tail_text
                else:
                    prev_sibling.tail = tail_text
            else:
                if parent.text:
                    parent.text += tail_text
                else:
                    parent.text = tail_text
    else:
        new_element.tail = tail_text
        parent.replace(old_element, new_element)


# Load the actual convert_tei_root_to_text function
exec(compile(open(os.path.join(os.path.dirname(__file__), '..', 'bdrc_etext_sync', 'es_utils.py')).read()
                  .replace('from opensearchpy import', '#from opensearchpy import')
                  .replace('from .chunkers import', '#from .chunkers import')
                  .replace('from .buda_api import', '#from .buda_api import')
                  .replace('from .fs_utils import', '#from .fs_utils import')
                  .replace('import fs.path', '#import fs.path')
                  .replace('import logging', 'import logging; logging.basicConfig(level=logging.ERROR)'),
             '<string>', 'exec'))


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
        
        text, annotations, source_path = convert_tei_root_to_text(tree)
        
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
        
        text, annotations, source_path = convert_tei_root_to_text(tree)
        
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
