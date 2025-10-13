# ao_etexts
AO etext scripts

## Features

- **PyFilesystem2 Integration**: Transparent support for both local filesystem paths and S3 URLs
- Synchronize etext files to OCFL archive
- Synchronize etext files to S3
- Index etext content to ElasticSearch/OpenSearch
- Validate etext file structure

## Installation

```bash
pip install -r requirements.txt
pip install -e .
```

## Usage

The tool supports both local paths and S3 URLs transparently. See [PYFILESYSTEM2_USAGE.md](PYFILESYSTEM2_USAGE.md) for details.

### Examples

```bash
# Sync from local directory
bdrc-etext-sync sync_s3 --id IE12345 --filesdir /path/to/files/

# Sync from S3
bdrc-etext-sync sync_s3 --id IE12345 --filesdir s3://bucket-name/prefix/

# Index to ElasticSearch from local or S3
bdrc-etext-sync sync_es --id IE12345 --filesdir /path/or/s3/url/ --version v1
```

## TODO

- Add version to sync notification
- Additional documentation
