import os
import re
import hashlib
import xml.etree.ElementTree as ET
from lxml import etree
import requests
from rdflib import Graph, URIRef
from urllib.parse import urlparse
import logging
from importlib import resources

def get_volumes(ie_lname):
    """
    Fetch RDF data for a given IE resource and extract volume local names.
    
    Args:
        ie_lname (str): Local name of the instance entity
        
    Returns:
        list: Local names of the volumes associated with the instance
        
    Raises:
        Exception: If HTTP response is not 200 or if RDF parsing fails
    """
    # Construct the URL for the resource
    url = f"https://ldspdi-dev.bdrc.io/resource/{ie_lname}.ttl"
    
    # Fetch the data
    response = requests.get(url)
    
    # Check if response is successful
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data: HTTP {response.status_code}")
    
    # Initialize RDF graph
    g = Graph()
    
    try:
        # Parse the Turtle data
        g.parse(data=response.text, format="turtle")
        
        # Check if graph is empty
        if len(g) == 0:
            raise Exception("Empty RDF graph - no data found")
            
    except Exception as e:
        raise Exception(f"Failed to parse RDF data: {str(e)}")
    
    # Construct the resource URI and property URI
    resource_uri = URIRef(f"http://purl.bdrc.io/resource/{ie_lname}")
    property_uri = URIRef("http://purl.bdrc.io/ontology/core/instanceHasVolume")
    
    # Find all objects of the property for the given resource
    volume_uris = [obj for obj in g.objects(resource_uri, property_uri)]
    
    # Extract local names (everything after the last '/')
    volume_local_names = []
    for uri in volume_uris:
        path = urlparse(uri).path
        local_name = path.split('/')[-1]
        volume_local_names.append(local_name)
    
    return volume_local_names

def validate_files_and_log(args):
    logging.info(f"Validating files for ID: {args.id} in directory: {args.filesdir}")
    passed, warns, errors = validate_files(args)
    logging.warn("Validation %s with %d warning(s) and %d error(s)", "passed" if passed else "failed", len(warns), len(errors))
    if warns:
        logging.warn("Validation warnings:")
        for warn in warns:
            logging.warn("  "+warn)
    if errors:
        logging.error("Validation errors:")
        for error in errors:
            logging.error("  "+error)

