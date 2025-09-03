# Bootstrap a new machine
This role will install basic packages. At high level it will execute below actions:
- update and upgrade the packages
- Install common packages (git, nano, htop, python, docker and docker-compose)
- Configure firewall to allow or block traffic to ports

## Dependecies
Install below roles
```sh
ansible-galaxy install geerlingguy.docker geerlingguy.firewall
```

## How to use the role from the collection?
- Install the collection
- Call the role from the collection in the playbook as below.

```yaml
---
- hosts: all
  gather_facts: true
  name: Install docker and common packages
  become: true
  roles:
    - role: chainsafe.general.install_packages
```

## Link to [default values](./defaults/main.yml)
