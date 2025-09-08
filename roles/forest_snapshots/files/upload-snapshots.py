import hashlib
import os
import time
import threading
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

from logger_setup import setup_logger
from rabbitmq import RabbitMQClient, RabbitQueue
from metrics import Metrics

logger = setup_logger(os.path.basename(__file__))

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "my-bucket")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
QUEUE_WAIT_TIMEOUT = 30 * 60  # 30 minutes
TIMEOUT_SECONDS = 40 * 60  # 40 minutes

# S3 config
S3_READ_TIMEOUT = 300
S3_CONNECT_TIMEOUT = 60

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

# Initialize metrics
metrics = Metrics(prefix="forest_upload_snapshot_", port=METRICS_PORT)

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


def r2_upload_snapshot(file_path: str) -> bool:
    """Upload the snapshot file and checksum to S3."""
    try:
        basename = os.path.basename(file_path)
        destination = os.path.basename(os.path.dirname(file_path))
        key_prefix = f"{CHAIN}/{destination}/"
        try:
            s3.head_object(Bucket=BUCKET_NAME, Key=key_prefix + basename)
            logger.warning(f"Snapshot {file_path} already exists in s3://{BUCKET_NAME}/{key_prefix}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == "404":
                s3.upload_file(
                    file_path,
                    BUCKET_NAME,
                    key_prefix + basename,
                    Config=TransferConfig(
                        multipart_threshold=64 * MB,  # 64MB before multipart
                        multipart_chunksize=64 * MB,  # 64MB chunks
                        max_concurrency=10,  # parallel uploads
                        use_threads=True
                    )
                )
                logger.info(f"✅ Snapshot {file_path} uploaded to s3://{BUCKET_NAME}/{key_prefix}")
                # TODO: apply as validation logic
                # file_sha256 = file_path + ".sha256sum"
                # if not os.path.exists(file_sha256):
                #     checksum = sha256sum(file_path)
                #     with open(file_sha256, "w") as f:
                #         f.write(checksum + "\n")
                # s3.upload_file(file_sha256, BUCKET_NAME, key_prefix + basename + ".sha256sum")
                return True
            else:
                # Other errors (permission, etc.)
                raise
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
        result["success"] = r2_upload_snapshot(snapshot_path)
    return result["success"]


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
    logger.info("🐇 Waiting for snapshots...")
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
    main()
