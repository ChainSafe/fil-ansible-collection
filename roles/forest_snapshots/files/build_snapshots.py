import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

from forest_helpers import get_api_info, get_current_epoch, get_genesis_timestamp, secs_to_dhms, wait_for_f3, \
    SNAPSHOT_CONFIGS
from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue
from slack import slack_notify
from snapshot import SnapshotMetadata, Snapshot

logger = setup_logger(os.path.basename(__file__))

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
BUILD_DELAY = int(os.getenv("BUILD_DELAY", f"{20 * 60}"))  # 20 minutes
BUILD_LATEST_SNAPSHOTS = os.getenv("BUILD_LATEST_SNAPSHOTS", "false").lower() in {"1", "true", "yes"}
WAIT_FOR_COMPUTATION = os.getenv("WAIT_FOR_COMPUTATION", "true").lower() in {"1", "true", "yes"}
DEFAULT_START_EPOCH = int(os.getenv("DEFAULT_START_EPOCH", "0"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "6116"))
SNAPSHOT_PATH = os.getenv("SNAPSHOT_PATH", "/data/snapshots")
SNAPSHOT_ARCHIVE_PATH = os.getenv("SNAPSHOT_ARCHIVE_PATH", "/data/snapshots-archive")

# Config
QUEUE_WAIT_TIMEOUT = 10 * 60  # 10 minutes
SECONDS_PER_EPOCH = 30

# Initialize
rabbit_setup = RabbitMQClient()
rabbit_setup.setup([
    RabbitQueue.COMPUTE,
    RabbitQueue.SNAPSHOT,
    RabbitQueue.SNAPSHOT_DIFF,
    RabbitQueue.SNAPSHOT_LATEST,
])
rabbit_setup.close()

metrics = Metrics(port=METRICS_PORT)


def epoch_to_date(epoch: int):
    """Convert epoch to date."""
    return datetime.fromtimestamp(
        get_genesis_timestamp() + epoch * SECONDS_PER_EPOCH, tz=timezone.utc
    ).strftime("%Y-%m-%d")


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
        logger.error(f"❌Failed to resolve snapshot path in {folder}: {e}")
    return None


def gather_archive_metadata(snapshot_path: str):
    try:
        archive_metadata = subprocess.run(
            ["/usr/local/bin/forest-tool", "archive", "metadata", snapshot_path],
            env={
                "FULLNODE_API_INFO": get_api_info()
            },
            capture_output=True,
            text=True
        ).stdout.splitlines()
        archive_info = subprocess.run(
            ["/usr/local/bin/forest-tool", "archive", "info", snapshot_path],
            env={
                "FULLNODE_API_INFO": get_api_info()
            },
            capture_output=True,
            text=True,
            check=True
        ).stdout.splitlines()
    except subprocess.CalledProcessError as err:
        logger.error(f"⛔Error fetching snapshot metadata: {err.stderr}", exc_info=True)
        raise

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


def get_build_args(
    snapshot_type: str,
    depth: int,
    state_roots: int,
    epoch: int,
    snapshot: str
) -> list[str]:
    """Get the build args."""
    args = []
    if snapshot_type == "diff":
        args.extend([
            "forest-cli", "snapshot",
            "export-diff",
            "--from", str(epoch),
            "--to", str(epoch - depth),
        ])
    else:
        args.extend([
            "forest-cli", "snapshot",
            "export",
            "--tipset", str(epoch),
        ])
    if snapshot_type == "latest-v2":
        wait_for_f3()
        args.extend(["--format", "v2"])
    if snapshot_type == "latest-v1":
        args.extend(["--format", "v1"])
    args.extend([
        "--depth", str(state_roots),
        "--output-path", snapshot
    ])

    return args


