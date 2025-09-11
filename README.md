## ChainSafe Filecoin Ansible Collection (`chainsafe.filecoin`)

Automate provisioning and operations for Filecoin infrastructure using Ansible. This collection provides roles to install dependencies, bootstrap hosts, deploy Filecoin nodes (Lotus and Forest), manage snapshot pipelines, configure monitoring, and more.

Links:
- Documentation: https://infra-docs.chainsafe.dev/
- Repository: https://github.com/chainsafe/fil-ansible-collection
- Homepage: https://chainsafe.io/
- Issues: https://github.com/chainsafe/fil-ansible-collection/issue/tracker

---

### Requirements
- Ansible 2.15+ (recommended) and Python 3.9+
- Linux target hosts with SSH access and `sudo`
- The following collections will be installed automatically when using this collection:
  - `community.docker (>=4.0.0,<5.0.0)`
  - `community.general (>=10.0.0,<11.0.0)`
  - `ansible.posix (>=1.0.0,<2.0.0)`

### Installation
Install from Ansible Galaxy:

```
ansible-galaxy collection install chainsafe.filecoin
```

To use in a `requirements.yml`:

```yaml
collections:
  - name: chainsafe.filecoin
    version: ">=1.0.0"
```

### Contents
- **Roles**:
  - `install_packages`: Install common packages, Docker, and Docker Compose; includes helpful shell aliases.
  - `bootstrap`: Initial host bootstrap and handlers for common system setup.
  - `bootnode_monitor`: Defaults and tasks for bootnode monitoring.
  - `forest_fullnode_docker_role`: Deploy and manage a Forest full node via Docker; includes templates for `config.toml`, filter list, and helper scripts.
  - `forest_snapshots`: Snapshot pipeline (compose, jobs, monitoring, RabbitMQ) and Forest node config for snapshotting.
  - `lotus_fullnode_docker_role`: Deploy Lotus full or archival nodes via Docker; includes scripts for snapshot import/checks and configs.
  - `lotus_fountain_docker_role`: Deploy Lotus faucet services and Nginx configuration.
  - `opkssh`: Configure SSH auth via providers and templates.
  - `snapshot_role`: Create and schedule snapshot cron jobs.

See role `defaults/main.yml` files for configurable variables and role READMEs where present.

### Quick start
Example inventory `inventories/prod/hosts.ini`:

```ini
[filecoin_fullnodes]
fullnode1 ansible_host=203.0.113.10

[snapshotters]
snapshot1 ansible_host=203.0.113.20
```

Example playbook `site.yml`:

```yaml
---
- name: Prepare hosts
  hosts: all
  become: true
  roles:
    - chainsafe.filecoin.install_packages

- name: Deploy Lotus full node
  hosts: filecoin_fullnodes
  become: true
  roles:
    - chainsafe.filecoin.lotus_fullnode_docker_role

- name: Configure Forest snapshot pipeline
  hosts: snapshotters
  become: true
  roles:
    - chainsafe.filecoin.forest_snapshots
```

Vars are documented within each role under `roles/<role>/defaults/main.yml`. Review and override as needed in group_vars/host_vars.

### Usage examples
- Run a single role ad‑hoc:
  ```bash
  ansible-playbook -i inventories/prod/hosts.ini -l fullnode1 -b -K \
    -e "some_var=value" \
    -t setup site.yml
  ```

- Include a role directly in a task file:
  ```yaml
  - name: Deploy Forest full node
    ansible.builtin.include_role:
      name: chainsafe.filecoin.forest_fullnode_docker_role
  ```

### Supported platforms
- Linux hosts (e.g., Ubuntu/Debian). Refer to each role's defaults for specifics.

### Development
- Build the collection artifact:
  ```bash
  ansible-galaxy collection build
  ```

- Install the locally built artifact:
  ```bash
  ansible-galaxy collection install chainsafe-filecoin-*.tar.gz --force
  ```

- Contributing: open pull requests on the repository. Please follow Ansible best practices and ensure roles are idempotent.

### Versioning and License
- Versioning: Semantic Versioning (SemVer). See `galaxy.yml` for the current version.
- License: See `LICENSE.md`.

### Authors
- Josh (https://github.com/joshdougall)
- Samuel https://github.com/samuelarogbonlo
- Hamid (https://github.com/hamidmuslih)
- Faith Olapade (https://github.com/Faithtosin)
- Alexander Dobrodey (https://github.com/ADobrodey)

---

For more detailed role‑specific docs and architecture, see the docs site: https://infra-docs.chainsafe.dev/
