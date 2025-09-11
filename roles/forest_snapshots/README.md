## Role: forest_snapshots

Provision a Forest archive node and a snapshot pipeline using Docker Compose. This role can build historic and latest snapshots, validate them, upload to object storage (e.g., Cloudflare R2/S3), publish metrics/logs, and optionally run compute-state jobs. It also wires up RabbitMQ for job coordination and Grafana Alloy for metrics/logs shipping.

This role is part of the `chainsafe.filecoin` collection.

---

### Components
- Forest archive node container
- Optional jobs:
  - compute-state
  - build-snapshots (historic and latest)
  - validate-snapshots
  - upload-snapshots
- RabbitMQ (optional, enabled by default)
- Grafana Alloy for metrics/logs (optional, enabled by default)

### Requirements
- Linux host with Docker and Docker Compose v2
- Sufficient disk throughput and space for archive data and snapshots
- Ansible collections:
  - `community.docker (>=4.0.0,<5.0.0)`
  - `community.general (>=10.0.0,<11.0.0)`
  - `ansible.posix (>=1.0.0,<2.0.0)`

Ensure Docker is installed (e.g., via `chainsafe.filecoin.install_packages`).

### Default Variables
Defined in `defaults/main.yml` (excerpt):

```yaml
# R2 / Object Storage
r2:
  # S3-compatible endpoint for Cloudflare R2 or other object storage.
  endpoint_url: "https://2238a825c5aca59233eab1f221f7aefb.r2.cloudflarestorage.com"
  # Access key ID used for uploads.
  access_key_id: ""
  # Secret key used for uploads.
  secret_access_key: ""
  # Bucket name where snapshots are stored.
  bucket_name: "forest-archive"

# External Disk / Filesystem
external_disk:
  # List or device glob for RAID members (if any). Leave empty for single disk.
  raid_devices: []
  # RAID device name when `raid_devices` is used.
  raid_device_name: md0
  # RAID level (e.g., 0/1/5). Only used when `raid_devices` is set
  raid_level: 0
  # Mount point for the data disk that will hold archive and snapshots.
  mount_point: /data
  # Filesystem type used when formatting the disk or array.
  filesystem_type: ext4

# Docker Compose
docker_compose:
  # Path where Compose files and state are placed.
  project_path: "/home/{{ ansible_user }}/forest-{{ forest.node_type }}-{{ network }}"

# Filecoin network identifier (e.g., `mainnet`, `calibnet`). Used in names and configs.
network: "testnet"

# Forest configuration
forest:
  image:
    # Container image repository for Forest.
    name: ghcr.io/chainsafe/forest
    # Container image tag.
    tag: latest-fat
  # Node type descriptor used in naming; archive nodes keep full chain state.
  node_type: "archive"
  # Application log verbosity (debug, info, warning, error).
  log_level: "info" # debug, info, warning, error
  # Rust log filter passed to the process (debug, info, warn, error, off).
  rust_log_level: "warn" # debug, info, warn, error, off
  # Enables F3 sidecar FFI if required.
  f3_enabled_sidecar: false
  # Target number of peers to connect to.
  target_peer_count: 5000
  # Extra CLI args for the Forest process; `--no-gc` recommended for snapshotters.
  container_extra_args:
    - "--no-gc"
  host:
    # Forest config directory on host.
    config_path: "/home/{{ ansible_user }}/forest/{{ network }}/config"
    # Forest data directory on host.
    data_path: "/data/forest"
    # Snapshot output directory on host.
    snapshot_path: "/data/snapshots/{{ network }}"
    # Helper scripts directory on host.
    scripts_path: "/home/{{ ansible_user }}/forest/{{ network }}/scripts"
  container:
    # Config directory inside container.
    config_path: "/home/forest/config"
    # Data directory inside container.
    data_path: "/home/forest/data"
    # Scripts directory inside container.
    scripts_path: "/scripts"
    # Snapshot output path inside container.
    snapshot_path: "/home/forest/snapshots"
    # Metrics/logs path inside container.
    metrics_path: "/data/metrics"
  compute:
    # Enable compute-state job service.
    enabled: false
    # Starting epoch for compute-state.
    start_epoch: 0
    # Batch size for compute-state processing.
    batch_size: 100
  build_snapshots_historic:
    # Enable historic snapshots builder.
    enabled: false
    # Starting epoch for historic snapshot generation.
    start_epoch: 0
    # Delay between historic snapshot runs in seconds.
    delay: "{{ 24 * 60 * 60 }}"
  build_snapshots_latest:
    # Enable periodic latest snapshot builder.
    enabled: false
    # Snapshot format/version for latest snapshots.
    format: "v1"
    # Delay between latest snapshot runs in seconds.
    delay: "{{ 6 * 60 * 60 }}"
  upload_snapshots:
    # Enable uploader service to push snapshots to object storage.
    enabled: false
  validate_snapshots:
    # Enable validator service to verify produced snapshots.
    enabled: false
  metrics:
    # Metrics port exposed by Forest.
    port: 6116
  # Whether to import a provided libp2p private key.
  import_libp2p_private_key: false
  # The libp2p private key material (handle securely).
  libp2p_private_key: ""

# RabbitMQ
rabbitmq:
  # Whether to deploy RabbitMQ alongside the pipeline.
  enabled: true
  #  RabbitMQ username.
  user: "guest"
  # RabbitMQ password.
  password: "password"
  # Host path for RabbitMQ data.
  data_path: "/data/rabbitmq/{{ network }}"

# # Grafana Alloy (Metrics/Logs Shipping)
grafana_alloy:
  # Whether to deploy Grafana Alloy sidecar.
  enabled: true
  # Host path for Alloy configs.
  config_path: "/home/{{ ansible_user }}/grafana-alloy/{{ network }}"
  # Grafana Alloy container image.
  image: "grafana/alloy:latest"
  # Grafana Cloud API key used for remote_write.
  api_key: "GRAFANA_CLOUD_API_KEY"
  metrics:
    # Grafana Cloud Prometheus endpoint.
    endpoint: "https://prometheus-prod-xx.grafana.net"
    # Prometheus instance/user ID.
    username: "GRAFANA_CLOUD_METRICS_USERNAME"
  logs:
    # Grafana Cloud Logs endpoint.
    endpoint: "https://logs-prod-xx.grafana.net"
    # Logs instance/user ID.
    username: "GRAFANA_CLOUD_LOGS_USERNAME"

# Slack Notifications
slack:
  # Bot token used to post notifications.
  token: "SLACK_TOKEN"
  # Default channel for notifications.
  channel: "#forest-dump"
```

