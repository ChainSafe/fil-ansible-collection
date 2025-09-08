import hashlib
import json
import os
import subprocess
import threading
import time

from forest_helpers import get_api_info
from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue
from upload_snapshots import r2_upload_artifact

logger = setup_logger(os.path.basename(__file__))

CHAIN = os.getenv("CHAIN", "testnet")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
QUEUE_WAIT_TIMEOUT = 30 * 60  # 30 minutes
TIMEOUT_SECONDS = 40 * 60  # 40 minutes
metrics = None


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
    return json.dumps(data, indent=2)


def forest_validate(snapshot_path: str) -> bool:
    """Validate a snapshot using Forest CLI."""
    result = {"success": False}
    with open(snapshot_path, "rb") as f:
        snapshot_hash = hashlib.sha256(f.read()).hexdigest()
    snapshot_sha256 = f"{snapshot_path}.sha256sum"
    with open(snapshot_sha256, "w") as f:
        f.write(snapshot_hash)
    r2_upload_artifact(snapshot_sha256)

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
        snapshot_metadata = f"{snapshot_path}.metadata.json"
        with open(snapshot_metadata, "w") as f:
            f.write(target_snapshot_metadata)
        r2_upload_artifact(snapshot_metadata)
        result["success"] = True

    except subprocess.CalledProcessError as err:
        logger.error(f"Error fetching genesis timestamp: {err.stderr}", exc_info=True)
        raise

    return result["success"]


def validate_snapshot(snapshot_path: str) -> bool:
    """Wrapper around upload that also produces RabbitMQ status messages."""
    result = {"success": False}
    with metrics.track_upload():
        result["success"] = forest_validate(snapshot_path)

    return result["success"]


# noinspection DuplicatedCode
def process_snapshot(delivery_tag: int, snapshot_path: str, rabbit: RabbitMQClient = None):
    """Process snapshot with timeout logic."""
    logger.info(f"Start processing snapshot: {snapshot_path}")
    result = {"success": False}

    def worker():
        result["success"] = validate_snapshot(snapshot_path)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(TIMEOUT_SECONDS)

    if thread.is_alive():
        logger.warning(f"⏱ Timeout: {snapshot_path} exceeded {TIMEOUT_SECONDS // 60} minutes")
        metrics.inc_failure()
        rabbit.reject(delivery_tag, requeue=True)
    else:
        if result["success"]:
            rabbit.produce(RabbitQueue.VALIDATE, snapshot_path)
            metrics.inc_success()
            rabbit.ack(delivery_tag)

        else:
            rabbit.produce(RabbitQueue.VALIDATE_FAILED, snapshot_path)
            metrics.inc_failure()
            rabbit.reject(delivery_tag, requeue=False)


def main():
    # Initialize queue
    rabbit_setup = RabbitMQClient()
    rabbit_setup.setup([
        RabbitQueue.SNAPSHOT,
        RabbitQueue.SNAPSHOT_DIFF,
        RabbitQueue.SNAPSHOT_LATEST,
        RabbitQueue.VALIDATE,
        RabbitQueue.VALIDATE_FAILED
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
            logger.info("⚠️ No snapshots in queue. Sleeping...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
            continue


if __name__ == "__main__":
    metrics = Metrics(prefix="forest_validate_snapshot_", port=METRICS_PORT)
    main()
