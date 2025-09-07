#!/usr/bin/env python3
import logging
import os
import socket
import sys
import time
import json
import subprocess

from rabbitmq import RabbitMQClient
from metrics import Metrics
from slack import slack_notify

logger = logging.getLogger("compute-state")
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
DEFAULT_START_EPOCH = int(os.getenv("DEFAULT_START_EPOCH", "0"))
COMPUTE_BATCH_SIZE = int(os.getenv("COMPUTE_BATCH_SIZE", "100"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
SECONDS_PER_EPOCH = 30

# RabbitMQ queues
COMPUTE_QUEUE = "compute"

# Initialize queue
rabbit = RabbitMQClient()
rabbit.connect()
rabbit.setup([COMPUTE_QUEUE])

# Initialize metrics
metrics = Metrics(logger, prefix=f"forest_compute_state_", port=METRICS_PORT)

# Forest connection
forest_ip = socket.gethostbyname(os.getenv("FOREST_HOST"))
with open(os.getenv("FOREST_TOKEN_PATH"), "r") as f:
    forest_token = f.read()
FULLNODE_API_INFO=f"{forest_token}:/ip4/{forest_ip}/tcp/2345/http"

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
    except subprocess.CalledProcessError as e:
        metrics.inc_failure()
        logger.error(f"Error fetching genesis timestamp: {result.stderr}")
    except Exception as e:
        metrics.inc_failure()
        logger.error(f"Error fetching current epoch: {e}")


def compute_state(epoch: int):
    """Compute state for a given epoch."""
    logger.info(f"Computing state for epoch {epoch}")
    try:
        with metrics.track_processing():
            proc = subprocess.Popen(
                [
                    "/usr/local/bin/forest-cli", "state", "compute",
                    "--epoch", str(epoch),
                    "--n-epochs", str(COMPUTE_BATCH_SIZE)
                ],
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
                logger.error(f"Epochs {epoch} to {epoch+COMPUTE_BATCH_SIZE} failed, retrying with per/epoch computation...")
                with metrics.track_processing():
                    for epoch in range(epoch, epoch+COMPUTE_BATCH_SIZE):
                        proc = subprocess.Popen(
                            [
                                "forest-cli", "state", "compute",
                                "--epoch", str(epoch),
                            ],
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
                            metrics.inc_failure()
                            slack_notify(f"Epochs {epoch} compute failed", "failed")
                            time.sleep(60)
                            raise Exception("Epochs compute failed")
            else:
                logger.info(f"Epochs {epoch} to {epoch+COMPUTE_BATCH_SIZE} finished")
                metrics.inc_success()
                rabbit.produce(COMPUTE_QUEUE, str(epoch + COMPUTE_BATCH_SIZE))
    except Exception as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")

def main():
    historic_start_epoch = 0
    current_epoch = get_current_epoch()
    epochs_left = current_epoch - historic_start_epoch
    # Diff snapshots, lite snapshots and full snapshots
    metrics.set_total(epochs_left)

    delivery_tag, computed_epoch = rabbit.consume(COMPUTE_QUEUE, latest=True)
    historic_start_epoch = DEFAULT_START_EPOCH

    if not delivery_tag:
        logger.warning("No processed epochs in queue. Starting over...")
    else:
        historic_start_epoch = int(computed_epoch)
    historic_start_epoch = (historic_start_epoch // COMPUTE_BATCH_SIZE) * COMPUTE_BATCH_SIZE
    if current_epoch > historic_start_epoch:
        for epoch in range(historic_start_epoch, current_epoch, COMPUTE_BATCH_SIZE):
            compute_state(epoch)
            time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    finally:
        rabbit.close()