Sensitive variables (R2 keys, Grafana credentials, Slack token) should be set via Ansible Vault or environment.

### Templates, Files and Compose
- Compose and env templates: `templates/docker-compose.yml.j2`, `templates/env.j2`
- Forest config and scripts: `templates/forest/*`
- Jobs artifacts: `files/*.py`, `templates/jobs/validate-snapshots.sh.j2`
- Monitoring config: `templates/monitoring/config.alloy.j2`

Compose `project_path` is `{{ docker_compose.project_path }}`; services are enabled/disabled via the `forest.*`/`rabbitmq.*`/`grafana_alloy.*` toggles above.

### Tasks Overview
Role tasks are organized as:
- `disks.yml`: Prepare and mount external disk (optional RAID) at `external_disk.mount_point`
- `forest-node.yml`: Configure Forest archive node directories, config, filter list, scripts
- `compose.yml`: Render compose files and bring up services
- `jobs.yml`: Configure and schedule snapshot/compute/upload/validate jobs
- `monitoring.yml`: Configure Grafana Alloy for metrics/logs shipping
- `rabbitmq.yml`: Deploy RabbitMQ (if enabled)
- `main.yml`: Orchestrates the above

### Handlers
Handlers restart components via Compose V2:
- `Restart forest`, `Restart compute-state`, `Restart build-snapshots`, `Restart validate-snapshots`, `Restart upload-snapshots`, `Restart grafana-alloy`, and `Restart all`.

### Usage
Example playbook enabling latest snapshots building and uploads to R2:

```yaml
---
- name: Forest snapshot pipeline
  hosts: snapshotters
  become: true
  vars:
    network: calibration
    forest:
      node_type: archive
      build_snapshots_latest:
        enabled: true
        format: v1
        delay: "{{ 6 * 60 * 60 }}"
      upload_snapshots:
        enabled: true
      validate_snapshots:
        enabled: true
    r2:
      endpoint_url: "https://<account-id>.r2.cloudflarestorage.com"
      bucket_name: forest-archive
      access_key_id: "{{ vault_r2_access_key_id }}"
      secret_access_key: "{{ vault_r2_secret_access_key }}"
    grafana_alloy:
      enabled: true
      api_key: "{{ vault_grafana_api_key }}"
      metrics:
        endpoint: "https://prometheus-prod-xx.grafana.net"
        username: "12345"
      logs:
        endpoint: "https://logs-prod-xx.grafana.net"
        username: "12345"
    slack:
      token: "{{ vault_slack_token }}"
      channel: "#forest-dump"
  roles:
    - chainsafe.filecoin.forest_snapshots
```

Example enabling historic snapshot build from a specific epoch:

```yaml
vars:
  forest:
    build_snapshots_historic:
      enabled: true
      start_epoch: 0
      delay: "{{ 24 * 60 * 60 }}"
```

### Operational Notes
- Ensure adequate IOPS and throughput on `external_disk.mount_point` for archive and snapshots.
- Forest container typically runs with `--no-gc` for snapshot-producing nodes.
- RabbitMQ is recommended when running multiple jobs/pipelines.
- Set `forest.target_peer_count` and logging levels to match environment needs.

### Troubleshooting
- Snapshots not uploaded: verify `r2.*` credentials and bucket permissions.
- Jobs not starting: check Compose service status and logs; ensure `enabled: true` for the specific job.
- Metrics/logs missing: confirm Grafana Alloy credentials and endpoints; check network egress.
- Disk full: monitor `forest.container.metrics_path` and snapshot output paths.

### License
See `LICENSE.md` at the collection root.

### Author
ChainSafe Systems
