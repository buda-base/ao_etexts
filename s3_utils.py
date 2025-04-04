import os
import hashlib
import boto3
from botocore.exceptions import ClientError
import logging
import hashlib

S3_BUCKET_NAME = "etexts.bdrc.io"

def to_s3_prefix(ie_lname):
    encoded_string = ie_lname.encode('utf-8')
    md5_hash = hashlib.md5(encoded_string)
    md5_hex = md5_hash.hexdigest()
    return md5_hex[:2]+"/"+ie_lname+"/"

def sync_id_to_s3(ie_lname, local_dir_path):
    prefix = to_s3_prefix(ie_lname)
    return sync_directory_to_s3(local_dir_path, S3_BUCKET_NAME, prefix)

def sync_directory_to_s3(local_dir_path, bucket_name, prefix):
    """
    Synchronize local directory to an S3 prefix.
    
    This function:
    1. Uploads all files from the local directory to S3
    2. Includes SHA256 checksum with each upload
    3. Removes any files in the S3 prefix that don't exist in the local directory
    
    Args:
        local_dir_path (str): Path to the local directory
        bucket_name (str): the bucket name
        prefix (str): the s3 prefix
    
    Returns:
        bool: True if synchronization was successful, False otherwise
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Ensure prefix ends with a slash
    if prefix and not prefix.endswith('/'):
        prefix = prefix + '/'
    
    # Initialize S3 client
    s3_client = boto3.client('s3')
    
    try:
        # Check if local directory exists
        if not os.path.isdir(local_dir_path):
            logger.error(f"Local directory does not exist: {local_dir_path}")
            return False
        
        # Get list of all files in S3 with the given prefix
        existing_s3_files = set()
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    # Store the key without the prefix for comparison
                    key = obj['Key']
                    if key != prefix:  # Skip the directory marker object if it exists
                        existing_s3_files.add(key)
        
        # Track which S3 files have been processed
        processed_s3_files = set()
        
        # Walk through the local directory
        for root, _, files in os.walk(local_dir_path):
            for file in files:
                local_file_path = os.path.join(root, file)
                
                # Calculate relative path from the base directory
                rel_path = os.path.relpath(local_file_path, local_dir_path)
                
                # Convert Windows backslashes to forward slashes if needed
                rel_path = rel_path.replace('\\', '/')
                
                # Calculate the S3 key for this file
                s3_key = prefix + rel_path
                
                # Calculate the SHA256 checksum
                sha256_hash = hashlib.sha256()
                with open(local_file_path, 'rb') as f:
                    for byte_block in iter(lambda: f.read(4096), b""):
                        sha256_hash.update(byte_block)
                checksum = sha256_hash.hexdigest()
                
                # Upload the file with the checksum
                logger.info(f"Uploading {local_file_path} to s3://{bucket_name}/{s3_key}")
                try:
                    with open(local_file_path, 'rb') as data:
                        s3_client.put_object(
                            Bucket=bucket_name,
                            Key=s3_key,
                            Body=data,
                            ChecksumSHA256=checksum
                        )
                    
                    # Mark this S3 key as processed
                    processed_s3_files.add(s3_key)
                    
                except ClientError as e:
                    logger.error(f"Error uploading {local_file_path}: {e}")
                    return False
        
        # Delete files in S3 that don't exist locally
        files_to_delete = existing_s3_files - processed_s3_files
        if files_to_delete:
            logger.info(f"Deleting {len(files_to_delete)} files from S3 that don't exist locally")
            
            # S3 delete_objects requires a specific format
            delete_list = [{'Key': key} for key in files_to_delete]
            
            # Delete in batches of 1000 (S3 limit)
            for i in range(0, len(delete_list), 1000):
                batch = delete_list[i:i+1000]
                try:
                    s3_client.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': batch}
                    )
                except ClientError as e:
                    logger.error(f"Error deleting objects: {e}")
        
        logger.info("Synchronization completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"An error occurred during synchronization: {e}")
        return False