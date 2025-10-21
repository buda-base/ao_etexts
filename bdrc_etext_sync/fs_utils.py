"""Filesystem utilities for transparent handling of local and S3 paths using PyFilesystem2."""
import fs
from fs.base import FS
from fs.osfs import OSFS
from fs_s3fs import S3FS
import fs.opener
import os

def to_dirname(id_s):
    if id_s.startswith("http://purl.bdrc.io/resource/IE"):
        return id_s[29:]
    elif id_s.startswith("bdr:IE"):
        return id_s[4:]
    elif id_s.startswith("IE"):
        return id_s
    raise Exception("unable to parse id "+id_s)

def _id_subdir_path(base_dir, id_s, use_fs=False):
    """
    Resolve the directory that actually contains the files for the given id,
    assuming files live in a subdirectory named exactly like the id.
    If use_fs is True, join using fs.path (for PyFilesystem paths like s3://...).
    """
    sub = to_dirname(id_s)
    if use_fs:
        return fs.path.join(base_dir, sub)
    return os.path.join(base_dir, sub)

def open_filesystem(path_or_url, create=False, writeable=True):
    """
    Open a filesystem from either a local path or an S3 URL.
    
    Args:
        path_or_url (str): Either a local filesystem path or an S3 URL
                          Examples:
                          - "/path/to/dir" (local)
                          - "s3://bucket-name/prefix/" (S3)
        create (bool): If True, create the filesystem if it doesn't exist
        writeable (bool): If True, the filesystem must be writeable
    
    Returns:
        FS: A PyFilesystem2 filesystem object
    """
    if isinstance(path_or_url, FS):
        # Already a filesystem object, return as-is
        return path_or_url
    
    # Check if this is an S3 URL
    if path_or_url.startswith("s3://"):
        # Parse S3 URL
        parse_result = fs.opener.parse(path_or_url)
        bucket_name, _, dir_path = parse_result.resource.partition("/")
        if not bucket_name:
            raise ValueError(f"Invalid S3 bucket name in '{path_or_url}'")
        
        # Use strict=False to avoid needing directory marker objects
        strict = (
            parse_result.params.get("strict") == "1"
            if "strict" in parse_result.params
            else False
        )
        
        s3fs = S3FS(
            bucket_name,
            dir_path=dir_path or "/",
            aws_access_key_id=parse_result.username or None,
            aws_secret_access_key=parse_result.password or None,
            endpoint_url=parse_result.params.get("endpoint_url", None),
            acl=parse_result.params.get("acl", None),
            cache_control=parse_result.params.get("cache_control", None),
            strict=strict
        )
        # Patch getinfo to avoid directory checks
        s3fs.getinfo = s3fs._getinfo
        return s3fs
    
    # Otherwise treat as a local path
    return OSFS(path_or_url, create=create)


def walk_files(filesystem, path="/"):
    """
    Walk through all files in a filesystem directory.
    
    Args:
        filesystem (FS): PyFilesystem2 filesystem object
        path (str): Starting path within the filesystem
        
    Yields:
        tuple: (dirpath, filename, file_info) for each file
    """
    for dirpath, dirnames, filenames in filesystem.walk(path):
        for file_info in filenames:
            # file_info is an Info object, get the name
            filename = file_info.name
            file_path = fs.path.join(dirpath, filename)
            yield dirpath, filename, file_info


def copy_file(src_fs, src_path, dst_fs, dst_path):
    """
    Copy a file from one filesystem to another.
    
    Args:
        src_fs (FS): Source filesystem
        src_path (str): Source file path
        dst_fs (FS): Destination filesystem
        dst_path (str): Destination file path
    """
    with src_fs.open(src_path, 'rb') as src_file:
        with dst_fs.open(dst_path, 'wb') as dst_file:
            dst_file.write(src_file.read())


def get_path_type(path_or_url):
    """
    Determine the type of path/URL.
    
    Args:
        path_or_url (str): Path or URL to check
        
    Returns:
        str: "s3" for S3 URLs, "local" for local paths
    """
    if path_or_url.startswith("s3://"):
        return "s3"
    return "local"


def ensure_dir(filesystem, path):
    """
    Ensure a directory exists in the filesystem.
    
    Args:
        filesystem (FS): PyFilesystem2 filesystem object
        path (str): Directory path to ensure exists
    """
    if not filesystem.exists(path):
        filesystem.makedirs(path, recreate=True)
