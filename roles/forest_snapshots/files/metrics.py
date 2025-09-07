from prometheus_client import Counter, Histogram, Gauge, start_http_server

class Metrics:
    def __init__(self, logger, prefix="snapshot_", port=8000):
        self.logger = logger

        # Counters
        self.success_counter = Counter(f"{prefix}_success_total", "Total successfully processed snapshots")
        self.failure_counter = Counter(f"{prefix}_failure_total", "Total failed processed snapshots")

        # Progress gauge
        self.total_messages = Gauge(f"{prefix}_total", "Total snapshots to process")
        self.progress = Gauge(f"{prefix}_progress", "Progress: processed snapshots / total")

        # Durations
        self.download_duration = Histogram(f"{prefix}_download_duration_seconds",
                                           "Time spent downloading snapshots")
        self.upload_duration = Histogram(f"{prefix}_upload_duration_seconds", "Time spent uploading snapshots")
        self.processing_duration = Histogram(f"{prefix}_processing_duration_seconds",
                                             "Total processing time per snapshot")

        # Start Prometheus HTTP metrics server
        start_http_server(port)

    def set_total(self, value: int):
        self.total_messages.set(value)
        self.success_counter.reset()
        self.failure_counter.reset()
        self.update_progress()

    # noinspection PyProtectedMember
    def update_progress(self):
        processed = self.success_counter._value.get() + self.failure_counter._value.get()
        total = self.total_messages._value.get()
        if total > 0:
            self.progress.set(processed / total)

    def inc_success(self):
        self.success_counter.inc()
        self.update_progress()

    def inc_failure(self):
        self.failure_counter.inc()
        self.update_progress()


    # Context managers for duration tracking
    def track_download(self):
        self.logger.debug("Starting download duration tracking")
        return self.download_duration.time()

    def track_upload(self):
        self.logger.debug("Starting upload duration tracking")
        return self.upload_duration.time()

    def track_processing(self):
        self.logger.debug("Starting processing duration tracking")
        return self.processing_duration.time()
