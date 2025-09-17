import json
import os
import socket
import subprocess
import time

from logger_setup import setup_logger

logger = setup_logger(os.path.basename(__file__))

SNAPSHOT_CONFIGS = {
    "lite": {
        "depth": 30000,
        "state_roots": 900,
        "folder": "lite",
    },
    "diff": {
        "depth": 3000,
        "state_roots": 3000,
        "folder": "diff",
    },
    "latest": {
        "depth": 2000,
        "state_roots": 2000,
        "folder": "latest",
    },
}


def get_api_info() -> str:
    forest_ip = socket.gethostbyname(os.getenv("FOREST_HOST"))
    forest_rpc_port = os.getenv("FOREST_RPC_PORT")
    with open(os.getenv("FOREST_TOKEN_PATH"), "r") as f:
        forest_token = f.read()
    rpc_api_info = f"{forest_token}:/ip4/{forest_ip}/tcp/{forest_rpc_port}/http"
    while True:
        try:
            result = subprocess.run(
                ["/usr/local/bin/forest-cli", "wait-api"],
                env={
                    "FULLNODE_API_INFO": rpc_api_info
                },
                capture_output=True, text=True, check=True,
                timeout=60
            )
            if result.returncode == 0:
                break
        except subprocess.CalledProcessError as err:
            logger.error(f"Error Getting API status, wait 10 sec: {err.stderr}", exc_info=True)
            time.sleep(10)

    return rpc_api_info


def secs_to_dhms(seconds):
    """Convert seconds to human-readable dhms."""
    d, rem = divmod(seconds, 60*60*24)
    h, rem = divmod(rem, 60*60)
    m, s = divmod(rem, 60)
    result = f"{m}m {int(s)}s"
    if h > 0:
        result = f"{h}h {result}"
    if d > 0:
        result = f"{d}d {result}"
    return result


def wait_for_f3():
    """Wait for f3 status to be ready."""
    logger.debug("Waiting for f3 to be ready")
    while True:
        try:
            result = subprocess.run(
                ["/usr/local/bin/forest-cli", "f3", "ready", "--wait"],
                env={
                    "FULLNODE_API_INFO": get_api_info()
                },
                capture_output=True, text=True, check=True
            )
            if result.returncode == 0:
                break
        except subprocess.CalledProcessError as err:
            logger.error(f"Error Getting f3 status, wait 10 sec: {err.stderr}", exc_info=True)
            time.sleep(10)


def wait_for_sync():
    """Wait for sync to complete."""
    logger.debug("Wait for instance sync")
    while True:
        try:
            result = subprocess.run(
                ["/usr/local/bin/forest-cli", "sync", "wait"],
                env={
                    "FULLNODE_API_INFO": get_api_info()
                },
                capture_output=True, text=True, check=True
            )
            if result.returncode == 0:
                break
        except subprocess.CalledProcessError as err:
            logger.error(f"Error Getting sync status, wait 10 sec: {err.stderr}", exc_info=True)
            time.sleep(10)


def get_genesis_timestamp() -> int:
    """Fetch genesis timestamp."""
    logger.debug("Fetch genesis timestamp")
    try:
        wait_for_sync()
        result = subprocess.run(
            ["/usr/local/bin/forest-cli", "chain", "genesis"],
            env={
                "FULLNODE_API_INFO": get_api_info()
            },
            capture_output=True, text=True, check=True
        )
        head_info = json.loads(result.stdout)
        return int(head_info["Blocks"][0]["Timestamp"])
    except subprocess.CalledProcessError as err:
        logger.error(f"Error fetching genesis timestamp: {err.stderr}", exc_info=True)
        raise
    except BaseException as e:
        logger.error(f"Error fetching genesis timestamp: {e}")
        raise


def get_current_epoch() -> int:
    """Fetch current chain head epoch."""
    logger.debug("Fetch current epoch")
    try:
        args = ["/usr/local/bin/forest-cli", "chain", "head", "--format", "json"]
        api_info = get_api_info()
        logger.debug(f"Running command: {' '.join(args)} with FULLNODE_API_INFO='{api_info}'")
        result = subprocess.run(
            args=args,
            env={
                "FULLNODE_API_INFO": api_info
            },
            capture_output=True,
            text=True,
            check=True
        )
        head_info = json.loads(result.stdout)
        return int(head_info[0]["epoch"])
    except subprocess.CalledProcessError as err:
        logger.error(f"Error fetching genesis timestamp: {err.stderr}")
        raise
    except BaseException as err:
        logger.error(f"Error fetching current epoch: {err}")
        raise
