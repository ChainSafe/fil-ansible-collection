import os
import subprocess
import threading
import time
from typing import Any

import docker
import requests

from forest_helpers import get_api_info
from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue
from slack import slack_notify
from snapshot import SnapshotMetadata
from upload_snapshots import r2_upload_artifact

logger = setup_logger(os.path.basename(__file__))

CHAIN = os.getenv("CHAIN", "testnet")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
LOTUS_CONTAINER = os.getenv("LOTUS_HOST")
LOTUS_RPC_PORT = os.getenv("LOTUS_RPC_PORT")
FULL_RPC_NODE = os.getenv("FULL_RPC_NODE", "http://127.0.0.1:1234/rpc/v0")
BACKUP_RPC_NODE = os.getenv("BACKUP_RPC_NODE", "http://127.0.0.1:1234/rpc/v0")
# Config
QUEUE_WAIT_TIMEOUT = 10 * 60  # 10 minutes
TIMEOUT_SECONDS = 60 * 60  # 1h
metrics = None


# noinspection HttpUrlsUsage
def request_lotus_api(
    method: str,
    params: list[Any] = None,
    endpoint: str = f'http://lotus:{LOTUS_RPC_PORT}/rpc/v0'
):
    """Request Lotus API."""
    response = requests.post(
        endpoint,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        },
        headers={
            'Content-Type': 'application/json'
        }
    )
    response.raise_for_status()
    return response.json()


def lotus_validate(snapshot_path: str) -> bool:
    """Validate a snapshot using Lotus daemon."""
    client = docker.from_env()
    logger.info("⏳Validating snapshot using lotus daemon")
    lotus = client.containers.get(LOTUS_CONTAINER)
    try:
        # Start Lotus daemon from the snapshot
        _, lotus_daemon = lotus.exec_run(
            # Send outputs to the main process's stdout/stderr
            f"sh -c 'lotus daemon --import-snapshot {snapshot_path} --remove-existing-chain >> /proc/1/fd/1 2>>/proc/1/fd/2'",
            stdout=False,
            stderr=False,
            detach=True
        )

        logger.info("⏱ Waiting for lotus API to be ready")
        result, lotus_wait_api = lotus.exec_run(
            "timeout 10m lotus wait-api --timeout 10m"
        )
        if result != 0:
            logger.error(f"Failed to wait for lotus API: {lotus_wait_api.decode().rstrip()}")
            return False

        logger.info("⏱ Waiting for lotus data sync to complete")
        result, lotus_sync_wait = lotus.exec_run(
            "timeout 1h lotus sync wait"
        )
        if result != 0:
            logger.error(f"Failed to wait for lotus data sync: {lotus_sync_wait.decode().rstrip()}")
            return False

        node_height = request_lotus_api(
            method="Filecoin.ChainHead",
            params=[]
        )['result']['Height']

        test_height = int(node_height) - 1950
        logger.info(f"🔗 Test Block Height: {test_height}")

        test_cid_req = request_lotus_api(
            method="Filecoin.ChainGetTipSetByHeight",
            params=[test_height, None],
            endpoint=FULL_RPC_NODE
        )
        if test_cid_req['result'] is None:
            logger.warning("❗ Failed to retrieve CID from FULLNODE_ENDPOINT. Trying GILFNODE_ENDPOINT...")
            test_cid_req = request_lotus_api(
                method="Filecoin.ChainGetTipSetByHeight",
                params=[test_height, None],
                endpoint=BACKUP_RPC_NODE
            )
        if test_cid_req['result'] is None or test_cid_req['result']['Cids'][0] is None:
            logger.error("❌ Failed to retrieve CID from both FULLNODE_ENDPOINT and GILFNODE_ENDPOINT.")
            return False
        test_cid = test_cid_req['result']['Cids'][0]['/']
        logger.debug(f"🛠️Query ChainGetBlock with the extracted CID {test_cid}")
        block_height_cid = request_lotus_api(
            method="Filecoin.ChainGetBlock",
            params=[{"/": test_cid}]
        )['result']['Height']
        if block_height_cid is None:
            logger.error(f"❌ Failed to retrieve block height for cid: {test_cid}.")
            return False
        if test_height != block_height_cid:
            logger.error(
                f"❌ Block height from lotus {test_height} is different from the block on remote {block_height_cid}.")
            return False
        logger.info(f"🔗 Block height {test_height} is corresponding to the CID {test_cid}"
                    f" which is present on the remote node on {block_height_cid}")
        logger.info("✅ Snapshot validation has finished by lotus")
    except Exception as err:
        logger.error(f"❌ Error validating snapshot on lotus: {err}", exc_info=True)
        return False
    finally:
        lotus.restart()

    return True


