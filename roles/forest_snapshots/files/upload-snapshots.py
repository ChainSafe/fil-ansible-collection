import hashlib
import logging
import os
import sys
import time
import threading
import boto3
from boto3.s3.transfer import TransferConfig
from rabbitmq import RabbitMQClient
from metrics import Metrics

logger = logging.getLogger("upload-snapshots")
logger.setLevel(logging.DEBUG)
# StreamHandler to stdout
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "my-bucket")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
QUEUE_WAIT_TIMEOUT = 30 * 60  # 30 minutes
TIMEOUT_SECONDS = 40 * 60  # 40 minutes

# RabbitMQ queues
SNAPSHOT_QUEUE = "snapshot"
SNAPSHOT_LATEST_QUEUE = "snapshot-latest"
SNAPSHOT_DIFF_QUEUE = "snapshot-diff"
UPLOAD_QUEUE = "upload"
UPLOAD_FAILED_QUEUE = "upload-failed"

# S3 config
S3_READ_TIMEOUT = 300
S3_CONNECT_TIMEOUT = 60

# Initialize queue
rabbit = RabbitMQClient()
rabbit.connect()
rabbit.setup([SNAPSHOT_QUEUE, SNAPSHOT_LATEST_QUEUE, SNAPSHOT_DIFF_QUEUE, UPLOAD_QUEUE, UPLOAD_FAILED_QUEUE])

# Initialize metrics
metrics = Metrics(logger, prefix=f"forest_upload_snapshot_",port=METRICS_PORT)

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

def aws_upload_snapshot(file_path: str) -> bool:
    """Upload the snapshot file and checksum to S3."""
    try:
        basename = os.path.basename(file_path)
        destination = os.path.basename(os.path.dirname(file_path))
        key_prefix = f"{CHAIN}/{destination}/"

        s3.upload_file(
            file_path,
            BUCKET_NAME,
            key_prefix + basename,
            Config=TransferConfig(
                multipart_threshold=64 * MB,  # 64MB before multipart
                multipart_chunksize=64 * MB,  # 64MB chunks
                max_concurrency=10,           # parallel uploads
                use_threads=True
            )
        )
        file_sha256 = file_path + ".sha256sum"
        if not os.path.exists(file_sha256):
            checksum = sha256sum(file_path)
            with open(file_sha256, "w") as f:
                f.write(checksum + "\n")
        s3.upload_file(file_sha256, BUCKET_NAME, key_prefix + basename + ".sha256sum")

        logger.info(f"✅ Snapshot {file_path} uploaded to s3://{BUCKET_NAME}/{key_prefix}")
        return True
    except Exception as e:
        logger.error(f"❌ Snapshot {file_path} upload failed: {e}")
        return False

def sha256sum(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def upload_snapshot(snapshot_path: str) -> bool:
    """Wrapper around upload that also produces RabbitMQ status messages."""
    result = {"success": False}
    with metrics.track_upload():
        result["success"] = aws_upload_snapshot(snapshot_path)

    if result["success"]:
        rabbit.produce(UPLOAD_QUEUE, snapshot_path)
        return True
    else:
        rabbit.produce(UPLOAD_FAILED_QUEUE, snapshot_path)
        return False


def process_snapshot(delivery_tag: int, snapshot_path: str):
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
        else:
            metrics.inc_failure()
            rabbit.reject(delivery_tag, requeue=False)


def main():
    logger.info("🐇 Waiting for snapshots...")
    while True:
        for queue in [SNAPSHOT_QUEUE, SNAPSHOT_DIFF_QUEUE, SNAPSHOT_LATEST_QUEUE]:
            delivery_tag, snapshot_path = rabbit.consume(queue)
            if delivery_tag:
                metrics.set_total(rabbit.get_queue_size(queue))
                try:
                    process_snapshot(delivery_tag, snapshot_path)
                    break
                except Exception as e:
                    logger.error(f"Could not process snapshot: {snapshot_path} ({e})")
        else:
            logger.info("⚠️ No snapshots in queue. Sleeping...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
            continue
    rabbit.close()


if __name__ == "__main__":
    main()
