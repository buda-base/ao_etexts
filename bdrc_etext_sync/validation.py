import os
import re
import hashlib
from lxml import etree
import requests
from rdflib import Graph, URIRef
from urllib.parse import urlparse
import logging
from importlib import resources
from .fs_utils import _id_subdir_path
from .validate_normalization import validate_tei_file_normalization, validate_tei_root_normalization
from .validate_tei_subset import validate_tei_subset, validate_tei_root_subset

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
    logger = logging.getLogger(__name__)
    logger.debug("Fetching volume names for IE: %s", ie_lname)
    
    # Construct the URL for the resource
    url = f"https://ldspdi.bdrc.io/resource/{ie_lname}.ttl"
    logger.debug("Fetching RDF data from: %s", url)
    
    # Fetch the data
    response = requests.get(url)
    
    # Check if response is successful
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data: HTTP {response.status_code}")
    
    logger.debug("Successfully fetched RDF data (status: %d)", response.status_code)
    
    # Initialize RDF graph
    g = Graph()
    
    try:
        # Parse the Turtle data
        g.parse(data=response.text, format="turtle")
        logger.debug("Parsed RDF graph with %d triples", len(g))
        
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
    logger.debug("Found %d volume URI(s)", len(volume_uris))
    
    # Extract local names (everything after the last '/')
    volume_local_names = []
    for uri in volume_uris:
        path = urlparse(uri).path
        local_name = path.split('/')[-1]
        volume_local_names.append(local_name)
    
    logger.info("Found %d volume(s) for IE %s: %s", len(volume_local_names), ie_lname, volume_local_names)
    return volume_local_names

def validate_files_and_log(args):
    logging.info(f"Validating files for ID: {args.id} in directory: {args.filesdir}")
    passed, warns, errors = validate_files(args.id, _id_subdir_path(args.filesdir, args.id))
    logging.info("Validation %s with %d warning(s) and %d error(s)", "passed" if passed else "failed", len(warns), len(errors))
    if warns:
        logging.warn("Validation warnings:")
        for warn in warns:
            logging.warn("  "+warn)
    if errors:
        logging.error("Validation errors:")
        for error in errors:
            logging.error("  "+error)
    return passed, warns, errors

