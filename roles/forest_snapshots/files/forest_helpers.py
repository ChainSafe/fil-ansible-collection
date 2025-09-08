import json
import subprocess
from logger_setup import setup_logger

logger = setup_logger(__name__)


def get_genesis_timestamp(api_info: str) -> int:
    """Fetch genesis timestamp."""
    result = None
    try:
        result = subprocess.run(
            ["/usr/local/bin/forest-cli", "chain", "genesis"],
            env={
                "FULLNODE_API_INFO": api_info
            },
            capture_output=True, text=True, check=True)
        head_info = json.loads(result.stdout)
        return int(head_info["Blocks"][0]["Timestamp"])
    except subprocess.CalledProcessError:
        logger.error(f"Error fetching genesis timestamp: {result.stderr}")
    except BaseException as e:
        logger.error(f"Error fetching genesis timestamp: {e}")


def get_current_epoch(api_info: str) -> int:
    """Fetch current chain head epoch."""
    result = None
    try:
        result = subprocess.run(
            ["/usr/local/bin/forest-cli", "chain", "head", "--format", "json"],
            env={
                "FULLNODE_API_INFO": api_info
            },
            capture_output=True, text=True, check=True)
        head_info = json.loads(result.stdout)
        return int(head_info[0]["epoch"])
    except subprocess.CalledProcessError:
        logger.error(f"Error fetching genesis timestamp: {result.stderr}")
    except BaseException as err:
        logger.error(f"Error fetching current epoch: {err}")
