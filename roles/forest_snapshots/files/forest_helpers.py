import json
import os
import socket
import subprocess

from logger_setup import setup_logger

logger = setup_logger(os.path.basename(__file__))


def get_api_info() -> str:
    forest_ip = socket.gethostbyname(os.getenv("FOREST_HOST"))
    with open(os.getenv("FOREST_TOKEN_PATH"), "r") as f:
        forest_token = f.read()
    return f"{forest_token}:/ip4/{forest_ip}/tcp/2345/http"


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
    try:
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
    try:
        result = subprocess.run(
            ["/usr/local/bin/forest-cli", "chain", "head", "--format", "json"],
            env={
                "FULLNODE_API_INFO": get_api_info()
            },
            capture_output=True, text=True, check=True)
        head_info = json.loads(result.stdout)
        return int(head_info[0]["epoch"])
    except subprocess.CalledProcessError as err:
        logger.error(f"Error fetching genesis timestamp: {err.stderr}")
        raise
    except BaseException as err:
        logger.error(f"Error fetching current epoch: {err}")
        raise