def validate_files(eid, filesdir):
    """Validates files for a specific ID in the given directory.
    returns two values:
      passed (boolean)
      warns (list of warning strings)
      errors (list of error strings)
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting validation for ID: %s in directory: %s", eid, filesdir)
    
    errors = []
    warns = []
    
    # Catch exception in get_volumes
    try:
        logger.debug("Fetching volume names from RDF...")
        volume_names = get_volumes(eid)
    except Exception as e:
        logger.error("Failed to get volume names: %s", str(e))
        errors.append(f"Failed to get volume names for {eid}: {str(e)}")
        return False, warns, errors
    
    # Check if there's at least one volume
    if not volume_names:
        logger.error("No volume names found")
        errors.append("No volume names found. There should be at least one volume.")
        return False, warns, errors
    
    # Check if archive directory exists
    archive_dir = os.path.join(filesdir, "archive")
    logger.debug("Checking for archive directory: %s", archive_dir)
    if not os.path.isdir(archive_dir):
        logger.error("Archive directory not found: %s", archive_dir)
        errors.append(f"Required 'archive' directory not found in {filesdir}")
        return False, warns, errors
    logger.debug("Archive directory found")
    
    # Check if sources directory exists (optional)
    sources_dir = os.path.join(filesdir, "sources")
    sources_exist = os.path.isdir(sources_dir)
    if not sources_exist:
        logger.debug("Optional sources directory not found: %s", sources_dir)
        warns.append(f"Optional 'sources' directory not found in {filesdir}")
    else:
        logger.debug("Sources directory found: %s", sources_dir)
    
    # Get all directories in archive folder
    archive_subdirs = [d for d in os.listdir(archive_dir) 
                       if os.path.isdir(os.path.join(archive_dir, d))]
    logger.debug("Found %d subdirectory(ies) in archive: %s", len(archive_subdirs), archive_subdirs)

    archive_subdirs = sorted(archive_subdirs)
    
    # Check that archive has at least one volume
    if not archive_subdirs:
        logger.error("No volume subdirectories found in archive")
        errors.append(f"No volume subdirectories found in {archive_dir}")
        return False, warns, errors
    
    # Check that all subdirectories correspond to volume names
    logger.debug("Checking that archive subdirectories match volume names...")
    for subdir in archive_subdirs:
        if subdir not in volume_names:
            logger.warning("Directory %s in archive/ does not match any volume name", subdir)
            errors.append(f"Directory {subdir} in archive/ does not match any volume name")
    
    # Process each volume directory
    found_valid_volume = False
    logger.info("Processing %d volume(s)...", len(archive_subdirs))
    for volume in archive_subdirs:
        if volume in volume_names:
            found_valid_volume = True
            logger.info("Processing volume: %s", volume)
            volume_dir = os.path.join(archive_dir, volume)
            all_files = os.listdir(volume_dir)
            logger.debug("Found %d file(s) in volume %s", len(all_files), volume)
            
            # Check for non-XML files and invalid filenames
            xml_files = []
            for filename in all_files:
                filepath = os.path.join(volume_dir, filename)
                
                # Check if it's a file (not a directory)
                if not os.path.isfile(filepath):
                    logger.warning("Found directory %s in volume %s (only files allowed)", filename, volume)
                    errors.append(f"Found directory {filename} in volume {volume}, only files allowed")
                    continue
                
                # Check file extension
                if not filename.endswith(".xml"):
                    logger.warning("File %s in volume %s does not end with .xml", filename, volume)
                    errors.append(f"File {filename} in volume {volume} does not end with .xml")
                    continue
                
                # Check filename format: volume_NNNN.xml
                pattern = r"^UT[A-Z_\-0-9]+_([0-9]{4})\.xml$"
                match = re.match(pattern, filename)
                if not match:
                    logger.warning("File %s in volume %s does not follow naming pattern", filename, volume)
                    errors.append(f"File {filename} in volume {volume} does not follow naming pattern UTXXX_NNNN.xml")
                    continue
                
                xml_files.append((filename, int(match.group(1))))
            
            logger.debug("Found %d valid XML file(s) in volume %s", len(xml_files), volume)
            
            # Check that there's at least one file
            if not xml_files:
                logger.error("No valid XML files found in volume %s", volume)
                errors.append(f"No valid XML files found in volume {volume}")
                continue
            
            # Check for sequence gaps
            sorted_files = sorted(xml_files, key=lambda x: x[1])
            expected_sequence = list(range(1, len(sorted_files) + 1))
            actual_sequence = [num for _, num in sorted_files]
            
            logger.debug("File sequence in volume %s: %s", volume, actual_sequence)
            if actual_sequence != expected_sequence:
                logger.warning("File sequence gap in volume %s: expected %s, found %s", volume, expected_sequence, actual_sequence)
                errors.append(f"Files in volume {volume} don't form a continuous sequence starting from 0001. Found: {actual_sequence}")
            
            # Check each XML file
            logger.info("Validating %d XML file(s) in volume %s...", len(sorted_files), volume)
            for file_idx, (filename, _) in enumerate(sorted_files, 1):
                logger.debug("Validating file %d/%d: %s", file_idx, len(sorted_files), filename)
                filepath = os.path.join(volume_dir, filename)
                
                # Parse the XML file once with lxml (used by all validation functions)
                logger.debug("  Parsing XML file: %s", filename)
                try:
                    parser = etree.XMLParser(remove_blank_text=False)
                    xml_doc = etree.parse(filepath, parser)
                    root = xml_doc.getroot()
                    logger.debug("  Successfully parsed XML file: %s", filename)
                except etree.XMLSyntaxError as e:
                    logger.error("  XML syntax error in %s: %s", filename, str(e))
                    errors.append(f"File {filename} in volume {volume} is not a valid XML: {str(e)}")
                    continue
                except Exception as e:
                    logger.error("  Error reading file %s: %s", filename, str(e))
                    errors.append(f"Error reading file {filename} in volume {volume}: {str(e)}")
                    continue
                
                # Validate against TEI schema
                logger.debug("  Validating against TEI schema: %s", filename)
                try:
                    with resources.path('bdrc_etext_sync.schemas', 'tei_lite.rng') as schema_path:
                        if schema_path is None:
                            logger.error("  Cannot find TEI schema file for %s", filename)
                            errors.append(f"Cannot find TEI schema file (tei_lite.rng) in bdrc_etext_sync.schemas package for {filename} in volume {volume}")
                            continue
                        # Use the already-parsed xml_doc
                        tei_schema = etree.RelaxNG(file=schema_path)
                        is_valid = tei_schema.validate(xml_doc)
                        if not is_valid:
                            logger.warning("  TEI schema validation failed for %s", filename)
                            errors.append(f"File {filename} in volume {volume} is not a valid TEI XML: {tei_schema.error_log}")
                        else:
                            logger.debug("  TEI schema validation passed for %s", filename)
                except Exception as e:
                    logger.error("  Error validating TEI schema for %s: %s", filename, str(e))
                    errors.append(f"Error validating TEI for {filename} in volume {volume}: {str(e)}")
                    continue
                
                # Validate text normalization (reading file as text)
                logger.debug("  Validating text normalization: %s", filename)
                try:
                    norm_errors, norm_warnings = validate_tei_root_normalization(filepath)
                    if norm_errors:
                        logger.debug("  Found %d normalization error(s) in %s", len(norm_errors), filename)
                    if norm_warnings:
                        logger.debug("  Found %d normalization warning(s) in %s", len(norm_warnings), filename)
                    errors.extend(norm_errors)
                    warns.extend(norm_warnings)
                except Exception as e:
                    logger.error("  Error validating normalization for %s: %s", filename, str(e))
                    errors.append(f"Error validating normalization for {filename} in volume {volume}: {str(e)}")
                
                # Validate TEI subset (tags and attributes) (using parsed root)
                logger.debug("  Validating TEI subset: %s", filename)
                try:
                    subset_errors, subset_warnings = validate_tei_root_subset(root, filepath)
                    if subset_errors:
                        logger.debug("  Found %d TEI subset error(s) in %s", len(subset_errors), filename)
                    if subset_warnings:
                        logger.debug("  Found %d TEI subset warning(s) in %s", len(subset_warnings), filename)
                    errors.extend(subset_errors)
                    warns.extend(subset_warnings)
                except Exception as e:
                    logger.error("  Error validating TEI subset for %s: %s", filename, str(e))
                    errors.append(f"Error validating TEI subset for {filename} in volume {volume}: {str(e)}")

                # Check source references if sources directory exists (using already-parsed xml_doc)
                if sources_exist:
                    logger.debug("  Checking source references: %s", filename)
                    try:
                        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
                        
                        # Find SRC_PATH elements
                        src_elems = xml_doc.xpath("//tei:idno[@type='src_path']", namespaces=ns)
                        logger.debug("  Found %d source reference(s) in %s", len(src_elems), filename)
                        for src_elem in src_elems:
                            src_path = src_elem.text.strip()
                            full_src_path = os.path.join(sources_dir, src_path)
                            logger.debug("  Checking source file: %s", src_path)
                            
                            # Check if source file exists
                            if not os.path.isfile(full_src_path):
                                logger.warning("  Source file %s referenced in %s not found", src_path, filename)
                                errors.append(f"Source file {src_path} referenced in {filename} not found in sources directory")
                                continue
                            
                            # Get sha256 elements that are siblings to SRC_PATH
                            xpath = f"//tei:idno[@type='src_path'][text()=$val]/following-sibling::tei:idno[@type='src_sha256']/text()"
                            sha256_values = xml_doc.xpath(xpath, namespaces=ns, val=src_path)
                            
                            if not sha256_values:
                                logger.warning("  No sha256 checksum found for source %s in %s", src_path, filename)
                                warns.append(f"No sha256 checksum found for source {src_path} in {filename}")
                                continue
                            
                            # Calculate actual checksum
                            logger.debug("  Calculating SHA256 checksum for %s", src_path)
                            with open(full_src_path, 'rb') as f:
                                file_data = f.read()
                                actual_checksum = hashlib.sha256(file_data).hexdigest()
                            
                            # Verify checksum
                            if sha256_values[0] != actual_checksum:
                                logger.warning("  SHA256 checksum mismatch for %s in %s", src_path, filename)
                                errors.append(f"SHA256 checksum mismatch for {src_path} in {filename}. "
                                             f"Expected: {sha256_values[0]}, Got: {actual_checksum}")
                            else:
                                logger.debug("  SHA256 checksum verified for %s", src_path)
                    except Exception as e:
                        logger.error("  Error checking source references in %s: %s", filename, str(e))
                        errors.append(f"Error checking source references in {filename}: {str(e)}")
                else:
                    logger.debug("  Skipping source reference check (sources directory not found)")
                
                logger.debug("  Completed validation for %s", filename)
        
        else:
            logger.debug("Skipping volume %s (not in volume names list)", volume)
    
    # Check if we found at least one valid volume
    if not found_valid_volume:
        logger.error("No valid volumes found in archive directory")
        errors.append("No valid volumes found in archive directory")
    
    # Function passes if there are no errors
    passed = len(errors) == 0
    logger.info("Validation complete: %s (%d error(s), %d warning(s))", 
                "PASSED" if passed else "FAILED", len(errors), len(warns))
    return passed, warns, errors
