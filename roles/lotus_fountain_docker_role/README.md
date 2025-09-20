# Run Lotus Fountain (Faucet)

This role is to spin up a Lotus Fountain (Faucet) as a docker container.

## Dependencies

- Docker needs to be installed
- A Lotus full node is needed for RPC calls and data directory, you can find the [role](https://github.com/ChainSafe/ansible-collection/tree/main/roles/lotus_fullnode_docker_role)
- You need reCaptcha keys, check references below.

## How to use the role from the collection?

1. Add both roles and install the collection

    ```sh
    ansible-galaxy install -r requirements.yml
    ```

2. Call the both roles from the collection in the playbook as below.

    ```yaml
    ---
    - name: Deploy lotus fullnode
      hosts: lotus_faucet
      gather_facts: false
      become: true
      roles:
        - role: chainsafe.general.lotus_fullnode_docker_role

    - name: Deploy lotus fountain
      hosts: lotus_faucet
      gather_facts: false
      become: true
      roles:
        - role: chainsafe.general.lotus_fountain_docker_role
    ```

    Link to [default values](./defaults/main.yml)

3. The Lotus Fountain will run on `0.0.0.0:7777` port and you can `curl` it.

    ```sh
    curl localhost:7777
    ```

## How to setup a wallet

1. Make sure that Lotus Fountain and Fullnode sharing the same data directory for `keystore`, by default it is is `/var/lib/lotus`
2. Get into Lotus Fountain container and generate a wallet address and take a  note of `public key`

    ```sh
    docker exec -it lotus-fountain bash
    lotus wallet new
    ```

    you can check the wallet addresses are populated in `/var/lib/lotus/keystore`
    or alternatively list the wallets as below.

    ```sh
    lotus wallet list
    ```

3. Export the private key of a wallet and save it in a secure place so you can import it if `keystore` dir is destroyed or you are moving service to another machine.

    ```sh
     lotus wallet export < wallet pub key > pv.key
    ```

4. Import a wallet

    ```sh
    lotus wallet import pv.key
    ```

## How to send tFil

**Note**: If the request is around 100 tFil, use the faucet website, for larger requests follow below steps.

1. SSH to fountain machine

    ```sh
    ssh <find the IP in filecoin-execution hosts.ini>
    ```

2. Get into the faucet container

    ```sh
    docker exec -it lotus-fountain bash
    ```

3. If the address starts with `t or f` skip this step. if the address starts with `0x...`, it is eth/fil compatible address, to send tFil you need Filecoin type, run the below command and it will output `Filecoin address:`

    ```sh
    lotus evm stat 0x...
    ```

4. Send tFill

    ```sh
    lotus send <tfil address> <amount>
    ```

## References

1. [Wallet management](https://lotus.filecoin.io/lotus/manage/manage-fil/)
2. [Create reCAPTCHA keys for websites with Google account](https://cloud.google.com/recaptcha-enterprise/docs/create-key-website)
