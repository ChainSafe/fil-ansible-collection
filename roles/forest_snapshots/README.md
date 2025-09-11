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
r2:
  endpoint_url: "https://2238a825c5aca59233eab1f221f7aefb.r2.cloudflarestorage.com"
  access_key_id: ""
  secret_access_key: ""
  bucket_name: "forest-archive"

external_disk:
  raid_devices: ""
  raid_device_name: md0
  raid_level: 0
  mount_point: /data
  filesystem_type: ext4

docker_compose:
  project_path: "/home/{{ ansible_user }}/forest-{{ forest.node_type }}-{{ network }}"

network: "testnet"

forest:
  image:
    name: ghcr.io/chainsafe/forest
    tag: latest-fat
  node_type: "archive"
  log_level: "info"        # debug, info, warning, error
  rust_log_level: "warn"   # debug, info, warn, error, off
  f3_enabled_sidecar: false
  target_peer_count: 5000
  container_extra_args:
    - "--no-gc"
  host:
    config_path: "/home/{{ ansible_user }}/forest/{{ network }}/config"
    data_path: "/data/forest"
    snapshot_path: "/data/snapshots/{{ network }}"
    scripts_path: "/home/{{ ansible_user }}/forest/{{ network }}/scripts"
  container:
    config_path: "/home/forest/config"
    data_path: "/home/forest/data"
    scripts_path: "/scripts"
    snapshot_path: "/home/forest/snapshots"
    metrics_path: "/data/metrics"
  compute:
    enabled: false
    start_epoch: 0
    batch_size: 100
  build_snapshots_historic:
    enabled: false
    start_epoch: 0
    delay: "{{ 24 * 60 * 60 }}"
  build_snapshots_latest:
    enabled: false
    format: "v1"
    delay: "{{ 6 * 60 * 60 }}"
  upload_snapshots:
    enabled: false
  validate_snapshots:
    enabled: false
  metrics:
    port: 6116
  import_libp2p_private_key: false
  libp2p_private_key: ""

rabbitmq:
  enabled: true
  user: "guest"
  password: "password"
  data_path: "/data/rabbitmq/{{ network }}"

grafana_alloy:
  enabled: true
  config_path: "/home/{{ ansible_user }}/grafana-alloy/{{ network }}"
  image: "grafana/alloy:latest"
  api_key: "GRAFANA_CLOUD_API_KEY"
  metrics:
    endpoint: "https://prometheus-prod-xx.grafana.net"
    username: "GRAFANA_CLOUD_METRICS_USERNAME"
  logs:
    endpoint: "https://logs-prod-xx.grafana.net"
    username: "GRAFANA_CLOUD_LOGS_USERNAME"

slack:
  token: "SLACK_TOKEN"
  channel: "#forest-dump"
```

Sensitive variables (R2 keys, Grafana credentials, Slack token) should be set via Ansible Vault or environment.

### Variables reference
Below is a complete reference of all variables defined in `defaults/main.yml`.

#### R2 / Object Storage
- `r2.endpoint_url` (string, default: `https://2238a825c5aca59233eab1f221f7aefb.r2.cloudflarestorage.com`): S3-compatible endpoint for Cloudflare R2 or other object storage.
- `r2.access_key_id` (string, default: empty): Access key ID used for uploads.
- `r2.secret_access_key` (string, default: empty): Secret key used for uploads.
- `r2.bucket_name` (string, default: `forest-archive`): Bucket name where snapshots are stored.

#### External Disk / Filesystem
- `external_disk.raid_devices` (string, default: empty): Space-separated list or device glob for RAID members (if any). Leave empty for single disk.
- `external_disk.raid_device_name` (string, default: `md0`): mdadm RAID device name when `raid_devices` is used.
- `external_disk.raid_level` (integer, default: `0`): RAID level (e.g., 0/1/5). Only used when `raid_devices` is set.
- `external_disk.mount_point` (string, default: `/data`): Mount point for the data disk that will hold archive and snapshots.
- `external_disk.filesystem_type` (string, default: `ext4`): Filesystem type used when formatting the disk or array.

#### Docker Compose
- `docker_compose.project_path` (string, default: `/home/{{ ansible_user }}/forest-{{ forest.node_type }}-{{ network }}`): Path where Compose files and state are placed.

#### Network
- `network` (string, default: `testnet`): Filecoin network identifier (e.g., `mainnet`, `calibration`). Used in names and configs.

#### Forest Node
- `forest.image.name` (string, default: `ghcr.io/chainsafe/forest`): Container image repository for Forest.
- `forest.image.tag` (string, default: `latest-fat`): Container image tag.
- `forest.node_type` (string, default: `archive`): Node type descriptor used in naming; archive nodes keep full chain state.
- `forest.log_level` (string, default: `info`): Application log verbosity (debug, info, warning, error).
- `forest.rust_log_level` (string, default: `warn`): Rust log filter passed to the process (debug, info, warn, error, off).
- `forest.f3_enabled_sidecar` (boolean, default: `false`): Enables F3 sidecar FFI if required.
- `forest.target_peer_count` (integer, default: `5000`): Target number of peers to connect to.
- `forest.container_extra_args` (list[string], default: `["--no-gc"]`): Extra CLI args for the Forest process; `--no-gc` recommended for snapshotters.

