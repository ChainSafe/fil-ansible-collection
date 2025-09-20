import os
# import re
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from logger_setup import setup_logger

logger = setup_logger(os.path.basename(__file__))

SLACK_TOKEN = os.getenv("SLACK_TOKEN")  # Bot token
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#forest-dump")  # Channel ID or name, e.g., "#alerts"

slack_client = WebClient(token=SLACK_TOKEN)


def slack_notify(message: str, status: str = "info", thread_ts: str = None) -> Optional[str]:
    """
    Send a message to Slack.

    :param message: Message text
    :param status: "info", "success", "failed" for the emoji prefix
    :param thread_ts: Thread timestamp to reply to
    """
    emoji = {
        "info": ":information_source:",
        "success": ":white_check_mark:",
        "failed": ":x:"
    }.get(status, ":information_source:")

    forest = {
        "info": ":evergreen_tree:",
        "success": ":deciduous_tree::evergreen_tree:",
        "failed": ":fire::evergreen_tree::fire:"
    }.get(status, ":evergreen_tree:")

    text = f"{emoji} {message} {forest}"
    logger.debug(f"Slack notification sending: {text}")
    try:
        # Starting a new thread
        if thread_ts is None:
            response = slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=text)
            return response["ts"]
        else:
            # head_message = slack_client.conversations_history(
            #     channel=SLACK_CHANNEL,
            #     latest=thread_ts,
            #     limit=1,
            #     inclusive=True
            # )["messages"][0]["text"]
            # new_text = re.sub(r":\w+?:", emoji, head_message, count=1)
            # slack_client.chat_update(
            #     channel=SLACK_CHANNEL,
            #     ts=thread_ts,
            #     text=f"{new_text}{forest}"
            # )
            slack_client.chat_postMessage(channel=SLACK_CHANNEL, text=text, thread_ts=thread_ts)

    except SlackApiError as e:
        logger.error(f"Error sending Slack message: {e.response['error']}")
