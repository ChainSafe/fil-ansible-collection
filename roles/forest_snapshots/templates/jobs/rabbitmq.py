#!/usr/bin/env python3
import pika
import os
import sys
import json

RABBIT_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBIT_USER = os.getenv("RABBITMQ_USER", "user")
RABBIT_PASS = os.getenv("RABBITMQ_PASS", "password")

class RabbitMQClient:
    def __init__(self):
        self.connection = None
        self.channel = None

    def setup(self, queue):
        # Exchanges
        self.channel.exchange_declare(exchange=queue, exchange_type="fanout", durable=True)
        self.channel.exchange_declare(exchange=f"{queue}-failed", durable=True)
        # History queue
        self.channel.queue_declare(queue=queue, durable=True)
        self.channel.queue_bind(exchange=queue, queue=queue)
        # Failed queue
        self.channel.queue_declare(queue=f"{queue}-failed", durable=True)
        self.channel.queue_bind(exchange=f"{queue}-failed", queue=f"{queue}-failed")
        # Latest status queue
        self.channel.queue_declare(queue=f"{queue}-latest", durable=True,arguments={'x-max-length': 1, "x-overflow": "drop-head"})
        self.channel.queue_bind(exchange=queue, queue=f"{queue}-latest")

    def connect(self):
        try:
            credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASS)
            self.connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBIT_HOST, credentials=credentials)
            )
            self.channel = self.connection.channel()
        except pika.exceptions.AMQPError as e:
            print(f"Failed to connect to RabbitMQ: {e}")
            sys.exit(1)

    def close(self):
        if self.channel:
            self.channel.close()
        if self.connection:
            self.connection.close()

    def produce(self, exchange, message):
        try:
            self.channel.basic_publish(
                exchange=exchange,
                routing_key=exchange,
                body=message,
                properties=pika.BasicProperties(
                    delivery_mode=2  # make message persistent
                )
            )
        except pika.exceptions.AMQPError as e:
            print(f"Failed to produce message: {e}")
            sys.exit(1)

    def consume(self, queue):
        try:
            method_frame, header_frame, body = self.channel.basic_get(queue=queue, auto_ack=False)
            if method_frame:
                try:
                    message = body.decode()
                    print(json.dumps({
                        "delivery_tag": method_frame.delivery_tag,
                        "message": message
                    }))
                except json.JSONDecodeError:
                    print("Invalid JSON message received")
                    self.reject(method_frame.delivery_tag, requeue=False)
                    return
            else:
                print("{}")  # No message
        except pika.exceptions.AMQPError as e:
            print(f"Failed to consume message: {e}")
            sys.exit(1)

    def ack(self, tag):
        try:
            self.channel.basic_ack(delivery_tag=int(tag))
            print(f"Acked message {tag}")
        except pika.exceptions.AMQPError as e:
            print(f"Failed to ack message: {e}")
            sys.exit(1)

    def reject(self, tag, requeue=True):
        try:
            self.channel.basic_reject(delivery_tag=int(tag), requeue=requeue)
            print(f"Rejected message {tag}, requeue={requeue}")
        except pika.exceptions.AMQPError as e:
            print(f"Failed to reject message: {e}")
            sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: rabbitmq.py [setup|produce|consume|ack|reject] [...options]")
        sys.exit(1)

    client = RabbitMQClient()
    try:
        client.connect()
        action = sys.argv[1]

        if action == "setup":
            if len(sys.argv) != 3:
                print(f"Wrong args: {sys.argv[2:]}\nUsage: rabbitmq.py setup <queue>")
                sys.exit(1)
            client.setup(sys.argv[2])
        elif action == "produce":
            if len(sys.argv) != 4:
                print(f"Wrong args: {sys.argv[2:]}\nUsage: rabbitmq.py produce <exchange> <message>")
                sys.exit(1)
            client.produce(sys.argv[2], sys.argv[3])
        elif action == "consume":
            if len(sys.argv) != 3:
                print(f"Wrong args: {sys.argv[2:]}\nUsage: rabbitmq.py consume <queue>")
                sys.exit(1)
            client.consume(sys.argv[2])
        elif action == "ack":
            if len(sys.argv) != 3:
                print(f"Wrong args: {sys.argv[2:]}\nUsage: rabbitmq.py ack <delivery_tag>")
                sys.exit(1)
            client.ack(sys.argv[2])
        elif action == "reject":
            if len(sys.argv) != 3:
                print(f"Wrong args: {sys.argv[2:]}\nUsage: rabbitmq.py reject <delivery_tag>")
                sys.exit(1)
            client.reject(sys.argv[2], requeue=True)
        else:
            print("Unknown action")
    finally:
        client.close()

if __name__ == "__main__":
    main()
