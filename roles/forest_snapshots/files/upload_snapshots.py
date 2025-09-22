import hashlib
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
from slack import slack_notify
from snapshot import SnapshotMetadata

logger = setup_logger(os.path.basename(__file__))

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
ARCHIVE_BUCKET_NAME = os.getenv("R2_ARCHIVE_BUCKET_NAME", "my-bucket")
LATEST_BUCKET_NAME = os.getenv("R2_LATEST_BUCKET_NAME", "my-bucket")
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


def upload_sha256(metadata: SnapshotMetadata):
    """Upload sha256 to R2."""
    snapshot_path = metadata.build_information.build_path
    sha256 = hashlib.sha256()
    with open(snapshot_path, "rb") as f:
        for chunk in iter(lambda: f.read(10*1024*1024), b""):
            sha256.update(chunk)
    snapshot_hash = sha256.hexdigest()
    snapshot_sha256 = f"{snapshot_path}.sha256sum"
    with open(snapshot_sha256, "w") as f:
        f.write(snapshot_hash)
    r2_upload_artifact(snapshot_sha256)
    metadata.snapshot.sha256 = snapshot_hash


def upload_metadata(metadata: SnapshotMetadata):
    """Upload metadata to R2."""
    try:
        snapshot_metadata = f"{metadata.build_information.build_path}.metadata.json"
        with open(snapshot_metadata, "w") as f:
            f.write(metadata.to_json())
        return r2_upload_artifact(snapshot_metadata)

    except subprocess.CalledProcessError as err:
        logger.error(f"⛔Error fetching snapshot metadata: {err.stderr}", exc_info=True)
        raise


def r2_upload_artifact(file_path: str) -> bool:
    """Upload the snapshot file and checksum to S3."""
    try:
        basename = os.path.basename(file_path)
        destination = os.path.basename(os.path.dirname(file_path))
        key_prefix = f"{CHAIN}/{destination}/"
        if destination in ["latest-v1", "latest-v2"]:
            bucket_name = LATEST_BUCKET_NAME
        else:
            bucket_name = ARCHIVE_BUCKET_NAME
        # Check if the file exists in s3
        exists = True
        try:
            s3.head_object(Bucket=bucket_name, Key=key_prefix + basename)
            if key_prefix.endswith("zst"):
                logger.warning(
                    f"⚠️ Snapshot {file_path} already exists in s3://{bucket_name}/{key_prefix}. Skipping upload.")
        except ClientError as e:
            if e.response['Error']['Code'] == "404":
                exists = False
            else:
                raise

        if not (file_path.endswith(".zst") and exists):
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
    except Exception as e:
        logger.error(f"❌ File {file_path} upload failed: {e}")
        return False


def upload_snapshot(snapshot_path: str, metadata: SnapshotMetadata) -> bool:
    """Wrapper around upload that also produces RabbitMQ status messages."""
    with metrics.track_upload():
        upload_sha256(metadata)
        upload_metadata(metadata)
        return r2_upload_artifact(snapshot_path)


def process_snapshot(delivery_tag: int, snapshot_path: str, metadata: SnapshotMetadata, rabbit: RabbitMQClient = None):
    """Process snapshot with timeout logic."""
    logger.info(f"⏳Start processing snapshot: {snapshot_path}")
    result = {"success": False}

    def worker():
        result["success"] = upload_snapshot(snapshot_path, metadata)

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
            rabbit.produce(RabbitQueue.UPLOAD, metadata.to_json())
            slack_notify(f"Upload snapshot {snapshot_path} succeeded", "success", metadata.build_information.build_timestamp)
        else:
            metrics.inc_failure()
            rabbit.reject(delivery_tag, requeue=False)
            rabbit.produce(RabbitQueue.UPLOAD_FAILED, metadata.to_json())
            slack_notify(f"Upload snapshot {snapshot_path} failed", "failed", metadata.build_information.build_timestamp)


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
                delivery_tag, snapshot_metadata = rabbit.consume(queue)
                if delivery_tag:
                    metrics.set_total(rabbit.get_queue_size(queue))
                    snapshot_path = SnapshotMetadata.from_json(snapshot_metadata).build_information.build_path
                    metadata = SnapshotMetadata.from_json(snapshot_metadata)
                    try:
                        process_snapshot(delivery_tag, snapshot_path, metadata, rabbit)
                        break
                    except Exception as e:
                        logger.error(f"🚧 Could not process snapshot: {snapshot_path} ({e})")
        else:
            logger.info(f"⚠️No snapshots in queue. Sleeping for {QUEUE_WAIT_TIMEOUT // 60} minutes...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
            continue
    rabbit.close()


if __name__ == "__main__":
    metrics = Metrics(port=METRICS_PORT)
    main()