def build_snapshot(
    epoch: int,
    folder: str,
    args: list[str],
    diff: bool = False,
) -> Tuple[str, bool]:
    """Export snapshot."""
    snapshot_type = os.path.basename(folder)
    snapshot = f"{folder}/forest_{'diff' if diff else 'snapshot'}_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}{'+3000' if diff else ''}.forest.car.zst"
    logger.info(f"💾Creating {snapshot_type} Snapshot: {snapshot}")

    start_time = time.time()

    return_code = None
    if os.path.exists(snapshot):
        return snapshot, True
    while True:
        try:
            build_ts = slack_notify(f"Creating {snapshot_type} Snapshot: {snapshot}", "info")
            # Export snapshot via forest-cli
            with metrics.track_processing():
                os.makedirs(folder, exist_ok=True)
                api_info = get_api_info()
                logger.info(f"⏳Running command: {' '.join(args)}")
                proc = subprocess.Popen(
                    args=[' '.join(args)],
                    cwd=folder,
                    env={
                        "FULLNODE_API_INFO": api_info
                    },
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True,
                    bufsize=1  # line-buffered
                )
                export_output = ''
                for line in proc.stdout:
                    export_output += line + '\n'
                    logger.debug(line.rstrip())
                return_code = proc.wait()
            if return_code != 0 and 'Another chain export job is still in progress' in export_output:
                logger.warning(
                    f"🔄 Another chain export job is still in progress. Retrying in {QUEUE_WAIT_TIMEOUT // 60}m..."
                )
                time.sleep(QUEUE_WAIT_TIMEOUT)
                continue
            if return_code != 0 or not os.path.exists(snapshot):
                logger.error(f"⛔Snapshot {snapshot_type} {epoch} failed")
                metrics.inc_failure()
                slack_notify(f"Build snapshot {snapshot_type} {epoch} failed", "failed", build_ts)
                return '', False
            else:
                duration = int(time.time() - start_time)
                snapshot = _resolve_snapshot_path(folder, epoch) or snapshot
                logger.info(f"✅Snapshot {snapshot_type} finished. Took {secs_to_dhms(duration)}")
                metrics.inc_success()

                snapshot_meta = Snapshot.model_validate(gather_archive_metadata(snapshot))
                # noinspection PyArgumentList
                metadata = SnapshotMetadata(
                    snapshot=snapshot_meta,
                )
                metadata.build_information.build_timestamp = build_ts
                metadata.build_information.build_date = datetime.fromtimestamp(float(build_ts), tz=timezone.utc)
                metadata.build_information.build_path = snapshot
                metadata.build_information.epoch = epoch
                metadata.build_information.epoch_date = datetime.fromtimestamp(
                    get_genesis_timestamp() + epoch * SECONDS_PER_EPOCH, tz=timezone.utc
                )
                logger.debug(f"🔗 Snapshot metadata: {metadata}")

                with RabbitMQClient() as rabbit:
                    if snapshot_type in ["latest-v1", "latest-v2"]:
                        rabbit.produce(RabbitQueue.SNAPSHOT_LATEST, metadata.to_json())
                    elif snapshot_type == "lite":
                        rabbit.produce(RabbitQueue.SNAPSHOT, metadata.to_json())
                    elif snapshot_type == "diff":
                        rabbit.produce(RabbitQueue.SNAPSHOT_DIFF, metadata.to_json())
                slack_notify(f"Build snapshot {snapshot_type} {epoch} succeeded", "success", build_ts)
                return snapshot, True
        except Exception as e:
            metrics.inc_failure()
            logger.error(f"❌Error running command: {e}", exc_info=True)
            return '', False
        except BaseException as e:
            metrics.inc_failure()
            logger.error(f"❌Error running command: {e}", exc_info=True)
            return '', False


def wait_for_epoch_compute(epoch):
    """Wait until the given epoch is computed in the queue."""
    while True:
        with RabbitMQClient() as rabbit:
            latest_tag, latest_epoch = rabbit.consume(RabbitQueue.COMPUTE, latest=True)
            if latest_tag and int(latest_epoch) > epoch:
                logger.info(f">>> Epoch {epoch} is computed. Continuing...")
                return
        logger.warning(f"⏱ Epoch {epoch} is not computed. Waiting {QUEUE_WAIT_TIMEOUT // 60} minutes...")
        time.sleep(QUEUE_WAIT_TIMEOUT)


def process_historic_epoch(epoch: int, diff: bool = False) -> bool:
    """Build full, lite, and diff snapshots for a given epoch."""
    if diff:
        # Diff snapshots
        snapshot_config = SNAPSHOT_CONFIGS["diff"]
        folder = f"{SNAPSHOT_ARCHIVE_PATH}/{snapshot_config['folder']}"
        snapshot = f"{folder}/forest_diff_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}+{snapshot_config['depth']}.forest.car.zst"
        _, success = build_snapshot(
            epoch,
            folder,
            args=get_build_args(
                "diff",
                snapshot_config["depth"],
                snapshot_config["state_roots"],
                epoch,
                snapshot
            ),
            diff=True
        )
        if not success:
            logger.warning(f"🚧Diff snapshot for epoch {epoch} failed. Retrying...")
            return False
    else:
        # Lite snapshot
        snapshot_config = SNAPSHOT_CONFIGS["lite"]
        folder = f"{SNAPSHOT_ARCHIVE_PATH}/{snapshot_config['folder']}"
        snapshot = f"{folder}/forest_snapshot_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}.forest.car.zst"
        _, success = build_snapshot(
            epoch,
            folder,
            args=get_build_args(
                "lite",
                snapshot_config["depth"],
                snapshot_config["state_roots"],
                epoch,
                snapshot
            )
        )
        if not success:
            logger.warning(f"🚧Lite snapshot for epoch {epoch} failed. Retrying...")
            return False
    logger.info(f"✅Epoch {epoch} built successfully.")
    return True


