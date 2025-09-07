#!/usr/bin/env python3
import pika
import logging
import os
from typing import Optional, Tuple

RABBIT_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBIT_USER = os.getenv("RABBITMQ_USER", "user")
RABBIT_PASS = os.getenv("RABBITMQ_PASS", "password")

logger = logging.getLogger(__name__)


class RabbitMQClient:
    def __init__(self):
        self.connection = None
        self.channel = None

    def __enter__(self):
        """Allow usage with `with RabbitMQClient() as rabbit`"""
        if not self.connection or self.connection.is_closed:
            self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        except Exception as e:
            logger.warning("Error during RabbitMQ close: %s", e)

    def _ensure_open(self):
        """Ensure connection/channel are available and open."""
        if not self.connection or self.connection.is_closed:
            raise RuntimeError("RabbitMQ connection is not open. Call connect() first.")
        if not self.channel or self.channel.is_closed:
            raise RuntimeError("RabbitMQ channel is not open. Call connect() first.")

    def connect(self):
        """Connect to RabbitMQ and open a channel."""
        try:
            credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASS)
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBIT_HOST,
                    credentials=credentials,
                    heartbeat=600,
                    blocked_connection_timeout=600,
                    connection_attempts=5,
                    retry_delay=2.0,
                )
            )
            self.channel = self.connection.channel()
        except pika.exceptions.AMQPError as e:
            raise RuntimeError(f"Failed to connect to RabbitMQ: {e}")

    def close(self):
        """Close channel + connection."""
        try:
            if self.channel and not self.channel.is_closed:
                self.channel.close()
        except Exception as e:
            logger.debug("Ignoring channel close error: %s", e)
        finally:
            self.channel = None
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            logger.debug("Ignoring connection close error: %s", e)
        finally:
            self.connection = None

    def setup(self, queues: list[str] = None):
        """Create exchanges, queues and bindings."""
        self._ensure_open()
        for queue in queues:
            queue_x = queue
            queue_head = f"{queue}-head"
            queue_dlx = f"{queue}.dlx"
            queue_dlq = f"{queue}.dlq"

            # Main queue
            self.channel.exchange_declare(exchange=queue_x, exchange_type="fanout", durable=True)
            self.channel.queue_declare(
                queue=queue, durable=True,
                arguments={"x-dead-letter-exchange": f"{queue}.dlx"}
            )
            self.channel.queue_bind(exchange=queue, queue=queue)

            # Latest status queue
            self.channel.queue_declare(
                queue=queue_head, durable=True,
                arguments={'x-max-length': 1, "x-overflow": "drop-head"}
            )
            self.channel.queue_bind(exchange=queue_x, queue=queue_head)

            # DLQ
            self.channel.exchange_declare(exchange=queue_dlx, exchange_type="fanout", durable=True)
            self.channel.queue_declare(queue=queue_dlq, durable=True)
            self.channel.queue_bind(exchange=queue_dlx, queue=queue_dlq)

    def produce(self, exchange: str, message: str):
        """Publish a message to an exchange."""
        self._ensure_open()
        try:
            self.channel.basic_publish(
                exchange=exchange,
                routing_key=exchange,
                body=message,
                properties=pika.BasicProperties(delivery_mode=2)  # make persistent
            )
        except pika.exceptions.AMQPError as e:
            raise RuntimeError(f"Failed to produce message: {e}")

    def consume(self, queue: str, latest: bool = False, decode: bool = True) -> Tuple[Optional[int], Optional[str]]:
        """Fetch one message from a queue. Returns (delivery_tag, body) or (None, None)."""
        self._ensure_open()

        try:
            method_frame, header_frame, body = self.channel.basic_get(
                queue=(f"{queue}-head" if latest else queue), auto_ack=False
            )
            if method_frame:
                if decode:
                    return method_frame.delivery_tag, body.decode("utf-8")
                return method_frame.delivery_tag, body  # bytes
            else:
                return None, None
        except pika.exceptions.AMQPError as e:
            raise RuntimeError(f"Failed to consume message: {e}")

    def ack(self, tag: int):
        """Acknowledge a message."""
        self._ensure_open()
        try:
            self.channel.basic_ack(delivery_tag=int(tag))
        except pika.exceptions.AMQPError as e:
            raise RuntimeError(f"Failed to ack message: {e}")

    def reject(self, tag: int, requeue: bool = True):
        """Reject a message, requeuing it."""
        self._ensure_open()
        try:
            self.channel.basic_reject(delivery_tag=int(tag), requeue=requeue)
        except pika.exceptions.AMQPError as e:
            raise RuntimeError(f"Failed to reject message: {e}")

    def get_queue_size(self, queue: str) -> int:
        """Get the size of a queue."""
        self._ensure_open()
        try:
            queue_size = self.channel.queue_declare(queue=queue, passive=True).method.message_count
            return queue_size
        except pika.exceptions.AMQPError as e:
            raise RuntimeError(f"Failed to reject message: {e}")
