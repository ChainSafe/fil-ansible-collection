import os
import subprocess
import time

from forest_helpers import get_api_info, get_current_epoch, secs_to_dhms
from logger_setup import setup_logger
from metrics import Metrics
from rabbitmq import RabbitMQClient, RabbitQueue
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
rabbit_setup = RabbitMQClient()
rabbit_setup.setup([RabbitQueue.COMPUTE])
rabbit_setup.close()

# Initialize metrics
metrics = Metrics(prefix="forest_compute_state_", port=METRICS_PORT)


def compute_state(epoch: int, rabbit: RabbitMQClient):
    """Compute state for a given epoch."""
    logger.info(f"Computing state for epochs {epoch} - {epoch + COMPUTE_BATCH_SIZE}")
    start = time.time()
    try:
        with metrics.track_processing():
            proc = subprocess.Popen(
                [
                    "/usr/local/bin/forest-cli", "state", "compute",
                    "--epoch", str(epoch - 1),
                    "--n-epochs", str(COMPUTE_BATCH_SIZE)
                ],
                env={
                    "FULLNODE_API_INFO": get_api_info(),
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
                            "/usr/local/bin/forest-cli", "state", "compute",
                            "--epoch", str(epoch),
                        ],
                        env={
                            "FULLNODE_API_INFO": get_api_info()
                        },
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                    )
                    for line in proc.stdout:
                        logger.debug(line.rstrip())
                    return_code = proc.wait()
                    if return_code != 0:
                        metrics.inc_failure()
                        slack_notify(f"Epochs {epoch} compute failed", "failed")
                        raise Exception("Epochs compute failed")
        else:
            metrics.inc_success()
            time_taken = time.time() - start
            progress = metrics.get_progress()
            if progress > 0:
                time_estimate = secs_to_dhms(int(time_taken / metrics.get_progress()))
                logger.info(
                    f"Epochs {epoch} to {epoch + COMPUTE_BATCH_SIZE} finished.\nTook time: {secs_to_dhms(time_taken)}.\nTime left: {time_estimate}")
            rabbit.produce(RabbitQueue.COMPUTE, str(epoch + COMPUTE_BATCH_SIZE))
    except Exception as e:
        metrics.inc_failure()
        logger.error(f"Error running command: {e}")
        raise


def main():
    historic_start_epoch = DEFAULT_START_EPOCH
    while True:
        current_epoch = get_current_epoch()
        with RabbitMQClient() as rabbit:
            delivery_tag, computed_epoch = rabbit.consume(RabbitQueue.COMPUTE, latest=True)
        if not delivery_tag:
            logger.warning("No processed epochs in queue. Starting over...")
        else:
            historic_start_epoch = int(computed_epoch)

        historic_start_epoch = (historic_start_epoch // COMPUTE_BATCH_SIZE) * COMPUTE_BATCH_SIZE
        epochs_left = current_epoch - historic_start_epoch
        metrics.set_total(epochs_left // COMPUTE_BATCH_SIZE)
        if current_epoch > historic_start_epoch:
            for epoch in range(historic_start_epoch, current_epoch, COMPUTE_BATCH_SIZE):
                with RabbitMQClient() as rabbit:
                    try:
                        compute_state(epoch, rabbit)
                    except Exception as e:
                        logger.error(f"Error computing state on epoch {epoch}: {e}.  Sleeping for 10 minutes...")
                        time.sleep(600)
                        break
                time.sleep(10)


if __name__ == "__main__":
    main()
