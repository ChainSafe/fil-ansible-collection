import os

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from logger_setup import setup_logger

logger = setup_logger(__name__)

SLACK_TOKEN = os.getenv("SLACK_TOKEN")  # Bot token
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#forest-dump")  # Channel ID or name, e.g., "#alerts"

slack_client = WebClient(token=SLACK_TOKEN)


def slack_notify(message: str, status: str = "info"):
    """
    Send a message to Slack.

    :param message: Message text
    :param status: "info", "success", "failed" for the emoji prefix
    """
    emoji = {
        "info": ":information_source:",
        "success": ":white_check_mark:",
        "failed": ":x:"
    }.get(status, ":information_source:")

    forest = {
        "info": ":evergreen_tree:",
        "success": ":evergreen_tree::deciduous_tree::evergreen_tree:",
        "failed": ":fire::evergreen_tree::fire:"
    }.get(status, ":evergreen_tree:")

    text = f"{emoji} {message} {forest}"

    try:
        slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=text)
        logger.debug(f"Slack notification sent: {text}")
    except SlackApiError as e:
        logger.error(f"Error sending Slack message: {e.response['error']}")
