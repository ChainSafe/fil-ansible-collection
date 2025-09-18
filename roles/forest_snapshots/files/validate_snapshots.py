import os
import subprocess
import threading
import time
from typing import Any

import docker
import requests

from forest_helpers import get_api_info, SNAPSHOT_CONFIGS
from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue

logger = setup_logger(os.path.basename(__file__))

CHAIN = os.getenv("CHAIN", "testnet")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
FULL_RPC_NODE = os.getenv("FULL_RPC_NODE", "http://127.0.0.1:1234/rpc/v0")
BACKUP_RPC_NODE = os.getenv("BACKUP_RPC_NODE", "http://127.0.0.1:1234/rpc/v0")
# Config
QUEUE_WAIT_TIMEOUT = 10 * 60  # 10 minutes
TIMEOUT_SECONDS = 60 * 60  # 1h
metrics = None


def request_lotus_api(payload: dict[str, Any], endpoint: str = 'http://127.0.0.1:1234/rpc/v0'):
    """Request Lotus API."""
    response = requests.post(endpoint, json=payload, headers={'Content-Type': 'application/json'})
    response.raise_for_status()
    return response.json()

def lotus_validate(snapshot_path: str) -> bool:
    """Validate a snapshot using Lotus daemon."""
    snapshot_type = os.path.basename(os.path.dirname(snapshot_path))
    if snapshot_type in ["latest", "latest-v2"]:
        try:
            client = docker.from_env()
            logger.info("Validating snapshot using lotus daemon")
            lotus_daemon = client.containers.run(
                name="lotus-validate",
                image="filecoin/lotus-all-in-one:v1.34.1",
                entrypoint="/bin/bash",
                user="root",
                command=f"lotus daemon --import-snapshot {snapshot_path}",
                volumes={
                    os.getenv("FOREST_HOST_SNAPSHOT_PATH"): {
                        "bind": os.getenv("FOREST_CONTAINER_SNAPSHOT_PATH"),
                        "mode": "rw"
                    }
                },
                detach=True,
                network=os.getenv("FOREST_HOST"),
                tty=False,
                remove=True
            )

            for chunk in lotus_daemon.exec_run("lotus wait-api --timeout 30m", stream=True):
                logger.debug(chunk.decode().rstrip())
            for chunk in lotus_daemon.exec_run("timeout 6h lotus sync-wait", stream=True):
                logger.debug(chunk.decode().rstrip())
            lotus_info = lotus_daemon.exec_run("lotus info").output.decode()
            if 'Chain: [sync ok]' in lotus_info:
                logger.info('✅ Chain is in sync.')
            else:
                logger.error('✅ Chain is in sync.')
                return False

            node_height = request_lotus_api(
                {
                    "jsonrpc": "2.0",
                    "method": "Filecoin.ChainHead",
                    "params": [],
                    "id": 1
                }
            )['result']['Height']
            test_height = int(node_height) - 1950
            logger.info(f"🔗 Test Block Height: {test_height}")

            test_cid_req = request_lotus_api({
                "jsonrpc": "2.0",
                "method": "Filecoin.ChainGetTipSetByHeight",
                "params": [test_height, None],
                "id": 1
            }, FULL_RPC_NODE)
            if test_cid_req['result'] is None:
                logger.warning("❗ Failed to retrieve CID from FULLNODE_ENDPOINT. Trying GILFNODE_ENDPOINT...")
                test_cid_req = request_lotus_api({
                    "jsonrpc": "2.0",
                    "method": "Filecoin.ChainGetTipSetByHeight",
                    "params": [test_height, None],
                    "id": 1
                }, BACKUP_RPC_NODE)
            if test_cid_req['result'] is None or test_cid_req['result']['Cids'][0] is None:
                logger.error("Failed to retrieve CID from both FULLNODE_ENDPOINT and GILFNODE_ENDPOINT.")
                return False
            test_cid = test_cid_req['result']['Cids'][0]['/']
            logger.debug("Query ChainGetBlock with the extracted CID")
            block_height_cid = request_lotus_api(
                {
                    "jsonrpc": "2.0",
                    "method": "Filecoin.ChainGetBlock",
                    "params": [{"/": test_cid}],
                    "id": 1
                }
            )['result']['Height']
            if block_height_cid is None:
                logger.error(f"Failed to retrieve block height for cid: {test_cid}.")
                return False

            logger.info(f"Block Height from ChainGetBlock: {test_height}")
            logger.info("🛠️ Snapshot validation has finished")
        except Exception as err:
            logger.error(f"❌ Error validating snapshot on lotus: {err}", exc_info=True)
            return False

    return True

def forest_validate(snapshot_path: str) -> bool:
    """Validate a snapshot using Forest CLI."""
    try:
        snapshot_type = os.path.basename(os.path.dirname(snapshot_path))
        if snapshot_type in ["latest", "latest-v2", "lite"]:
            args = [
                "/usr/local/bin/forest-tool", "snapshot", "validate-diffs",
                "--check-network", CHAIN
            ]
            if CHAIN == "mainnet":
                print(f"⚡ Running light checks on {snapshot_path} for {CHAIN}...")
                args.extend([
                    "--check-links", "0",
                    "--check-stateroots", "5"
                ])
            else:
                print(f"✅ Running full checks on {snapshot_path} for {CHAIN}...")
                args.extend([
                    "--check-links", str(SNAPSHOT_CONFIGS["latest"]["depth"]),
                    "--check-stateroots", str(SNAPSHOT_CONFIGS["latest"]["state_roots"])
                ])
            args.append(snapshot_path)
            subprocess.run(
                args,
                env={
                    "FULLNODE_API_INFO": get_api_info()
                },
                capture_output=True, text=True, check=True
            )
    except subprocess.CalledProcessError as err:
        logger.error(f"❌ Error validating snapshot on forest: {err.stderr}", exc_info=True)
        return False

    return True


def validate_snapshot(snapshot_path: str) -> bool:
    """Wrapper around upload that also produces RabbitMQ status messages."""
    with metrics.track_processing():
        if not forest_validate(snapshot_path):
            return False
        # if not lotus_validate(snapshot_path):
        #     return False

    return True


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
        RabbitQueue.UPLOAD,
        RabbitQueue.VALIDATE,
        RabbitQueue.VALIDATE_FAILED
    ])
    rabbit_setup.close()
    while True:
        for queue in [RabbitQueue.UPLOAD]:
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
    metrics = Metrics(port=METRICS_PORT)
    main()