def forest_validate(snapshot_path: str) -> bool:
    """Validate a snapshot using Forest CLI."""
    args = [
        "forest-tool", "snapshot", "validate",
        "--check-network", CHAIN
    ]
    logger.debug(f"⚡ Running light checks on {snapshot_path} for {CHAIN}...")
    args.extend([
        "--check-links", "5",
        "--check-stateroots", "5"
    ])
    # if CHAIN == "calibnet":
    #     logger.debug(f"⚡ Running full checks on {snapshot_path} for {CHAIN}...")
    #     args.extend([
    #         "--check-links", str(SNAPSHOT_CONFIGS["latest"]["depth"]),
    #         "--check-stateroots", str(SNAPSHOT_CONFIGS["latest"]["state_roots"])
    #     ])
    args.append(snapshot_path)
    try:
        api_info = get_api_info()
        logger.debug(f"🔄Running command: {' '.join(args)}")
        proc = subprocess.Popen(
            args=[' '.join(args)],
            env={
                "FULLNODE_API_INFO": api_info
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            bufsize=1  # line-buffered
        )
        return_code = proc.wait(timeout=10 * 60)
        if return_code != 0:
            for line in proc.stdout:
                logger.debug(line.rstrip())
            logger.error(f"❌ Error validating snapshot on forest: {proc.stderr}", exc_info=True)
            return False
        logger.info(f"✅ Snapshot {snapshot_path} validation has finished by forest")
        return True
    except Exception as e:
        logger.error(f"❌Error running command: {e}", )
        return False
    except BaseException as e:
        logger.error(f"❌Error running command: {e}")
        return False


def update_metadata(metadata: SnapshotMetadata):
    """Update metadata file with validator and version."""
    metadata_file = f"{metadata.build_information.build_path}.metadata.json"
    with open(metadata_file, "w") as f:
        f.write(metadata.to_json())
    r2_upload_artifact(metadata_file)


def validate_snapshot(metadata: SnapshotMetadata) -> bool:
    """Wrapper around upload that also produces RabbitMQ status messages."""
    with metrics.track_processing():
        snapshot_type = os.path.basename(os.path.dirname(metadata.build_information.build_path))

        if snapshot_type in ["latest-v1", "latest-v2", "lite"]:
            # Forest validation
            metadata.build_information.validation.forest_version = os.getenv("FOREST_VERSION", "unknown")
            metadata.build_information.validation.lotus_version = os.getenv("FOREST_VERSION", "unknown")
            if not forest_validate(metadata.build_information.build_path):
                metadata.build_information.validation.success = False
                return False
            # Lotus validation
            if not lotus_validate(metadata.build_information.build_path):
                metadata.build_information.validation.success = False
                return False
            else:
                metadata.build_information.validation.success = True
    return True


# noinspection DuplicatedCode
def process_snapshot(delivery_tag: int, metadata: SnapshotMetadata, rabbit: RabbitMQClient = None):
    """Process snapshot with timeout logic."""
    logger.info(f"⏳Start processing snapshot: {metadata.build_information.build_path}")
    result = {"success": False}

    def worker():
        result["success"] = validate_snapshot(metadata)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(TIMEOUT_SECONDS)

    if thread.is_alive():
        logger.warning(f"⏱ Timeout: {metadata.build_information.build_path} exceeded {TIMEOUT_SECONDS // 60} minutes")
        metrics.inc_failure()
        rabbit.reject(delivery_tag, requeue=True)
    else:
        if result["success"]:
            logger.info(f"✅Snapshot {metadata.build_information.build_path} is valid.")
            rabbit.produce(RabbitQueue.VALIDATE, metadata.to_json())
            metrics.inc_success()
            rabbit.ack(delivery_tag)
            slack_notify(f"Validate snapshot {metadata.build_information.build_path} succeeded", "success",
                         metadata.build_information.build_timestamp)

        else:
            logger.error(f"❌Snapshot {metadata.build_information.build_path} is not valid.")
            rabbit.produce(RabbitQueue.VALIDATE_FAILED, metadata.to_json())
            metrics.inc_failure()
            rabbit.reject(delivery_tag, requeue=False)
            slack_notify(f"Validate snapshot {metadata.build_information.build_path} failed", "failed",
                         metadata.build_information.build_timestamp)


def main():
    # Initialize queue
    rabbit_setup = RabbitMQClient()
    rabbit_setup.setup([
        RabbitQueue.UPLOAD,
        RabbitQueue.VALIDATE,
        RabbitQueue.VALIDATE_FAILED
    ])
    rabbit_setup.close()
    while True:
        for queue in [RabbitQueue.UPLOAD]:
            with RabbitMQClient() as rabbit:
                delivery_tag, snapshot_metadata = rabbit.consume(queue)
                if delivery_tag:
                    metrics.set_total(rabbit.get_queue_size(queue))
                    try:
                        metadata = SnapshotMetadata.from_json(snapshot_metadata)
                        process_snapshot(delivery_tag, metadata, rabbit)
                        break
                    except Exception as e:
                        logger.error(f"🚧Could not process snapshot: {metadata.build_information.build_path} ({e})")
        else:
            logger.info(f"⚠️ No snapshots in queue. Sleeping {QUEUE_WAIT_TIMEOUT // 60}m...")
            time.sleep(QUEUE_WAIT_TIMEOUT)
            continue


if __name__ == "__main__":
    metrics = Metrics(port=METRICS_PORT)
    main()
