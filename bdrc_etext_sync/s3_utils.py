import hashlib
import logging
import hashlib
import base64
import fs
from .fs_utils import open_filesystem, walk_files

S3_BUCKET_NAME = "etexts.bdrc.io"

def to_s3_prefix(ie_lname):
    encoded_string = ie_lname.encode('utf-8')
    md5_hash = hashlib.md5(encoded_string)
    md5_hex = md5_hash.hexdigest()
    return md5_hex[:2]+"/"+ie_lname+"/"

def sync_id_to_s3(ie_lname, local_dir_path):
    """
    Synchronize files from a local or S3 path to S3.
    
    Args:
        ie_lname (str): Instance etext name
        local_dir_path (str): Source directory path (can be local path or S3 URL)
    
    Returns:
        bool: True if successful, False otherwise
    """
    prefix = to_s3_prefix(ie_lname)
    s3_url = f"s3://{S3_BUCKET_NAME}/{prefix}"
    return sync_directories(local_dir_path, s3_url)

def sync_directories(src_path, dst_path):
    """
    Synchronize files from source to destination using PyFilesystem2.
    Both source and destination can be local paths or S3 URLs.
    
    This function:
    1. Uploads/copies all files from source to destination
    2. Includes SHA256 checksum verification
    3. Removes any files in destination that don't exist in source
    
    Args:
        src_path (str): Source path or URL (local path or s3://bucket/prefix)
        dst_path (str): Destination path or URL (local path or s3://bucket/prefix)
    
    Returns:
        bool: True if synchronization was successful, False otherwise
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    try:
        # Open source and destination filesystems
        src_fs = open_filesystem(src_path)
        dst_fs = open_filesystem(dst_path, create=True, writeable=True)
        
        # Get list of all files in destination
        existing_dst_files = set()
        try:
            for dirpath, filename, _ in walk_files(dst_fs, "/"):
                rel_path = fs.path.join(dirpath, filename).lstrip("/")
                existing_dst_files.add(rel_path)
        except Exception as e:
            logger.debug(f"Could not list destination files (may be empty): {e}")
        
        # Track which destination files have been processed
        processed_dst_files = set()
        
        # Walk through source directory
        for dirpath, filename, file_info in walk_files(src_fs, "/"):
            src_file_path = fs.path.join(dirpath, filename)
            
            # Get relative path
            rel_path = src_file_path.lstrip("/")
            
            # Ensure destination directory exists
            dst_dir = fs.path.dirname(rel_path)
            if dst_dir and not dst_fs.exists(dst_dir):
                dst_fs.makedirs(dst_dir, recreate=True)
            
            # Calculate SHA256 checksum of source file
            sha256_hash = hashlib.sha256()
            with src_fs.open(src_file_path, 'rb') as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            checksum = base64.b64encode(sha256_hash.digest()).decode('utf-8')
            
            # Check if destination file exists and has same checksum
            should_copy = True
            if dst_fs.exists(rel_path):
                # Calculate checksum of existing destination file
                dst_sha256 = hashlib.sha256()
                with dst_fs.open(rel_path, 'rb') as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        dst_sha256.update(byte_block)
                dst_checksum = base64.b64encode(dst_sha256.digest()).decode('utf-8')
                
                if checksum == dst_checksum:
                    logger.debug(f"Skipping {rel_path} (unchanged)")
                    should_copy = False
            
            if should_copy:
                # Copy the file
                logger.info(f"Copying {src_file_path} to {rel_path}")
                try:
                    with src_fs.open(src_file_path, 'rb') as src_file:
                        with dst_fs.open(rel_path, 'wb') as dst_file:
                            dst_file.write(src_file.read())
                except Exception as e:
                    logger.error(f"Error copying {src_file_path}: {e}")
                    return False
            
            # Mark this file as processed
            processed_dst_files.add(rel_path)
        
        # Delete files in destination that don't exist in source
        files_to_delete = existing_dst_files - processed_dst_files
        if files_to_delete:
            logger.info(f"Deleting {len(files_to_delete)} files from destination that don't exist in source")
            for file_path in files_to_delete:
                try:
                    logger.info(f"Deleting {file_path}")
                    dst_fs.remove(file_path)
                except Exception as e:
                    logger.error(f"Error deleting {file_path}: {e}")
        
        logger.info("Synchronization completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"An error occurred during synchronization: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Close filesystems if they were opened
        try:
            if 'src_fs' in locals():
                src_fs.close()
            if 'dst_fs' in locals():
                dst_fs.close()
        except:
            pass
