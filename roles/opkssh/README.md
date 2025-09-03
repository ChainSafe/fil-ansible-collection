# OPKSSH role https://github.com/openpubkey/opkssh/

This role will install and configure OPKSSH on the destination server.

## Dependencies
SSH needs to be installed on the host system to use this role.

## Role Variables

Default variables are defined in [defaults/main.yaml](defaults/main.yaml)

## Example Playbook

With a target group of hosts called `all` , your playbook could look like this:

```yaml
- hosts: all
  become: true
  roles:
    - role: chainsafe.general.opkssh
```
