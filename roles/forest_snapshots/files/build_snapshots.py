import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

from forest_helpers import get_api_info, get_current_epoch, get_genesis_timestamp, secs_to_dhms, wait_for_f3
from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue
from slack import slack_notify

logger = setup_logger(os.path.basename(__file__))

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
SNAPSHOT_FORMAT = os.getenv("SNAPSHOT_FORMAT", "v1")
BUILD_DELAY = int(os.getenv("BUILD_DELAY", f"{6 * 60 * 60}"))  # seconds
BUILD_LATEST_SNAPSHOTS = os.getenv("BUILD_LATEST_SNAPSHOTS", "false").lower() in {"1", "true", "yes"}
DEFAULT_START_EPOCH = int(os.getenv("DEFAULT_START_EPOCH", "0"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
SECONDS_PER_EPOCH = 30
LITE_DEPTH = 30000
DIFF_DEPTH = 3000
LATEST_DEPTH = 2000
STATE_ROOTS = 900
QUEUE_WAIT_TIMEOUT = 10 * 60  # 10 minutes

# Directories (adjust as needed)
SNAPSHOT_PATH = os.getenv("SNAPSHOT_PATH", "/data/snapshots")
FULL_SNAPSHOTS_DIR = f"{SNAPSHOT_PATH}/full"
LITE_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/lite"
DIFF_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/diff"
LATEST_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/latest"
if SNAPSHOT_FORMAT != "v1":
    LATEST_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/latest-{SNAPSHOT_FORMAT}"

# Initialize
rabbit_setup = RabbitMQClient()
rabbit_setup.setup([
    RabbitQueue.COMPUTE,
    RabbitQueue.SNAPSHOT,
    RabbitQueue.SNAPSHOT_DIFF,
    RabbitQueue.SNAPSHOT_LATEST,
])
rabbit_setup.close()

metrics = Metrics(prefix="forest_build_snapshot_", port=METRICS_PORT)


def epoch_to_date(epoch: int):
    """Convert epoch to date."""
    return datetime.fromtimestamp(
        get_genesis_timestamp() + epoch * SECONDS_PER_EPOCH, tz=timezone.utc
    ).strftime("%Y-%m-%d")


def parse_epoch_from_snapshot_path(path: str, default: int = 0) -> int:
    """
    Parse the epoch from a snapshot filename.
    The expected filename pattern includes 'height_<epoch>' before the extension.
    Returns the parsed epoch as int or raises ValueError if not found/invalid.
    """
    filename = os.path.basename(path)
    m = re.search(r"height_(\d+)", filename)
    if not m:
        logger.error(f"Cannot parse epoch from filename: {filename}, revert to default start epoch {default}")
        return default
    return int(m.group(1))


def _resolve_snapshot_path(folder: str, epoch: int) -> Optional[str]:
    """
    Try to find the actual snapshot file produced for a given epoch by scanning the folder.
    Returns the full path if found, otherwise None.
    """
    try:
        for name in os.listdir(folder):
            if f"height_{epoch}" in name and name.endswith(".forest.car.zst"):
                return os.path.join(folder, name)
    except Exception as e:
        logger.debug(f"Failed to resolve snapshot path in {folder}: {e}")
    return None


def get_build_args(
    snapshot_type: str,
    full_snapshot: str,
    depth: int,
    epoch: int,
    diff: bool,
    snapshot: str
) -> str:
    """Get build args."""
    args = []
    if snapshot_type == "latest-v2":
        wait_for_f3()

    if not full_snapshot:
        args.extend([
            "/usr/local/bin/forest-tool", "archive", "export",
            "--epoch", str(epoch),
            "--output-path", snapshot
        ])
    else:
        args.extend([
            "/usr/local/bin/forest-cli", "snapshot", "export",
            "--tipset", str(epoch),
            "--depth", str(depth),
            "--format", SNAPSHOT_FORMAT,
            "--output-path", snapshot
        ])
        if diff:
            args.extend([
                "--diff", str(epoch - depth),
                "--diff-depth", str(STATE_ROOTS),
            ])
        args.append(full_snapshot)
    return ' '.join(args)


def build_snapshot(
    epoch: int,
    folder: str,
    depth: int,
    rabbit: RabbitMQClient,
    full_snapshot: str = None,
    diff: bool = False
):
    """Export snapshot."""
    snapshot_type = os.path.basename(folder)
    snapshot = f"{folder}/forest_{'diff' if diff else 'snapshot'}_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}{'+3000' if diff else ''}.forest.car.zst"
    logger.info(f"Creating {snapshot_type} Snapshot: {snapshot}")

    start_time = time.time()
    if os.path.exists(snapshot):
        logger.warning(f"File {snapshot} exists. Skipping")
        return snapshot, True

    return_code = None
    try:
        # Export snapshot via forest-cli
        with metrics.track_processing():
            args = get_build_args(snapshot_type, full_snapshot, depth, epoch, diff, snapshot)
            os.makedirs(folder, exist_ok=True)
            logger.debug(f"Running command: {args}")
            proc = subprocess.Popen(
                args=args,
                cwd=folder,
                env={
                    "FULLNODE_API_INFO": get_api_info(),
                    "RUST_LOG": "info"
                },
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True
            )
            return_code = proc.wait()
        if return_code != 0:
            for line in proc.stdout:
                logger.error(line.rstrip())
            logger.error(f"Snapshot {snapshot_type} {epoch} failed")
            metrics.inc_failure()
            slack_notify(f"Snapshot {snapshot_type} {epoch} failed", "failed")
        else:
            duration = int(time.time() - start_time)
            snapshot = _resolve_snapshot_path(folder, epoch) or snapshot
            logger.info(f"Snapshot {snapshot_type} finished. Took {secs_to_dhms(duration)}")
            metrics.inc_success()
            if snapshot_type in ["latest", "latest-v2"]:
                rabbit.produce(RabbitQueue.SNAPSHOT_LATEST, snapshot)
                slack_notify(f"Build snapshot {snapshot_type} {epoch} succeeded", "success")
            elif snapshot_type == "lite":
                rabbit.produce(RabbitQueue.SNAPSHOT, snapshot)
                slack_notify(f"Build snapshot {snapshot_type} {epoch} succeeded", "success")
            elif snapshot_type == "diff":
                rabbit.produce(RabbitQueue.SNAPSHOT_DIFF, snapshot)
            return snapshot, True
    except Exception as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")
        raise
    except BaseException as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")
        raise
    finally:
        return None, False


def wait_for_epoch_compute(epoch):
    """Wait until the given epoch is computed in the queue."""
    while True:
        with RabbitMQClient() as rabbit:
            latest_tag, latest_epoch = rabbit.consume(RabbitQueue.COMPUTE, latest=True)
            if latest_tag and int(latest_epoch) > epoch:
                logger.info(f"Epoch {epoch} is computed. Continuing...")
                return
        logger.warning(f"Epoch {epoch} is not computed. Waiting {QUEUE_WAIT_TIMEOUT // 60} minutes...")
        time.sleep(QUEUE_WAIT_TIMEOUT)


def process_historic_epoch(epoch: int):
    """Build full, lite, and diff snapshots for a given epoch."""
    logger.info(f"Processing epochs {epoch - LITE_DEPTH} to {epoch} on {CHAIN}")

    # Full snapshot
    with RabbitMQClient() as rabbit:
        full_snapshot, success = build_snapshot(epoch, FULL_SNAPSHOTS_DIR, LITE_DEPTH, rabbit)
        if not success:
            logger.warning(f"Full snapshot for epoch {epoch} failed. Retrying...")
            return False

    # Lite snapshot
    with RabbitMQClient() as rabbit:
        _, success = build_snapshot(epoch, LITE_SNAPSHOT_DIR, STATE_ROOTS, rabbit, full_snapshot=full_snapshot)
        if not success:
            logger.warning(f"Lite snapshot for epoch {epoch} failed. Retrying...")
            return False

    # Diff snapshots
    with RabbitMQClient() as rabbit:
        for diff_epoch in range(epoch - LITE_DEPTH, epoch, DIFF_DEPTH):
            _, success = build_snapshot(
                diff_epoch, DIFF_SNAPSHOT_DIR, DIFF_DEPTH, rabbit,
                full_snapshot=full_snapshot, diff=True
            )
            if not success:
                logger.warning(f"Diff snapshot for epoch {diff_epoch} failed. Retrying...")
                return False
    logger.info(f"Epoch {epoch} built successfully.")
    return True


def build_historic_snapshots():
    """Build historic snapshots for each epoch in the past."""
    historic_epoch = DEFAULT_START_EPOCH
    current_epoch = get_current_epoch()
    while True:
        with RabbitMQClient() as rabbit:
            delivery_tag, snapshot_path = rabbit.consume(RabbitQueue.SNAPSHOT, latest=True)
        if not delivery_tag:
            logger.warning("No processed epochs in queue. Starting over...")
        else:
            historic_epoch = parse_epoch_from_snapshot_path(snapshot_path, DEFAULT_START_EPOCH)
        epochs_left = current_epoch - historic_epoch
        # Diff snapshots, lite snapshots and full snapshots
        metrics.set_total(epochs_left // DIFF_DEPTH + (epochs_left // LITE_DEPTH) * 2)

        historic_epoch = (historic_epoch // LITE_DEPTH) * LITE_DEPTH
        for epoch in range(historic_epoch + LITE_DEPTH, current_epoch, LITE_DEPTH):
            wait_for_epoch_compute(epoch)
            if not process_historic_epoch(epoch):
                logger.warning(f"Epoch {epoch} failed. Restarting...")
                time.sleep(QUEUE_WAIT_TIMEOUT)
                break


def build_latest_snapshots():
    """Build the latest snapshot for the current epoch."""
    while True:
        with RabbitMQClient() as rabbit:
            epoch = get_current_epoch()
            previous_epoch = 0
            _, previous_built_snapshot = rabbit.consume(RabbitQueue.SNAPSHOT_LATEST, latest=True)
            if previous_built_snapshot:
                previous_epoch = parse_epoch_from_snapshot_path(previous_built_snapshot)
            if (epoch - previous_epoch) > 10:
                logger.info(f"Processing epoch {epoch} on {CHAIN}")
                build_snapshot(epoch, LATEST_SNAPSHOT_DIR, LATEST_DEPTH, rabbit)
            else:
                logger.warning(f"Latest snapshot for epoch {previous_epoch} is already built. Skipping...")
        logger.info(f"Sleeping for {secs_to_dhms(BUILD_DELAY)}...")
        time.sleep(BUILD_DELAY)


if __name__ == "__main__":
    try:
        if BUILD_LATEST_SNAPSHOTS:
            build_latest_snapshots()
        else:
            build_historic_snapshots()
    except Exception as exc:
        logger.exception(f"Error running build-snapshots: {exc}")