def validate_files(args):
    """Validates files for a specific ID in the given directory.
    returns two values:
      passed (boolean)
      warns (list of warning strings)
      errors (list of error strings)
    """
    errors = []
    warns = []
    
    # Catch exception in get_volumes
    try:
        volume_names = get_volumes(args.id)
    except Exception as e:
        errors.append(f"Failed to get volume names: {str(e)}")
        return False, warns, errors
    
    # Check if there's at least one volume
    if not volume_names:
        errors.append("No volume names found. There should be at least one volume.")
        return False, warns, errors
    
    # Check if archive directory exists
    archive_dir = os.path.join(args.filesdir, "archive")
    if not os.path.isdir(archive_dir):
        errors.append(f"Required 'archive' directory not found in {args.filesdir}")
        return False, warns, errors
    
    # Check if sources directory exists (optional)
    sources_dir = os.path.join(args.filesdir, "sources")
    sources_exist = os.path.isdir(sources_dir)
    if not sources_exist:
        warns.append(f"Optional 'sources' directory not found in {args.filesdir}")
    
    # Get all directories in archive folder
    archive_subdirs = [d for d in os.listdir(archive_dir) 
                       if os.path.isdir(os.path.join(archive_dir, d))]
    
    # Check that archive has at least one volume
    if not archive_subdirs:
        errors.append(f"No volume subdirectories found in {archive_dir}")
        return False, warns, errors
    
    # Check that all subdirectories correspond to volume names
    for subdir in archive_subdirs:
        if subdir not in volume_names:
            errors.append(f"Directory {subdir} in archive/ does not match any volume name")
    
    # Process each volume directory
    found_valid_volume = False
    for volume in archive_subdirs:
        if volume in volume_names:
            found_valid_volume = True
            volume_dir = os.path.join(archive_dir, volume)
            all_files = os.listdir(volume_dir)
            
            # Check for non-XML files and invalid filenames
            xml_files = []
            for filename in all_files:
                filepath = os.path.join(volume_dir, filename)
                
                # Check if it's a file (not a directory)
                if not os.path.isfile(filepath):
                    errors.append(f"Found directory {filename} in volume {volume}, only files allowed")
                    continue
                
                # Check file extension
                if not filename.endswith(".xml"):
                    errors.append(f"File {filename} in volume {volume} does not end with .xml")
                    continue
                
                # Check filename format: volume_NNNN.xml
                pattern = f"^UT[A-Z0-9]+_([0-9]{{4}})\\.xml$"
                match = re.match(pattern, filename)
                if not match:
                    errors.append(f"File {filename} in volume {volume} does not follow naming pattern UTXXX_NNNN.xml")
                    continue
                
                xml_files.append((filename, int(match.group(1))))
            
            # Check that there's at least one file
            if not xml_files:
                errors.append(f"No valid XML files found in volume {volume}")
                continue
            
            # Check for sequence gaps
            sorted_files = sorted(xml_files, key=lambda x: x[1])
            expected_sequence = list(range(1, len(sorted_files) + 1))
            actual_sequence = [num for _, num in sorted_files]
            
            if actual_sequence != expected_sequence:
                errors.append(f"Files in volume {volume} don't form a continuous sequence starting from 0001. Found: {actual_sequence}")
            
            # Check each XML file
            for filename, _ in sorted_files:
                filepath = os.path.join(volume_dir, filename)
                
                # Check if it's a valid XML file
                try:
                    tree = ET.parse(filepath)
                    root = tree.getroot()
                except ET.ParseError as e:
                    errors.append(f"File {filename} in volume {volume} is not a valid XML: {str(e)}")
                    continue
                
                # Validate against TEI schema
                try:
                    with resources.path('bdrc_etext_sync.schemas', 'tei_lite.rng') as schema_path:
                        # This part assumes you have access to the TEI schema
                        # You might need to adjust this based on how you handle schemas
                        tei_schema = etree.RelaxNG(file=schema_path)
                        xml_doc = etree.parse(filepath)
                        is_valid = tei_schema.validate(xml_doc)
                        if not is_valid:
                            errors.append(f"File {filename} in volume {volume} is not a valid TEI XML: {tei_schema.error_log}")
                except Exception as e:
                    errors.append(f"Error validating TEI for {filename} in volume {volume}: {str(e)}")
                    continue
                
                # Check source references if sources directory exists
                if sources_exist:
                    try:
                        # Parse with lxml for better namespace handling
                        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
                        xml_doc = etree.parse(filepath)
                        
                        # Find SRC_PATH elements
                        src_paths = xml_doc.xpath("//tei:idno[@type='src_path']/text()", namespaces=ns)
                        for src_path in src_paths:
                            full_src_path = os.path.join(sources_dir, src_path)
                            
                            # Check if source file exists
                            if not os.path.isfile(full_src_path):
                                errors.append(f"Source file {src_path} referenced in {filename} not found in sources directory")
                                continue
                            
                            # Get sha256 elements that are siblings to SRC_PATH
                            xpath = f"//tei:idno[@type='src_path'][text()='{src_path}']/following-sibling::tei:idno[@type='src_sha256']/text()"
                            sha256_values = xml_doc.xpath(xpath, namespaces=ns)
                            
                            if not sha256_values:
                                warns.append(f"No sha256 checksum found for source {src_path} in {filename}")
                                continue
                            
                            # Calculate actual checksum
                            with open(full_src_path, 'rb') as f:
                                file_data = f.read()
                                actual_checksum = hashlib.sha256(file_data).hexdigest()
                            
                            # Verify checksum
                            if sha256_values[0] != actual_checksum:
                                errors.append(f"SHA256 checksum mismatch for {src_path} in {filename}. "
                                             f"Expected: {sha256_values[0]}, Got: {actual_checksum}")
                    except Exception as e:
                        errors.append(f"Error checking source references in {filename}: {str(e)}")
    
    # Check if we found at least one valid volume
    if not found_valid_volume:
        errors.append("No valid volumes found in archive directory")
    
    # Function passes if there are no errors
    passed = len(errors) == 0
    return passed, warns, errors
