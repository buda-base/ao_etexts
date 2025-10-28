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
        
        # Build actual result
        actual = {
            "text": text,
            "annotations": annotations,
            "source_path": source_path
        }
        
        # Compare using deepdiff
        from deepdiff import DeepDiff
        diff = DeepDiff(expected, actual, ignore_order=False)
        
        # Assert no differences
        self.assertEqual(diff, {}, 
                        f"Mismatch in {test_case['name']}:\n{diff}")


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


def generate_expected_json(xml_file_path):
    """
    Generate a JSON string with the expected format for a fixture test.
    
    This helper function converts a TEI XML file and returns a JSON string
    in the exact format expected by the test fixtures. Use this to easily
    create new test fixtures.
    
    Args:
        xml_file_path: Path to the XML file to convert
        
    Returns:
        A JSON string with the expected format containing:
        - text: The converted plain text
        - annotations: The standoff annotations
        - source_path: The source path (or null)
    
    Example:
        >>> json_str = generate_expected_json('test.xml')
        >>> print(json_str)
        >>> # Save to a .json file to create a new fixture
    """
    from lxml import etree
    import json
    
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    tree = etree.parse(xml_file_path, parser)
    root = tree.getroot()
    text, annotations, source_path = convert_tei_root_to_standoff(root)
    
    expected = {
        "text": text,
        "annotations": annotations,
        "source_path": source_path
    }
    
    return json.dumps(expected, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    # Run test_conversion for manual testing
    if len(sys.argv) > 1 and sys.argv[1] == '--demo':
        test_conversion()
    else:
        unittest.main()
