## Role: forest_fullnode_docker_role

Deploy and manage a Forest Filecoin full node in a Docker container. The role creates required directories, renders configuration and helper scripts, ensures NTP is running, then starts the Forest container with sane defaults and logging.

This role is part of the `chainsafe.filecoin` collection.

---

### Requirements
- Linux host with Docker installed and running
- Ansible collections:
  - `community.docker (>=4.0.0,<5.0.0)`
  - `community.general (>=10.0.0,<11.0.0)`
  - `ansible.posix (>=1.0.0,<2.0.0)`

Ensure Docker is present beforehand (e.g., via `chainsafe.filecoin.install_packages`).

### Role Variables
Defined in `defaults/main.yml`:

```yaml
# Docker logging
docker_log_driver: json-file
docker_log_options:
  max-file: "5"
  max-size: 100m

# Filecoin network (e.g., mainnet, calibration, testnet)
network: "testnet"

forest:
  image:
    name: ghcr.io/chainsafe/forest
    tag: latest-fat
  node_type: fullnode
  container_extra_args: []
  rust_log_level: "warn"   # debug, info, warn, error, off
  f3_enabled_sidecar: false
  target_peer_count: 5000
  user: "{{ ansible_user }}"
  group: "{{ ansible_user }}"
  host:
    config_path: /home/{{ ansible_user }}/forest/config
    data_path: /home/{{ ansible_user }}/forest/forest_data
    scripts_path: /home/{{ ansible_user }}/forest/forest_data/script
  container:
    config_path: /home/forest
    data_path: /home/forest/forest_data
    scripts_path: /script
  rpc:
    enabled: true
    port: 2345
    host_port: 32345
  metrics:
    enabled: true
    port: 6116
    host_port: 36116
  import_libp2p_private_key: false
  libp2p_private_key: ""

# Optional memory limit for the container
# forest_memory_limit: "32g"
```

Notes:
- Container runs as `root` (0:0) to avoid permission issues on volumes.
- The container name format is `forest-<network>-<node_type>` and uses `network_mode: host`.

### Templates and Files
- `templates/config.toml.j2` → `{{ forest.host.config_path }}/config.toml`
- `templates/filter-list.txt` → `{{ forest.host.config_path }}/filter-list.txt`
- `templates/forest.sh.j2` → `{{ forest.host.scripts_path }}/forest.sh`

### Handlers
- `Restart_forest_docker`: restarts the container `docker restart "forest-{{ network }}-{{ forest.node_type }}"` when config/script changes.

### Tasks Overview
- Create directories for data, scripts, and config
- Render filter list and `config.toml`
- Ensure `ntp` package is installed and service is enabled/running
- Render `forest.sh` runner script
- Start or update the `forest` container with logging, labels, volumes and environment
- Optionally wait for sync completion (skipped for groups containing `forest_bootnodes`)

### Usage
Example playbook:

```yaml
---
- name: Deploy Forest full node
  hosts: forest_fullnodes
  become: true
  vars:
    network: calibration
    forest:
      image:
        name: ghcr.io/chainsafe/forest
        tag: latest-fat
      node_type: fullnode
      rust_log_level: info
      f3_enabled_sidecar: false
      host:
        config_path: /var/lib/forest/config
        data_path: /var/lib/forest/data
        scripts_path: /var/lib/forest/scripts
      rpc:
        enabled: true
        port: 2345
        host_port: 32345
      metrics:
        enabled: true
        port: 6116
        host_port: 36116
  roles:
    - chainsafe.filecoin.forest_fullnode_docker_role
```

To override configuration, set variables in `group_vars`/`host_vars` or via `vars` as above. Review and adapt `config.toml.j2` for advanced tuning if needed.

### Dependencies
- Docker engine on the target host
- Ansible collections listed in Requirements

### Troubleshooting
- Container restarts continuously: check `forest.log.txt` under `{{ forest.host.scripts_path }}` and ensure the `config.toml` is valid.
- Ports in use: adjust `forest.rpc.host_port` and `forest.metrics.host_port`.
- Slow sync: ensure disk and network performance meet Forest recommendations and that `ntp` is active.

### License
See `LICENSE.md` at the collection root.

### Author
ChainSafe Systems
