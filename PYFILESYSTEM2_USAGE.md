# PyFilesystem2 Integration

The codebase now uses [PyFilesystem2](https://docs.pyfilesystem.org/) to support transparent handling of both local filesystem paths and S3 URLs.

## Usage

All file path parameters can now accept either:

1. **Local filesystem paths**: `/path/to/directory` or `./relative/path`
2. **S3 URLs**: `s3://bucket-name/prefix/path/`

## Examples

### Sync to S3

```bash
# Sync from local directory to S3
bdrc-etext-sync sync_s3 --id IE12345 --filesdir s3://my-bucket/data/

# Sync from S3 to local
bdrc-etext-sync sync_s3 --id IE12345 --filesdir /local/path/

# Sync from S3 to S3
bdrc-etext-sync sync_s3 --id IE12345 --filesdir s3://source-bucket/path/
```

### Sync to ElasticSearch

```bash
# Index from local directory
bdrc-etext-sync sync_es --id IE12345 --filesdir /local/path/ --version v1

# Index from S3
bdrc-etext-sync sync_es --id IE12345 --filesdir s3://my-bucket/data/ --version v1
```

### Validate Files

```bash
# Validate local files
bdrc-etext-sync validate_files --id IE12345 --filesdir /local/path/

# Validate S3 files
bdrc-etext-sync validate_files --id IE12345 --filesdir s3://my-bucket/data/
```

## S3 Configuration

For S3 access, the following AWS credentials are used automatically:

- Environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- AWS credentials file: `~/.aws/credentials`
- IAM role (when running on AWS infrastructure)

You can also pass credentials in the S3 URL:
```
s3://access_key:secret_key@bucket-name/prefix/
```

## Implementation Details

### Key Components

1. **fs_utils.py**: Core utilities for filesystem operations
   - `open_filesystem(path_or_url)`: Opens either local or S3 filesystem
   - `walk_files(filesystem, path)`: Iterates over files
   - `get_path_type(path_or_url)`: Detects path type ("local" or "s3")

2. **s3_utils.py**: Updated to use PyFilesystem2
   - `sync_directories(src, dst)`: Syncs between any filesystem types
   - Supports local-to-local, local-to-S3, S3-to-local, and S3-to-S3

3. **es_utils.py**: Updated to read from any filesystem type
   - `get_docs()`: Reads XML files from local or S3 paths

4. **bdrc_etext_sync.py**: Updated to support filesystem URLs
   - `notify_sync()`: Processes files from any filesystem type

### S3 Specific Notes

- The implementation uses `strict=False` mode for S3, which avoids the need for directory marker objects
- File checksums (SHA256) are used for efficient synchronization
- Incremental sync is supported (only changed files are uploaded)
- Files removed from source are automatically deleted from destination

## Dependencies

The following packages are required:

```
fs              # PyFilesystem2 core
fs-s3fs         # S3 filesystem support
```

These are automatically installed via `requirements.txt`.

## Benefits

1. **Unified API**: Same code works for local and S3 paths
2. **Flexibility**: Easy to switch between local development and cloud deployment
3. **No Code Changes**: Existing scripts work with new path types
4. **Tested**: The ocfl-py library also uses PyFilesystem2, ensuring compatibility
