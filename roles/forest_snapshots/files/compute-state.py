import os
import socket
import time
import subprocess

from logger_setup import setup_logger
from forest_helpers import get_current_epoch
from rabbitmq import RabbitMQClient, RabbitQueue
from metrics import Metrics
from slack import slack_notify

logger = setup_logger(os.path.basename(__file__))

# Env variables
CHAIN = os.getenv("CHAIN", "testnet")
DEFAULT_START_EPOCH = int(os.getenv("DEFAULT_START_EPOCH", "0"))
COMPUTE_BATCH_SIZE = int(os.getenv("COMPUTE_BATCH_SIZE", "100"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

# Config
SECONDS_PER_EPOCH = 30

# Initialize queue
rabbit = RabbitMQClient()
rabbit.setup([RabbitQueue.COMPUTE])

# Initialize metrics
metrics = Metrics(prefix="forest_compute_state_", port=METRICS_PORT)

# Forest connection
forest_ip = socket.gethostbyname(os.getenv("FOREST_HOST"))
with open(os.getenv("FOREST_TOKEN_PATH"), "r") as f:
    forest_token = f.read()
FULLNODE_API_INFO = f"{forest_token}:/ip4/{forest_ip}/tcp/2345/http"


def compute_state(epoch: int):
    """Compute state for a given epoch."""
    logger.info(f"Computing state for epochs {epoch} - {epoch + COMPUTE_BATCH_SIZE}")
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
                logger.error(
                    f"Epochs {epoch} to {epoch + COMPUTE_BATCH_SIZE} failed, retrying with per/epoch computation...")
                with metrics.track_processing():
                    for epoch in range(epoch, epoch + COMPUTE_BATCH_SIZE):
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
                            # FIXME
                            logger.error(f"Epochs {epoch} compute failed. Sleeping for 10 minutes...")
                            time.sleep(600)
                            raise Exception("Epochs compute failed")
            else:
                logger.info(f"Epochs {epoch} to {epoch + COMPUTE_BATCH_SIZE} finished")
                metrics.inc_success()
                rabbit.produce(RabbitQueue.COMPUTE, str(epoch + COMPUTE_BATCH_SIZE))
    except Exception as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")


def main():
    historic_start_epoch = 0
    current_epoch = get_current_epoch(FULLNODE_API_INFO)
    epochs_left = current_epoch - historic_start_epoch
    # Diff snapshots, lite snapshots and full snapshots
    metrics.set_total(epochs_left)

    delivery_tag, computed_epoch = rabbit.consume(RabbitQueue.COMPUTE, latest=True)
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
