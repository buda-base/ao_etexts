#!/usr/bin/env python3 
import argparse
import sys
import logging
import ocfl
from .validation import validate_files_and_log, validate_files
from .s3_utils import sync_id_to_s3
from .buda_api import get_buda_AO_info, send_sync_notification
from .es_utils import sync_id_to_es, convert_tei_root_to_text, remove_previous_etext_es
from .fs_utils import open_filesystem, _id_subdir_path
import re
from pathlib import Path
from natsort import natsorted
import os
from lxml import etree
import copy
import fs.path
import argcomplete
from argcomplete.completers import DirectoriesCompleter, FilesCompleter, ChoicesCompleter

OCFL_ROOT = None
if 'OCFL_ROOT' in os.environ:
    OCFL_ROOT = os.environ['OCFL_ROOT']
    if not OCFL_ROOT.endswith("/"):
        OCFL_ROOT += "/"
OCFL_VERSION = "1.1"
OCFL_DIGEST = "sha256"
OCFL_PATH_NORM = "uri"
COMMIT_USER = "BDRC etext sync agent"
COMMIT_MESSAGE = None

OCFL_INIT = False
def ensure_ocfl_init():
    global OCFL_INIT
    if OCFL_INIT:
        return
    from ocfl.layout_registry import add_layout
    from .ocfl_layout_bdrc_etexts import Layout_BDRC_etexts
    add_layout("bdrc_etexts", Layout_BDRC_etexts)
    if OCFL_ROOT is None:
        raise Exception("environment variable OCFL_ROOT not set, aborting")
    OCFL_INIT = True

def validate_version(version):
    """Validates the version format. Must be 'head' or 'v' followed by digits."""
    if version == "head":
        return version

    if not re.match(r'^v\d+$', version):
        raise argparse.ArgumentTypeError(f"Invalid version {version}, must be 'head' or 'v' followed by digits (e.g., v1, v2, v10)")

    return version

def validate_id(id_s):
    if not re.match(r'^IE\d[A-Z0-9_\-]+$', id_s):
        raise argparse.ArgumentTypeError(f"invalid id {id_s}, must be in the form 'IE' then a digit, then upper case letters and digits")

    return id_s

def to_ocfl_id(id_s):
    if id_s.startswith("IE"):
        return "http://purl.bdrc.io/resource/"+id_s
    elif id_s.startswith("bdr:IE"):
        return "http://purl.bdrc.io/resource/"+id_s[4:]
    elif id_s.startswith("http://purl.bdrc.io/resource/IE"):
        return id_s
    raise Exception("unable to parse id "+id_s)

def read_ids_from_file(path):
    """Read an id list file (one id per line). Ignores blank lines and whitespace."""
    ids = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            # ignore pure comments lines if present
            if s.startswith("#"):
                continue
            ids.append(validate_id(s))
    return ids

def for_each_id(args, callback):
    """Call callback(args) for each id specified via --id or --idlistpath.
    When iterating, we copy args and set .id accordingly.
    """
    if getattr(args, "idlistpath", None):
        ids = read_ids_from_file(args.idlistpath)
    else:
        ids = [args.id]
    last_result = None
    for eid in ids:
        a = copy.copy(args)
        a.id = eid
        last_result = callback(a)
    return last_result

def sync_files_archive(args):
    """
    Synchronizes files for a specific ID with the given directory.

    Returns the head version of the ocfl object in the archive after the operation.
    """
    ensure_ocfl_init()
    srcdir = _id_subdir_path(args.filesdir, args.id)
    if not os.path.isdir(srcdir):
        raise Exception("not a directory: "+srcdir)
    store = ocfl.StorageRoot(root=OCFL_ROOT)
    ocfl_id = to_ocfl_id(args.id)
    objdir = OCFL_ROOT + store.object_path(ocfl_id)
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
        raise Exception("error: "+objdir+" is a file, should be a directory")
    if os.path.isdir(objdir):
        # if the object directory exists, make sure it is a valid OCFL object
        logging.info("validating previous version of object in "+objdir)
        passed, validator = obj.validate(objdir=objdir,
                                     log_warnings=True,
                                     log_errors=True,
                                     check_digests=True)
        if not passed:
            raise Exception("invalid OCFL object in "+objdir)
        create = False
    metadata = ocfl.VersionMetadata(created=None,
                                    message=COMMIT_MESSAGE,
                                    name=COMMIT_USER,
                                    address=None)
    new_version = "v1"
    if create:
        obj.create(srcdir=srcdir,
                   metadata=metadata,
                   objdir=objdir)
    else:
        obj.open_obj_fs(objdir)
        inventory = obj.parse_inventory()
        new_inventory = obj.add_version_with_content(objdir=objdir,
                                   srcdir=srcdir,
                                   metadata=metadata,
                                   abort_if_no_difference=True)
        if new_inventory:
            new_version = new_inventory.head
        else:
            new_version = inventory.head
    logging.info(f"Synced files for {args.id} from directory: {args.filesdir}, ocfl version in archive: {new_version}")
    return new_version