Paths on the host:
- `forest.host.config_path` (string, default: `/home/{{ ansible_user }}/forest/{{ network }}/config`): Forest config directory on host.
- `forest.host.data_path` (string, default: `/data/forest`): Forest data directory on host.
- `forest.host.snapshot_path` (string, default: `/data/snapshots/{{ network }}`): Snapshot output directory on host.
- `forest.host.scripts_path` (string, default: `/home/{{ ansible_user }}/forest/{{ network }}/scripts`): Helper scripts directory on host.

Paths in the container:
- `forest.container.config_path` (string, default: `/home/forest/config`): Config directory inside container.
- `forest.container.data_path` (string, default: `/home/forest/data`): Data directory inside container.
- `forest.container.scripts_path` (string, default: `/scripts`): Scripts directory inside container.
- `forest.container.snapshot_path` (string, default: `/home/forest/snapshots`): Snapshot output path inside container.
- `forest.container.metrics_path` (string, default: `/data/metrics`): Metrics/logs path inside container.

Jobs toggles and parameters:
- `forest.compute.enabled` (boolean, default: `false`): Enable compute-state job service.
- `forest.compute.start_epoch` (integer, default: `0`): Starting epoch for compute-state.
- `forest.compute.batch_size` (integer, default: `100`): Batch size for compute-state processing.
- `forest.build_snapshots_historic.enabled` (boolean, default: `false`): Enable historic snapshots builder.
- `forest.build_snapshots_historic.start_epoch` (integer, default: `0`): Starting epoch for historic snapshot generation.
- `forest.build_snapshots_historic.delay` (Jinja/integer, default: `{{ 24 * 60 * 60 }}`): Delay between historic snapshot runs in seconds.
- `forest.build_snapshots_latest.enabled` (boolean, default: `false`): Enable periodic latest snapshot builder.
- `forest.build_snapshots_latest.format` (string, default: `v1`): Snapshot format/version for latest snapshots.
- `forest.build_snapshots_latest.delay` (Jinja/integer, default: `{{ 6 * 60 * 60 }}`): Delay between latest snapshot runs in seconds.
- `forest.upload_snapshots.enabled` (boolean, default: `false`): Enable uploader service to push snapshots to object storage.
- `forest.validate_snapshots.enabled` (boolean, default: `false`): Enable validator service to verify produced snapshots.
- `forest.metrics.port` (integer, default: `6116`): Metrics port exposed by Forest.
- `forest.import_libp2p_private_key` (boolean, default: `false`): Whether to import a provided libp2p private key.
- `forest.libp2p_private_key` (string, default: empty): The libp2p private key material (handle securely).

#### RabbitMQ
- `rabbitmq.enabled` (boolean, default: `true`): Whether to deploy RabbitMQ alongside the pipeline.
- `rabbitmq.user` (string, default: `guest`): RabbitMQ username.
- `rabbitmq.password` (string, default: `password`): RabbitMQ password.
- `rabbitmq.data_path` (string, default: `/data/rabbitmq/{{ network }}`): Host path for RabbitMQ data.

#### Grafana Alloy (Metrics/Logs Shipping)
- `grafana_alloy.enabled` (boolean, default: `true`): Whether to deploy Grafana Alloy sidecar.
- `grafana_alloy.config_path` (string, default: `/home/{{ ansible_user }}/grafana-alloy/{{ network }}`): Host path for Alloy configs.
- `grafana_alloy.image` (string, default: `grafana/alloy:latest`): Alloy container image.
- `grafana_alloy.api_key` (string, default: `GRAFANA_CLOUD_API_KEY`): Grafana Cloud API key used for remote_write.
- `grafana_alloy.metrics.endpoint` (string, default: `https://prometheus-prod-xx.grafana.net`): Grafana Cloud Prometheus endpoint.
- `grafana_alloy.metrics.username` (string, default: `GRAFANA_CLOUD_METRICS_USERNAME`): Prometheus instance/user ID.
- `grafana_alloy.logs.endpoint` (string, default: `https://logs-prod-xx.grafana.net`): Grafana Cloud Logs endpoint.
- `grafana_alloy.logs.username` (string, default: `GRAFANA_CLOUD_LOGS_USERNAME`): Logs instance/user ID.

#### Slack Notifications
- `slack.token` (string, default: `SLACK_TOKEN`): Bot token used to post notifications.
- `slack.channel` (string, default: `#forest-dump`): Default channel for notifications.

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
