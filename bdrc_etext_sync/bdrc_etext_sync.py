#!/usr/bin/env python3 
import argparse
import sys
import logging
import ocfl
from .validation import validate_files_and_log, validate_files
from .s3_utils import sync_id_to_s3
from .buda_api import get_buda_AO_info
from .es_utils import sync_id_to_es
import re
import os

OCFL_ROOT = "/home/eroux/BUDA/softs/public-library-data-warehouse/acip/sungbum/archive/"
OCFL_VERSION = "1.1"
OCFL_DIGEST = "sha256"
OCFL_PATH_NORM = "uri"
COMMIT_USER = "BDRC sync agent"
COMMIT_MESSAGE = None

def validate_version(version):
    """Validates the version format. Must be 'head' or 'v' followed by digits."""
    if version == "head":
        return version
    
    if not re.match(r'^v\d+$', version):
        raise argparse.ArgumentTypeError("Version must be 'head' or 'v' followed by digits (e.g., v1, v2, v10)")
    
    return version

def validate_id(id_s):
    """Validates the version format. Must be 'head' or 'v' followed by digits."""
    if not re.match(r'^IE\d[A-Z0-9_]+$', id_s):
        raise argparse.ArgumentTypeError("id must be in the form IE then a digit, then upper case letters and digits")
    
    return id_s

def to_ocfl_id(id_s):
    if id_s.startswith("IE"):
        return "http://purl.bdrc.io/resource/"+id_s
    elif id_s.startswith("bdr:IE"):
        return "http://purl.bdrc.io/resource/"+id_s[4:]
    elif id_s.startswith("http://purl.bdrc.io/resource/IE"):
        return id_s
    raise "unable to parse id "+id_s

def sync_files_archive(args):
    """Synchronizes files for a specific ID with the given directory."""
    srcdir = args.filesdir
    if not os.path.isdir(srcdir):
        raise "not a directory: "+srcdir
    store = ocfl.StorageRoot(root=OCFL_ROOT)
    ocfl_id = to_ocfl_id(args.id)
    objdir = store.object_path(ocfl_id)
    obj = ocfl.Object(identifier=ocfl_id,
                  spec_version=OCFL_VERSION,
                  digest_algorithm=OCFL_DIGEST,
                  content_path_normalization=OCFL_PATH_NORM,
                  forward_delta=True,
                  dedupe=True,
                  lax_digests=True,
                  fixity=None)
    create = True
    if os.path.isfile(objdir):
        raise "error: "+objdir+" is a file, should be a directory"
    if os.path.isdir(objdir):
        # if the object directory exists, make sure it is a valid OCFL object
        logging.info("validating previous version of object in "+objdir)
        passed, validator = obj.validate(objdir=objdir,
                                     log_warnings=True,
                                     log_errors=True,
                                     check_digests=True)
        if not passed:
            raise "invalid OCFL object in "+objdir
        create = False
    metadata = ocfl.VersionMetadata(created=None,
                                    message=COMMIT_MESSAGE,
                                    name=COMMIT_USER,
                                    address=None)
    if create:
        obj.create(srcdir=srcdir,
                   metadata=metadata,
                   objdir=args.objdir)
    else:
        obj.add_version_with_content(objdir=args.objdir,
                                           srcdir=srcdir,
                                           metadata=metadata)
    logging.info(f"Synced files for ID: {args.id} from directory: {args.filesdir}")

def sync_files_s3(args):
    # hardcode configuration (not ideal) so the command can be run without access to the archive
    return sync_id_to_s3(args.id, args.filesdir)

def sync_to_es(args):
    # hardcode configuration (not ideal) so the command can be run without access to the archive
    ie_info = get_buda_AO_info(args.id)
    if not ie_info:
        logger.error(f"could not find {args.id} in the database")
        return
    return sync_id_to_es(ie_info["mw_lname"], ie_info["mw_root_lname"], args.id, args.filesdir, args.version, ie_info["volname_to_volnum"])

def get_batch_info(batch_dir, requires_version=False):
    # Ensure batch_dir exists and is a directory
    if not os.path.isdir(batch_dir):
        raise ValueError(f"'{batch_dir}' is not a valid directory")
    
    # Get all entries in the batch directory
    all_entries = os.listdir(batch_dir)
    all_entries.sort()

    res = []
    for entry in all_entries:
        if not os.path.isdir(os.path.join(batch_dir, entry)):
            logging.warning(f"ignore file {entry}")
            continue
        if not entry.startswith("IE"):
            logging.warning(f"ignore directory {entry}")
            continue
        if re.match(r'^(.+?)[-_]v(\d+)$', entry):
            eid = match.group(1)
            version = match.group(2)
        else:
            eid = entry
            version = None
            if requires_version:
                logging.warning(f"ignore directory {entry} (lacks OCFL version indication)")
                continue
        res.append({
            "path": os.path.join(batch_dir, entry),
            "eid": eid,
            "version": version
            })
    return res

    
    # Process each directory
    for subdir_basename in ie_dirs:
        subdir_path = os.path.join(batch_dir, subdir_basename)
        
        # Call the validate function (assuming it's defined elsewhere)
        validate(subdir_basename, subdir_path)
    
    return len(ie_dirs)  # Return number of processed directories