def get_historic_epoch(queue: RabbitQueue):
    """Get the latest historic epoch."""
    with RabbitMQClient() as rabbit:
        _, snapshot_metadata = rabbit.consume(queue, latest=True)
    if not snapshot_metadata:
        logger.warning(f"❗No processed epochs {queue} queue. Starting over...")
        return DEFAULT_START_EPOCH
    return SnapshotMetadata.from_json(snapshot_metadata).build_information.epoch


def build_historic_snapshots():
    """Build historic snapshots for each epoch in the past."""
    while True:
        restart = False
        current_epoch = get_current_epoch()
        logger.info(f"⏳Starting from current epoch: {current_epoch}")

        lite_depth = SNAPSHOT_CONFIGS["lite"]["depth"]
        diff_depth = SNAPSHOT_CONFIGS["diff"]["depth"]

        # Adjust historic epoch to correct start points
        lite_historic_epoch = (get_historic_epoch(RabbitQueue.SNAPSHOT) // lite_depth) * lite_depth
        diff_historic_epoch = (get_historic_epoch(RabbitQueue.SNAPSHOT_DIFF) // diff_depth) * diff_depth

        total_executions = ((current_epoch - diff_historic_epoch) // diff_depth) + (
            current_epoch - lite_historic_epoch // lite_depth)
        metrics.set_total(total_executions)

        if current_epoch - lite_historic_epoch > SNAPSHOT_CONFIGS["lite"]["depth"]:
            logger.info(f">>> Starting from epoch: {lite_historic_epoch + lite_depth} to {current_epoch}")
            for epoch in range(lite_historic_epoch + lite_depth, current_epoch, lite_depth):
                if WAIT_FOR_COMPUTATION:
                    logger.info(f"⏱ Waiting for epoch {epoch} compute...")
                    wait_for_epoch_compute(epoch)
                if not process_historic_epoch(epoch):
                    logger.warning(f"⚠️Lite epoch {epoch} failed. Restarting...")
                    time.sleep(QUEUE_WAIT_TIMEOUT)
                    restart = True
                    break

        if current_epoch - diff_historic_epoch > SNAPSHOT_CONFIGS["diff"]["depth"]:
            logger.info(f">>> Starting from epoch: {diff_historic_epoch + diff_depth} to {current_epoch}")
            for epoch in range(diff_historic_epoch + diff_depth, current_epoch, diff_depth):
                if WAIT_FOR_COMPUTATION:
                    logger.info(f"⏱ Waiting for epoch {epoch} compute...")
                    wait_for_epoch_compute(epoch)
                if not process_historic_epoch(epoch, diff=True):
                    logger.warning(f"⚠️Diff epoch {epoch} failed. Restarting...")
                    time.sleep(QUEUE_WAIT_TIMEOUT)
                    restart = True
                    break

        if not restart:
            logger.warning("💤 Not enough epochs left to build historic snapshots. Sleeping for 24h...")
            time.sleep(24 * 60 * 60)


def build_latest_snapshots():
    """Build the latest snapshot for the current epoch."""
    while True:
        epoch = get_current_epoch()
        previous_epoch = 0
        with RabbitMQClient() as rabbit:
            _, previous_built_snapshot = rabbit.consume(RabbitQueue.SNAPSHOT_LATEST, latest=True)
        if previous_built_snapshot:
            previous_epoch = SnapshotMetadata.from_json(previous_built_snapshot).build_information.epoch
        if (epoch - previous_epoch) >= 2 * 60 * 60 / SECONDS_PER_EPOCH:  # more than 2 hours since last build
            logger.info(f"⏳Processing epoch {epoch} on {CHAIN}")
            # Build v2 snapshot
            folder = f"{SNAPSHOT_PATH}/{SNAPSHOT_CONFIGS['latest']['folder']}-v2"
            snapshot = f"{folder}/forest_snapshot_{CHAIN}_{epoch_to_date(epoch)}_height_{epoch}.forest.car.zst"
            build_snapshot(
                epoch=epoch,
                folder=folder,
                args=get_build_args(
                    "latest-v2",
                    SNAPSHOT_CONFIGS["latest"]["depth"],
                    SNAPSHOT_CONFIGS["latest"]["state_roots"],
                    epoch,
                    snapshot
                )
            )
        else:
            logger.warning(f"⏱ Latest snapshot for epoch {previous_epoch} recently was already built. Skipping...")
        logger.info(f"⏱ Sleeping for {secs_to_dhms(BUILD_DELAY)}...")
        time.sleep(BUILD_DELAY)


if __name__ == "__main__":
    try:
        if BUILD_LATEST_SNAPSHOTS:
            build_latest_snapshots()
        else:
            build_historic_snapshots()
    except Exception as exc:
        logger.exception(f"❌Error running build-snapshots: {exc}")
