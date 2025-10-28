"""Tests for TEI to standoff text conversion.

This test suite validates the TEI/XML to standoff text conversion functionality
using the standalone tei_to_standoff module with minimal dependencies.

Tests are data-driven using XML fixtures and corresponding JSON expectation files.
"""
import unittest
from lxml import etree
import sys
import os
import json
import glob

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the conversion function from the new standalone module
from bdrc_etext_sync.tei_to_standoff import convert_tei_root_to_standoff


def debug_annotations(text, annotations):
    """Create a debug view of text with annotation boundaries marked."""
    # Create a list of annotation boundaries to insert
    boundaries = []
    
    for anno_type, anno_list in annotations.items():
        if anno_type == "milestones" or anno_type == "div_boundaries":
            # Skip these annotation types
            continue
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


def test_conversion():
    """Test the TEI to text conversion with a sample XML string (legacy test)."""
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
    
    # Convert the test XML
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    tree = etree.fromstring(test_xml.encode('utf-8'), parser)
    text, annotations, source_path = convert_tei_root_to_standoff(tree)
    text_with_anns = debug_annotations(text, annotations)
    
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

The spelling cat was fixed.

[/pages]"""
    
    print("Test passed!" if text_with_anns == expected else "Test failed!")


class TestTEIConversionFromFixtures(unittest.TestCase):
    """Test conversion using XML fixtures and JSON expectation files."""
    
    @classmethod
    def setUpClass(cls):
        """Load all test fixtures."""
        cls.fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures', 'tei_to_standoff')
        cls.test_cases = []
        
        # Find all XML files
        xml_files = glob.glob(os.path.join(cls.fixtures_dir, '*.xml'))
        
        for xml_file in xml_files:
            base_name = os.path.splitext(xml_file)[0]
            json_file = base_name + '.json'
            
            if os.path.exists(json_file):
                test_name = os.path.basename(base_name)
                cls.test_cases.append({
                    'name': test_name,
                    'xml_file': xml_file,
                    'json_file': json_file
                })
    
    def _test_fixture(self, test_case):
        """Run a test for a given fixture."""
        # Load XML
        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
        tree = etree.parse(test_case['xml_file'], parser)
        root = tree.getroot()
        
        # Convert
        text, annotations, source_path = convert_tei_root_to_standoff(root)
        
        # Load expectations
        with open(test_case['json_file'], 'r', encoding='utf-8') as f:
            expected = json.load(f)
        
        # Verify text
        self.assertEqual(text, expected['text'], 
                        f"Text mismatch in {test_case['name']}")
        
        # Verify source_path
        self.assertEqual(source_path, expected['source_path'],
                        f"Source path mismatch in {test_case['name']}")
        
        # Verify annotations structure
        expected_annotations = expected.get('annotations', {})
        
        # Check milestones
        if expected.get('has_milestones', False):
            self.assertIn('milestones', annotations,
                         f"Expected milestones in {test_case['name']}")
            if 'milestones' in expected_annotations:
                for ms_id, ms_pos in expected_annotations['milestones'].items():
                    self.assertIn(ms_id, annotations['milestones'],
                                 f"Missing milestone {ms_id} in {test_case['name']}")
                    self.assertEqual(annotations['milestones'][ms_id], ms_pos,
                                   f"Milestone {ms_id} position mismatch in {test_case['name']}")
        else:
            self.assertNotIn('milestones', annotations,
                           f"Unexpected milestones in {test_case['name']}")
        
        # Check div_boundaries
        if expected.get('has_div_boundaries', False):
            self.assertIn('div_boundaries', annotations,
                         f"Expected div_boundaries in {test_case['name']}")
            if 'div_boundaries' in expected_annotations:
                self.assertEqual(len(annotations['div_boundaries']), 
                               len(expected_annotations['div_boundaries']),
                               f"div_boundaries count mismatch in {test_case['name']}")
        else:
            self.assertNotIn('div_boundaries', annotations,
                           f"Unexpected div_boundaries in {test_case['name']}")
        
        # Check pages
        if 'pages' in expected_annotations:
            self.assertIn('pages', annotations,
                         f"Expected pages in {test_case['name']}")
            expected_pages = expected_annotations['pages']
            actual_pages = annotations['pages']
            
            self.assertEqual(len(actual_pages), len(expected_pages),
                           f"Pages count mismatch in {test_case['name']}")
            
            for i, expected_page in enumerate(expected_pages):
                actual_page = actual_pages[i]
                if 'pname' in expected_page:
                    self.assertEqual(actual_page['pname'], expected_page['pname'],
                                   f"Page {i} name mismatch in {test_case['name']}")
                if 'pnum' in expected_page:
                    self.assertEqual(actual_page['pnum'], expected_page['pnum'],
                                   f"Page {i} number mismatch in {test_case['name']}")
                if 'cstart' in expected_page:
                    self.assertEqual(actual_page['cstart'], expected_page['cstart'],
                                   f"Page {i} cstart mismatch in {test_case['name']}")
        
        # Check hi annotations
        if 'hi' in expected_annotations:
            self.assertIn('hi', annotations,
                         f"Expected hi annotations in {test_case['name']}")
            expected_hi = expected_annotations['hi']
            actual_hi = annotations['hi']
            
            # Check count matches
            self.assertEqual(len(actual_hi), len(expected_hi),
                           f"Hi annotations count mismatch in {test_case['name']}")
            
            # Check each hi has expected rend value
            for i, expected_h in enumerate(expected_hi):
                if 'rend' in expected_h:
                    actual_h = actual_hi[i]
                    self.assertEqual(actual_h['rend'], expected_h['rend'],
                                   f"Hi {i} rend mismatch in {test_case['name']}")


def load_tests(loader, tests, pattern):
    """Dynamically generate test methods for each fixture."""
    suite = unittest.TestSuite()
    
    # Add the fixture-based tests
    test_class = TestTEIConversionFromFixtures
    test_class.setUpClass()
    
    for test_case in test_class.test_cases:
        test_name = f"test_{test_case['name'].replace('-', '_')}"
        
        # Create a test method dynamically
        def make_test(tc):
            def test(self):
                self._test_fixture(tc)
            return test
        
        test_method = make_test(test_case)
        test_method.__name__ = test_name
        test_method.__doc__ = f"Test conversion for {test_case['name']}"
        
        # Add the test method to the test class
        setattr(test_class, test_name, test_method)
        
        # Add to suite
        suite.addTest(test_class(test_name))
    
    return suite


if __name__ == '__main__':
    # Run test_conversion for manual testing
    if len(sys.argv) > 1 and sys.argv[1] == '--demo':
        test_conversion()
    else:
        unittest.main()
