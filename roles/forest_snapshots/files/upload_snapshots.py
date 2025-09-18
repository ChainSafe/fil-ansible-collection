import hashlib
import json
import os
import subprocess
import threading
import time

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue
from roles.forest_snapshots.files.forest_helpers import get_api_info

logger = setup_logger(os.path.basename(__file__))

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
ARCHIVE_BUCKET_NAME = os.getenv("R2_ARCHIVE_BUCKET_NAME", "my-bucket")
LATEST_BUCKET_NAME = os.getenv("R2_LATEST_BUCKET_NAME", "my-bucket")
LATEST_V2_BUCKET_NAME = os.getenv("R2_LATEST_V2_BUCKET_NAME", "my-bucket")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
QUEUE_WAIT_TIMEOUT = 10 * 60  # 10 minutes
TIMEOUT_SECONDS = 40 * 60  # 40 minutes

# S3 config
S3_READ_TIMEOUT = 300
S3_CONNECT_TIMEOUT = 60

# Initialize metrics
metrics = None

# Initialize S3
s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    config=boto3.session.Config(
        connect_timeout=S3_CONNECT_TIMEOUT,
        read_timeout=S3_READ_TIMEOUT,
        retries={"max_attempts": 10, "mode": "adaptive"},
        max_pool_connections=50,
        signature_version="s3v4"
    )
)
KB = 1024
MB = KB * KB


def gather_archive_metadata(archive_metadata: list[str], archive_info: list[str]):
    data = {}
    current_key = None
    for metadata in [archive_metadata, archive_info]:
        for line in metadata:
            if not line.strip():
                continue  # skip empty lines

            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if value:
                    data[key] = value
                    current_key = key
                else:
                    # Key with multiline value
                    data[key] = []
                    current_key = key
            else:
                # Continuation line (multiline value)
                if current_key:
                    if isinstance(data[current_key], list):
                        data[current_key].append(line.strip())
                    else:
                        # Convert to list if already has a single value
                        data[current_key] = [data[current_key], line.strip()]
    return data


def upload_sha256(snapshot_path: str) -> str:
    """Upload sha256 to R2."""
    with open(snapshot_path, "rb") as f:
        snapshot_hash = hashlib.sha256(f.read()).hexdigest()
    snapshot_sha256 = f"{snapshot_path}.sha256sum"
    with open(snapshot_sha256, "w") as f:
        f.write(snapshot_hash)
    r2_upload_artifact(snapshot_sha256)
    return snapshot_hash


def upload_metadata(snapshot_path: str, snapshot_hash: str):
    """Upload metadata to R2."""
    try:
        archive_metadata = subprocess.run(
            ["/usr/local/bin/forest-tool", "archive", "metadata", snapshot_path],
            env={
                "FULLNODE_API_INFO": get_api_info()
            },
            capture_output=True, text=True, check=True
        )
        archive_info = subprocess.run(
            ["/usr/local/bin/forest-tool", "archive", "info", snapshot_path],
            env={
                "FULLNODE_API_INFO": get_api_info()
            },
            capture_output=True, text=True, check=True
        )
        target_snapshot_metadata = gather_archive_metadata(
            archive_metadata.stdout.splitlines(),
            archive_info.stdout.splitlines()
        )
        target_snapshot_metadata["sha256sum"] = snapshot_hash
        target_snapshot_metadata["forest_validation"] = {
            "success": False,
        }
        target_snapshot_metadata["lotus_validation"] = {
            "success": False,
        }
        snapshot_metadata = f"{snapshot_path}.metadata.json"
        with open(snapshot_metadata, "w") as f:
            f.write(json.dumps(target_snapshot_metadata, indent=2))
        return r2_upload_artifact(snapshot_metadata)

    except subprocess.CalledProcessError as err:
        logger.error(f"Error fetching genesis timestamp: {err.stderr}", exc_info=True)
        raise