def get_ut_info(filesystem, xml_file_path):
    """
    Get etext info from XML file.
    
    Args:
        filesystem: PyFilesystem2 filesystem object
        xml_file_path: Path to XML file within the filesystem
    
    Returns:
        tuple: (nb_pages, nb_characters, src_path)
    """
    # Parse the XML file
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, remove_pis=True)
    with filesystem.open(xml_file_path, 'rb') as f:
        tree = etree.parse(f, parser)
    root = tree.getroot()

    # Define the TEI namespace
    namespace = {'tei': 'http://www.tei-c.org/ns/1.0'}

    # Find all pb elements using the namespace
    nb_pages = len(root.findall('.//tei:pb', namespace))
    plain_txt, annotations, src_path = convert_tei_root_to_text(root)
    nb_characters = len(plain_txt)
    return nb_pages, nb_characters, src_path

def notify_sync(args):
    """Send sync notification for files in a directory (local or S3)."""
    notification_info = { "ocfl_version": args.version, "volumes": {} }
    
    # Open the filesystem
    id_dir = _id_subdir_path(args.filesdir, args.id, use_fs=True)
    base_fs = open_filesystem(id_dir)
    archive_path = "archive"
    
    if not base_fs.exists(archive_path):
        logging.error(f"Archive directory does not exist at {archive_path}")
        base_fs.close()
        return

    # Walk through all subdirectories
    for volume_name in base_fs.listdir(archive_path):
        vol_path = fs.path.join(archive_path, volume_name)
        if base_fs.isdir(vol_path) and volume_name.startswith('VE'):
            notification_info["volumes"][volume_name] = {}

            # Process XML files in this volume directory
            for filename in base_fs.listdir(vol_path):
                if filename.endswith('.xml'):
                    xml_file_path = fs.path.join(vol_path, filename)
                    ut_name = filename[:-4]  # filename without extension
                    etext_num = int(ut_name[-4:])
                    nb_pages, nb_characters, src_path = get_ut_info(base_fs, xml_file_path)
                    # Get the etext info for this XML file
                    notification_info["volumes"][volume_name][ut_name] = { 
                        "etext_num": etext_num, 
                        "nb_pages": nb_pages, 
                        "nb_characters": nb_characters, 
                        "src_path": src_path 
                    }
    
    base_fs.close()
    send_sync_notification(args.id, notification_info)

def sync_files_s3(args):
    # hardcode configuration (not ideal) so the command can be run without access to the archive
    return sync_id_to_s3(args.id, _id_subdir_path(args.filesdir, args.id))

def sync_to_es(args):
    # hardcode configuration (not ideal) so the command can be run without access to the archive
    ie_info = get_buda_AO_info(args.id)
    if not ie_info:
        logging.error(f"could not find {args.id} in the database")
        return
    return sync_id_to_es(ie_info["mw_root_lname"], args.id, _id_subdir_path(args.filesdir, args.id), args.version, ie_info["volname_to_volnum"], ie_info["mw_outline_lname"])

def delete_es(args):
    """Remove previous eText index in ElasticSearch for this/these id(s)."""
    logging.info(f"Deleting previous eText index for {args.id}")
    return remove_previous_etext_es(args.id)

def get_archive_files(args):
    """Downloads archive files for a specific ID and optional version to the given directory."""
    ensure_ocfl_init()
    dstdir = os.path.join(args.filesdir, to_ocfl_id(args.id))
    if os.path.exists(dstdir):
        raise Exception("directory already exists: "+dstdir)
    store = ocfl.StorageRoot(root=OCFL_ROOT)
    ocfl_id = to_ocfl_id(args.id)
    objdir = store.object_path(ocfl_id)
    if not os.path.isdir(objdir):
        raise Exception("object does not exist in "+objdir)
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

def _add_id_or_idlist_arg(p):
    """Utility: add mutually exclusive --id and --idlistpath to a subparser."""
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--id', type=validate_id, help='The ID to target')
    g.add_argument('--idlistpath', help='Path to a file with one ID per line (blank lines ignored)')
    return p

class VersionCompleter:
    """Suggest 'head' and some common 'vN' patterns.
    This is a heuristic; actual valid versions depend on the object in archive.
    """
    def __call__(self, **kwargs):
        # Suggest 'head' and v1..v50 by default
        base = ["head"]
        base.extend([f"v{i}" for i in range(1, 51)])
        return base

def _set_completer(parser, option_flag, completer):
    """Attach an argcomplete completer to the option if present."""
    for action in getattr(parser, "_actions", []):
        if option_flag in getattr(action, "option_strings", []):
            action.completer = completer
            break

