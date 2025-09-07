#!/usr/bin/env python3
import logging
import os
import re
import sys
import time
import json
import socket
import subprocess
from datetime import datetime, timezone
from typing import Optional

from rabbitmq import RabbitMQClient
from metrics import Metrics
from slack import slack_notify

logger = logging.getLogger("build-snapshots")
logger.setLevel(logging.DEBUG)
# StreamHandler to stdout
if logger.hasHandlers():
    logger.handlers.clear()
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
QUEUE_WAIT_TIMEOUT = 30 * 60  # 30 minutes

# Directories (adjust as needed)
SNAPSHOT_PATH = os.getenv("SNAPSHOT_PATH", "/data/snapshots")
FULL_SNAPSHOTS_DIR = f"{SNAPSHOT_PATH}/full"
LITE_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/lite"
DIFF_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/diff"
LATEST_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/latest"
if SNAPSHOT_FORMAT != "v1":
    LATEST_SNAPSHOT_DIR = f"{SNAPSHOT_PATH}/latest-{SNAPSHOT_FORMAT}"

# RabbitMQ queues
COMPUTE_QUEUE = "compute"
SNAPSHOT_QUEUE = "snapshot"
SNAPSHOT_LATEST_QUEUE = "snapshot-latest"
SNAPSHOT_DIFF_QUEUE = "snapshot-diff"

# Initialize
rabbit = None
metrics = None

# Forest connection
forest_ip = socket.gethostbyname(os.getenv("FOREST_HOST"))
with open(os.getenv("FOREST_TOKEN_PATH"), "r") as f:
    forest_token = f.read()
FULLNODE_API_INFO=f"{forest_token}:/ip4/{forest_ip}/tcp/2345/http"
def secs_to_dhms(seconds):
    """Convert seconds to human-readable dhms."""
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    result = f"{m}m {s}s"
    if h > 0:
        result = f"{h}h {result}"
    if d > 0:
        result = f"{d}d {result}"
    return result

def get_genesis_timestamp() -> int:
    """Fetch genesis timestamp."""
    result=None
    try:
        result = subprocess.run(
            ["/usr/local/bin/forest-cli", "chain", "genesis"],
            env={
                "FULLNODE_API_INFO": FULLNODE_API_INFO
            },
            capture_output=True, text=True, check=True)
        head_info = json.loads(result.stdout)
        return int(head_info["Blocks"][0]["Timestamp"])
    except subprocess.CalledProcessError as e:
        metrics.inc_failure()
        logger.error(f"Error fetching genesis timestamp: {result.stderr}")
    except BaseException as e:
        metrics.inc_failure()
        logger.error(f"Error fetching genesis timestamp: {e}")

def get_current_epoch() -> int:
    """Fetch current chain head epoch."""
    result=None
    try:
        result = subprocess.run(
            ["/usr/local/bin/forest-cli", "chain", "head", "--format", "json"],
            env={
                "FULLNODE_API_INFO": FULLNODE_API_INFO
            },
            capture_output=True, text=True, check=True)
        head_info = json.loads(result.stdout)
        return int(head_info[0]["epoch"])
    except subprocess.CalledProcessError as err:
        metrics.inc_failure()
        logger.error(f"Error fetching genesis timestamp: {result.stderr}")
    except BaseException as err:
        metrics.inc_failure()
        logger.error(f"Error fetching current epoch: {err}")

def epoch_to_date(epoch: int):
    """Convert epoch to date."""
    return datetime.fromtimestamp(
        get_genesis_timestamp() + epoch * SECONDS_PER_EPOCH, tz=timezone.utc
    ).strftime("%Y-%m-%d")


def parse_epoch_from_snapshot_path(path: str) -> int:
    """
    Parse the epoch from a snapshot filename.
    The expected filename pattern includes 'height_<epoch>' before the extension.
    Returns the parsed epoch as int or raises ValueError if not found/invalid.
    """
    filename = os.path.basename(path)
    m = re.search(r"height_(\d+)", filename)
    if not m:
        raise ValueError(f"Cannot parse epoch from filename: {filename}")
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


