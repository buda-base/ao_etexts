#!/bin/bash
#
# sync_etexts_archive.sh
#
# OCFL-aware copy of local etext archive to S3 backup using rclone.
# Reads configuration from ~/.config/ao_etexts/sync_config
# Supports:
#   --filelist /path/to/relative_paths.txt
#   --dry-run   (simulate only, no changes made)
#
# example S3_PATH=":s3,provider=AWS,env_auth=true,region=XXX:BUCKET_NAME/PREFIX"

set -euo pipefail

# -------- Config loading --------
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CONF_DIR="${XDG_CONFIG_HOME}/ao_etexts"
CONF_FILE="${CONF_DIR}/sync_config"

if [[ ! -f "$CONF_FILE" ]]; then
  echo "Config file not found: $CONF_FILE" >&2
  echo "Create it with the required variables: LOCAL_PATH, S3_PATH, PROFILE, LOG_DIR" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONF_FILE"

: "${LOCAL_PATH:?LOCAL_PATH not set in $CONF_FILE}"
: "${S3_PATH:?S3_PATH not set in $CONF_FILE}"
: "${PROFILE:?PROFILE not set in $CONF_FILE}"
: "${LOG_DIR:?LOG_DIR not set in $CONF_FILE}"

# -------- Args --------
FILELIST=""
DRYRUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --filelist)
      FILELIST="$2"
      shift 2
      ;;
    --dry-run)
      DRYRUN=true
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

# -------- Pre-flight --------
command -v rclone >/dev/null 2>&1 || { echo "rclone not found in PATH"; exit 3; }
mkdir -p "$LOG_DIR"

DATE_TAG="$(date +%F)"
LOG_FILE="$LOG_DIR/sync_etexts_archive_${DATE_TAG}.log"
TRANSFERS="${TRANSFERS:-8}"
CHECKERS="${CHECKERS:-16}"

echo "[$(date)] Start OCFL copy -> $S3_PATH (profile: $PROFILE)" | tee -a "$LOG_FILE"

BASE_FLAGS=(
  --fast-list
  --transfers="$TRANSFERS" --checkers="$CHECKERS"
  --s3-upload-concurrency="${S3_UPLOAD_CONCURRENCY:-8}"
  --s3-chunk-size="${S3_CHUNK_SIZE:-64M}"
  --s3-upload-cutoff="${S3_UPLOAD_CUTOFF:-200M}"
  --s3-no-check-bucket
  --log-file="$LOG_FILE"
  --log-level="${LOG_LEVEL:-INFO}"
)

if $DRYRUN; then
  BASE_FLAGS+=(--dry-run)
  echo "[$(date)] Running in DRY-RUN mode (no changes will be made)" | tee -a "$LOG_FILE"
fi

# -------- Pass 1: all content except inventory.json*, skip existing --------
if [[ -n "${FILELIST}" ]]; then
  [[ -f "$FILELIST" ]] || { echo "File list not found: $FILELIST" | tee -a "$LOG_FILE" >&2; exit 4; }
  echo "[$(date)] Using files-from list: $FILELIST" | tee -a "$LOG_FILE"

  AWS_PROFILE="$PROFILE" rclone copy "$LOCAL_PATH" "$S3_PATH" \
    "${BASE_FLAGS[@]}" \
    --files-from-raw "$FILELIST" \
    --exclude '**/inventory.json*' \
    --ignore-existing

  AWS_PROFILE="$PROFILE" rclone copy "$LOCAL_PATH" "$S3_PATH" \
    "${BASE_FLAGS[@]}" \
    --files-from-raw "$FILELIST" \
    --include '**/inventory.json*' \
    --size-only
else
  AWS_PROFILE="$PROFILE" rclone copy "$LOCAL_PATH" "$S3_PATH" \
    "${BASE_FLAGS[@]}" \
    --exclude '**/inventory.json*' \
    --ignore-existing

  AWS_PROFILE="$PROFILE" rclone copy "$LOCAL_PATH" "$S3_PATH" \
    "${BASE_FLAGS[@]}" \
    --include '**/inventory.json*' \
    --size-only
fi

echo "[$(date)] Completed successfully." | tee -a "$LOG_FILE"