def main():
    # Create the top-level parser
    parser = argparse.ArgumentParser(prog='bdrc_etext_sync', description='BDRC eText management tool')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    subparsers.required = True

    # Parser for the validate_files command
    validate_parser = subparsers.add_parser('validate_files', help='Validate files for a specific ID')
    _add_id_or_idlist_arg(validate_parser)
    validate_parser.add_argument('--filesdir', required=True, help='Directory containing the files')
    validate_parser.set_defaults(func=lambda a: for_each_id(a, validate_files_and_log))

    # Parser for the sync_archive command
    sync_parser = subparsers.add_parser('sync_archive', help='Synchronize files to archive for a specific ID')
    _add_id_or_idlist_arg(sync_parser)
    sync_parser.add_argument('--filesdir', required=True, help='Directory to synchronize from')
    sync_parser.set_defaults(func=lambda a: for_each_id(a, sync_files_archive))

    # Parser for the notify_sync command
    notify_parser = subparsers.add_parser('notify_sync', help='Send sync notification for files in a directory')
    _add_id_or_idlist_arg(notify_parser)
    notify_parser.add_argument('--filesdir', required=True, help='Directory of files')
    notify_parser.add_argument('--version', required=True, help='OCFL version')
    notify_parser.set_defaults(func=lambda a: for_each_id(a, notify_sync))

    # Parser for the sync_s3 command
    sync_s3_parser = subparsers.add_parser('sync_s3', help='Synchronize files to s3 for a specific ID')
    _add_id_or_idlist_arg(sync_s3_parser)
    sync_s3_parser.add_argument('--filesdir', required=True, help='Directory to synchronize from')
    sync_s3_parser.set_defaults(func=lambda a: for_each_id(a, sync_files_s3))

    # Parser for the sync_es command
    sync_es_parser = subparsers.add_parser('sync_es', help='Synchronize files to ElasticSearch for a specific ID and path')
    _add_id_or_idlist_arg(sync_es_parser)
    sync_es_parser.add_argument('--filesdir', required=True, help='Directory to synchronize from')
    sync_es_parser.add_argument('--version', required=True, type=validate_version, help='OCFL version of the files')
    sync_es_parser.set_defaults(func=lambda a: for_each_id(a, sync_to_es))

    delete_es_parser = subparsers.add_parser('delete_es', help='Delete previous eText index in ElasticSearch for ID(s)')
    _add_id_or_idlist_arg(delete_es_parser)
    delete_es_parser.set_defaults(func=lambda a: for_each_id(a, delete_es))

    # Parser for the get_archive_files command
    archive_parser = subparsers.add_parser('get_archive_files', help='Get archive files for a specific ID')
    _add_id_or_idlist_arg(archive_parser)
    archive_parser.add_argument('--version', type=validate_version, default="head", 
                              help="Version of the archive files (format: 'v' followed by digits, or 'head'). Default is 'head'")
    archive_parser.add_argument('--filesdir', required=True, help='Directory to save archive files to')
    archive_parser.set_defaults(func=lambda a: for_each_id(a, get_archive_files))

    # Path-like completions
    _set_completer(validate_parser, '--filesdir', DirectoriesCompleter())
    _set_completer(sync_parser, '--filesdir', DirectoriesCompleter())
    _set_completer(notify_parser, '--filesdir', DirectoriesCompleter())
    _set_completer(sync_s3_parser, '--filesdir', DirectoriesCompleter())
    _set_completer(sync_es_parser, '--filesdir', DirectoriesCompleter())
    _set_completer(archive_parser, '--filesdir', DirectoriesCompleter())
    _set_completer(validate_parser, '--idlistpath', FilesCompleter())
    _set_completer(sync_parser, '--idlistpath', FilesCompleter())
    _set_completer(notify_parser, '--idlistpath', FilesCompleter())
    _set_completer(sync_s3_parser, '--idlistpath', FilesCompleter())
    _set_completer(sync_es_parser, '--idlistpath', FilesCompleter())
    _set_completer(delete_es_parser, '--idlistpath', FilesCompleter())
    _set_completer(archive_parser, '--idlistpath', FilesCompleter())
    # Version suggestions
    vc = VersionCompleter()
    _set_completer(sync_es_parser, '--version', vc)
    _set_completer(notify_parser, '--version', vc)
    _set_completer(archive_parser, '--version', vc)

    # Activate argcomplete for this parser
    # Users should also enable shell integration; see usage notes.
    argcomplete.autocomplete(parser)

    # Parse arguments and call the appropriate function
    args = parser.parse_args()
    # If the subparser already wrapped func with for_each_id, just call it.
    args.func(args)

if __name__ == '__main__':
    main()
