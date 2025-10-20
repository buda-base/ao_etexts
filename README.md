# ao_etexts
AO etext scripts

## Features

- Transparent support for both local filesystem paths and S3 URLs
- Validate etext file structure
- Synchronize etext files to OCFL archive (admin only)
- Synchronize etext files to staging area (dev)
- Index etext content to ElasticSearch/OpenSearch (admin only)

## Installation

```bash
pip install -r requirements.txt
pip install -e .
```

### Examples

```bash
# Sync from local directory
bdrc-etext-sync sync_s3 --id IE12345 --filesdir /path/to/files/

# Sync from S3
bdrc-etext-sync sync_s3 --id IE12345 --filesdir s3://bucket-name/prefix/

# Index to ElasticSearch from local or S3
bdrc-etext-sync sync_es --id IE12345 --filesdir /path/or/s3/url/ --version v1
```
