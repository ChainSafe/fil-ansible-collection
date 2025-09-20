# Run Lotus Full Node and archive node

This role is used to spin up a lotus full nodes and archive nodes  as a docker container, its also the functionality to import keys like the `wallet`, `libp2p` and `jwt private key`

## How to use the role from the collection?

1. Add both roles and install the collection

    ```sh
    ansible-galaxy install -r requirements.yml
    ```

2. Use the roles in your playbook as shown below:.

    ```yaml
    ---
    - name: Deploy lotus fullnode
      hosts: lotus
      gather_facts: false
      become: true
      roles:
        - role: chainsafe.general.lotus_fullnode_docker_role
      vars:
        ansible_user:
        lotus_metrics_port:

    ```

   Link to [default values](./defaults/main.yml)

### run_lotus_node

This task file contains operations for setting up and starting the Lotus node Docker container for both the full node and archive node.
The entrypoint command that start the container is set as a variable, default value is for full node and is the on the list of vars above, in case this task is running against an archive node, make sure to add a variable in `hosts.ini` to include the correct startup command for the archive node.

   ```ini
   lotus_docker_command_archive="lotus daemon"
   ```

### run_lotus_maintenance

This task file includes operations related to Lotus node maintenance, such as directory creation, permission adjustments, and template imports. Additionally, it runs the Docker container in sleep mode to allow the script to import snapshots, without having Lotus deamon running. Before executing Lotus maintenance tasks, ensure that the following variables are set in your `hosts.ini` file

   ```ini
   run_lotus_maintenance=true
   run_lotus_node=false
   ```

### Updating vm.max_map_count for Archive Node

To ensure the proper allocation of memory for your archive node, follow these steps to update the vm.max_map_count parameter.

#### Edit sysctl.conf

Open the /etc/sysctl.conf file

#### Adjust the valus of the following line to set vm.max_map_count

```sh
vm.max_map_count=262144
```

#### Reload Configuration

Run the following command to reload the sysctl configuration

```sh
sudo sysctl -p
```

#### Restart Archive Node

Restart your archive node to apply the changes. The node should start without any memory allocation errors.