def validate_files_batch(args):
    batch_infos = get_batch_info(args.batch_dir, requires_version=False)
    nb_total = len(batch_infos)
    logging.info(f"validate {nb_total} directories")
    nb_passed = 0
    for bi in batch_infos:
        passed, warnings, errors = validate_files(bi["eid"], bi["path"])
        bi["passed"] = passed
        if passed:
            nb_passed += 1
        bi["warnings"] = warnings
        bi["errors"] = errors
        if errors:
            for e in errors:
                logging.error(e)
    if nb_passed == nb_total:
        logging.info(f"all {nb_passed} directories passed")
    else:
        logging.error(f"{nb_passed} / {nb_total} passed")

def get_archive_files(args):
    """Downloads archive files for a specific ID and optional version to the given directory."""
    dstdir = args.filesdir
    if os.path.isdir(dstdir):
        raise "directory already exists: "+dstdir
    store = ocfl.StorageRoot(root=OCFL_ROOT)
    ocfl_id = to_ocfl_id(args.id)
    objdir = store.object_path(ocfl_id)
    if not os.path.isdir(objdir):
        raise "object does not exist in "+objdir
    obj = ocfl.Object(identifier=ocfl_id,
                  spec_version=OCFL_VERSION,
                  digest_algorithm=OCFL_DIGEST,
                  content_path_normalization=OCFL_PATH_NORM,
                  forward_delta=True,
                  dedupe=True,
                  lax_digests=True,
                  fixity=None)
    metadata = obj.extract(objdir=objdir,
               version=args.version,
               dstdir=dstdir)
    extracted_version = metadata.version
    if args.version == "head":
        extracted_version += " (head)"
    logging.info(f"Extracted archive files for ID: {args.id}, version {extracted_version} to directory: {args.filesdir}")
     

def main():
    # Create the top-level parser
    parser = argparse.ArgumentParser(prog='bdrc_etext_sync', description='BDRC eText management tool')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    subparsers.required = True
    
    # Parser for the validate_files command
    validate_parser = subparsers.add_parser('validate_files', help='Validate files for a specific ID')
    validate_parser.add_argument('--id', type=validate_id, required=True, help='The ID to validate')
    validate_parser.add_argument('--filesdir', required=True, help='Directory containing the files')
    validate_parser.set_defaults(func=validate_files_and_log)

    # Parser for the validate_files command
    validate_parser = subparsers.add_parser('validate_files_batch', help='Validate files for a all folders in a directory')
    validate_parser.add_argument('--batch_dir', required=True, help='The folder of the ID to validate')
    validate_parser.set_defaults(func=validate_files_batch)

    # Parser for the sync command
    sync_parser = subparsers.add_parser('sync_archive', help='Synchronize files to archive for a specific ID')
    sync_parser.add_argument('--id', type=validate_id, required=True, help='The ID to synchronize')
    sync_parser.add_argument('--filesdir', required=True, help='Directory to synchronize from')
    sync_parser.set_defaults(func=sync_files_archive)

    # Parser for the sync command
    sync_s3_parser = subparsers.add_parser('sync_s3', help='Synchronize files to s3 for a specific ID')
    sync_s3_parser.add_argument('--id', type=validate_id, required=True, help='The ID to synchronize')
    sync_s3_parser.add_argument('--filesdir', required=True, help='Directory to synchronize from')
    sync_s3_parser.set_defaults(func=sync_files_s3)

    # Parser for the sync command
    sync_s3_parser = subparsers.add_parser('sync_es', help='Synchronize files to ElasticSearch for a specific ID and path')
    sync_s3_parser.add_argument('--id', type=validate_id, required=True, help='The ID to synchronize')
    sync_s3_parser.add_argument('--filesdir', required=True, help='Directory to synchronize from')
    sync_s3_parser.add_argument('--version', required=True, type=validate_version, help='OCFL version of the files')
    sync_s3_parser.set_defaults(func=sync_to_es)

    # Parser for the get_archive_files command
    archive_parser = subparsers.add_parser('get_archive_files', help='Get archive files for a specific ID')
    archive_parser.add_argument('--id', required=True, type=validate_id, help='The ID to get archive files for')
    archive_parser.add_argument('--version', type=validate_version, default="head", 
                              help="Version of the archive files (format: 'v' followed by digits, or 'head'). Default is 'head'")
    archive_parser.add_argument('--filesdir', required=True, help='Directory to save archive files to')
    archive_parser.set_defaults(func=get_archive_files)
    
    # Parse arguments and call the appropriate function
    args = parser.parse_args()
    args.func(args)

if __name__ == '__main__':
    main()