def build_snapshot(
    epoch: int,
    folder: str,
    depth: int,
    archive: bool = False,
    diff: bool = False
):
    """Export snapshot."""
    snapshot_type = os.path.basename(folder)
    snapshot = f"{folder}/forest_snapshot_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}.forest.car.zst"
    if diff:
        diff_snapshot = f"{folder}/forest_diff_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}+3000.forest.car.zst"
    logger.info(f"Creating {snapshot_type} Snapshot: {snapshot}")

    start_time = time.time()
    if os.path.exists(snapshot):
        logger.warning(f"File {snapshot} exists. Skipping")
        return

    return_code = None
    try:
        # Export snapshot via forest-cli
        with metrics.track_processing():
            args = []
            if archive:
                args.extend([
                    "/usr/local/bin/forest-tool", "archive", "export",
                    "--epoch", str(epoch),
                ])
                if diff:
                    args.extend([
                        "--diff", str(epoch - depth),
                        "--diff-depth", str(STATE_ROOTS),
                    ])
            else:
                args.extend([
                    "/usr/local/bin/forest-cli", "snapshot", "export",
                    "--tipset", str(epoch),
                    "--depth", str(depth),
                    "--format", SNAPSHOT_FORMAT,
                ])
            os.makedirs(folder, exist_ok=True)
            proc = subprocess.Popen(
                args=args,
                cwd=folder,
                env={
                    "FULLNODE_API_INFO": FULLNODE_API_INFO,
                    "RUST_LOG": "info"
                },
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                logger.debug(line.rstrip())
            return_code = proc.wait()
        if return_code != 0:
            logger.error(f"Snapshot {snapshot_type} {epoch} failed")
            metrics.inc_failure()
            slack_notify(f"Snapshot {snapshot_type} {epoch} failed", "failed")
        else:
            duration = int(time.time() - start_time)
            snapshot = _resolve_snapshot_path(folder, epoch) or snapshot
            logger.info(f"Snapshot {snapshot_type} finished. Took {secs_to_dhms(duration)}")
            metrics.inc_success()
            if snapshot_type in ["latest", "latest-v2"]:
                rabbit.produce(SNAPSHOT_LATEST_QUEUE, snapshot)
                slack_notify(f"Build snapshot {snapshot_type} {epoch} succeeded", "success")
            elif snapshot_type == "lite":
                rabbit.produce(SNAPSHOT_QUEUE, snapshot)
                slack_notify(f"Build snapshot {snapshot_type} {epoch} succeeded", "success")
            elif snapshot_type == "diff":
                rabbit.produce(SNAPSHOT_DIFF_QUEUE, snapshot)
    except Exception as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")
    except BaseException as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")


def build_historic_snapshots():
    """Build historic snapshots for each epoch in the past."""
    historic_start_epoch = 0
    current_epoch = get_current_epoch()
    epochs_left = current_epoch - historic_start_epoch
    # Diff snapshots, lite snapshots and full snapshots
    metrics.set_total(epochs_left // DIFF_DEPTH + (epochs_left // LITE_DEPTH) * 2)

    delivery_tag, snapshot_path = rabbit.consume(SNAPSHOT_QUEUE, latest=True)
    historic_start_epoch = DEFAULT_START_EPOCH
    if not delivery_tag:
        logger.warning("No processed snapshots in queue. Starting over...")
    else:
        try:
            historic_start_epoch = parse_epoch_from_snapshot_path(snapshot_path)
        except Exception as e:
            logger.warning(
                f"Failed to parse epoch from snapshot path '{snapshot_path}': {e}. Falling back to DEFAULT_START_EPOCH.")
            historic_start_epoch = DEFAULT_START_EPOCH

    historic_start_epoch = (historic_start_epoch // LITE_DEPTH) * LITE_DEPTH

    for epoch in range(historic_start_epoch + LITE_DEPTH, current_epoch, LITE_DEPTH):
        while True:
            latest_computed_tag, latest_computed_epoch = rabbit.consume(COMPUTE_QUEUE, latest=True)
            if latest_computed_tag:
                latest_computed_epoch = int(latest_computed_epoch)
                if latest_computed_epoch > epoch:
                    logger.info(f"Epoch {epoch} is computed. Continuing...")
                    break
            logger.warning(f"Epoch {epoch} is not computed. Waiting {QUEUE_WAIT_TIMEOUT // 60} minutes...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
        logger.info(f"Processing epochs {epoch - LITE_DEPTH} to {epoch} on {CHAIN}")
        # Full Snapshot
        build_snapshot(epoch, FULL_SNAPSHOTS_DIR, LITE_DEPTH)
        # Lite Snapshot
        build_snapshot(epoch, LITE_SNAPSHOT_DIR, LITE_DEPTH, archive=True)
        # Diff Snapshots
        for diff_epoch in range(epoch - LITE_DEPTH, epoch, DIFF_DEPTH):
            build_snapshot(diff_epoch, DIFF_SNAPSHOT_DIR, DIFF_DEPTH, archive=True, diff=True)


def build_latest_snapshots():
    """Build the latest snapshot for the current epoch in the past LATEST_DEPTH."""
    old_epoch = 0
    while True:
        epoch = get_current_epoch()
        if epoch >= old_epoch:
            logger.info(f"Processing epochs {epoch - LATEST_DEPTH} to {epoch} on {CHAIN}")
            build_snapshot(epoch, LATEST_SNAPSHOT_DIR, LATEST_DEPTH)
            logger.info(f"Sleeping for {secs_to_dhms(BUILD_DELAY)} seconds...")
            time.sleep(BUILD_DELAY)
            old_epoch = epoch


if __name__ == "__main__":
    # Initialize queue
    rabbit = RabbitMQClient()
    try:
        rabbit.connect()
        rabbit.setup([COMPUTE_QUEUE, SNAPSHOT_QUEUE, SNAPSHOT_DIFF_QUEUE, SNAPSHOT_LATEST_QUEUE])

        # Initialize metrics
        metrics = Metrics(logger, prefix=f"forest_build_snapshot_", port=METRICS_PORT)
        logger.info(f"📊 Prometheus metrics available on port {METRICS_PORT}")


        if BUILD_LATEST_SNAPSHOTS:
            build_latest_snapshots()
        else:
            build_historic_snapshots()
    except Exception as e:
        logger.error(f"Error running build-snapshots: {e}")
    finally:
        rabbit.close()
