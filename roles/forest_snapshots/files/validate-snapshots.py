import hashlib
import os
import time
import threading

from logger_setup import setup_logger
from rabbitmq import RabbitMQClient, RabbitQueue
from metrics import Metrics

logger = setup_logger(os.path.basename(__file__))

CHAIN = os.getenv("CHAIN", "testnet")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
QUEUE_WAIT_TIMEOUT = 30 * 60  # 30 minutes
TIMEOUT_SECONDS = 40 * 60  # 40 minutes

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

# Initialize metrics
metrics = Metrics(prefix="forest_validate_snapshot_", port=METRICS_PORT)


def forest_validate(snapshot_path: str) -> bool:
    """Validate a snapshot using Forest CLI."""
    with open(snapshot_path, "rb") as f:
        snapshot_hash = hashlib.sha256(f.read()).hexdigest()
    with open(f"{snapshot_path}.sha256sum", "r") as f:
        target_snapshot_hash = f.read()
    return snapshot_hash == target_snapshot_hash


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
            logger.info("⚠️ No snapshots in queue. Sleeping...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
            continue


if __name__ == "__main__":
    main()