def r2_upload_artifact(file_path: str) -> bool:
    """Upload the snapshot file and checksum to S3."""
    try:
        basename = os.path.basename(file_path)
        destination = os.path.basename(os.path.dirname(file_path))
        key_prefix = f"{CHAIN}/{destination}/"
        if destination == "latest-v2":
            bucket_name = LATEST_V2_BUCKET_NAME
        elif destination == "latest":
            bucket_name = LATEST_BUCKET_NAME
        else:
            bucket_name = ARCHIVE_BUCKET_NAME
        try:
            s3.head_object(Bucket=bucket_name, Key=key_prefix + basename)
            logger.warning(f"Snapshot {file_path} already exists in s3://{bucket_name}/{key_prefix}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == "404":
                s3.upload_file(
                    file_path,
                    bucket_name,
                    key_prefix + basename,
                    Config=TransferConfig(
                        multipart_threshold=64 * MB,  # 64MB before multipart
                        multipart_chunksize=64 * MB,  # 64MB chunks
                        max_concurrency=10,  # parallel uploads
                        use_threads=True
                    )
                )
                logger.info(f"✅ File {file_path} uploaded to s3://{bucket_name}/{key_prefix}")
                return True
            else:
                # Other errors (permission, etc.)
                raise
    except Exception as e:
        logger.error(f"❌ Snapshot {file_path} upload failed: {e}")
        return False


def upload_snapshot(snapshot_path: str) -> bool:
    """Wrapper around upload that also produces RabbitMQ status messages."""
    with metrics.track_upload():
        snapshot_hash = upload_sha256(snapshot_path)
        upload_metadata(snapshot_path, snapshot_hash)
        return r2_upload_artifact(snapshot_path)


def process_snapshot(delivery_tag: int, snapshot_path: str, rabbit: RabbitMQClient = None):
    """Process snapshot with timeout logic."""
    logger.info(f"Start processing snapshot: {snapshot_path}")
    result = {"success": False}

    def worker():
        result["success"] = upload_snapshot(snapshot_path)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(TIMEOUT_SECONDS)

    if thread.is_alive():
        logger.warning(f"⏱ Timeout: {snapshot_path} exceeded {TIMEOUT_SECONDS // 60} minutes")
        metrics.inc_failure()
        rabbit.reject(delivery_tag, requeue=True)
    else:
        if result["success"]:
            metrics.inc_success()
            rabbit.ack(delivery_tag)
            rabbit.produce(RabbitQueue.UPLOAD, snapshot_path)
        else:
            metrics.inc_failure()
            rabbit.reject(delivery_tag, requeue=False)
            rabbit.produce(RabbitQueue.UPLOAD_FAILED, snapshot_path)


def main():
    # Initialize queue
    rabbit_setup = RabbitMQClient()
    rabbit_setup.setup([
        RabbitQueue.SNAPSHOT,
        RabbitQueue.SNAPSHOT_LATEST,
        RabbitQueue.SNAPSHOT_DIFF,
        RabbitQueue.UPLOAD,
        RabbitQueue.UPLOAD_FAILED
    ])
    rabbit_setup.close()
    while True:
        for queue in [RabbitQueue.SNAPSHOT, RabbitQueue.SNAPSHOT_DIFF, RabbitQueue.SNAPSHOT_LATEST]:
            with RabbitMQClient() as rabbit:
                delivery_tag, snapshot_path = rabbit.consume(queue)
                if delivery_tag:
                    metrics.set_total(rabbit.get_queue_size(queue))
                    try:
                        process_snapshot(delivery_tag, snapshot_path, rabbit)
                        break
                    except Exception as e:
                        logger.error(f"Could not process snapshot: {snapshot_path} ({e})")
        else:
            logger.info(f"⚠️ No snapshots in queue. Sleeping for {QUEUE_WAIT_TIMEOUT // 60} minutes...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
            continue
    rabbit.close()


if __name__ == "__main__":
    metrics = Metrics(port=METRICS_PORT)
    main()
