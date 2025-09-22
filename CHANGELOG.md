# Changelog

## [0.6.0](https://github.com/ChainSafe/fil-ansible-collection/compare/0.5.0...0.6.0) (2025-09-22)


### Features

* **bootstrap:** Update defaults, improve SSH tasks, and remove obsolete role ([a1bdbcf](https://github.com/ChainSafe/fil-ansible-collection/commit/a1bdbcf1a0c8845b6b68bf51f65c0202befd2e12))
* **forest_fullnode_docker_role:** Add healthcheck for Forest Docker container ([c7cce80](https://github.com/ChainSafe/fil-ansible-collection/commit/c7cce80018a0a8466ace81b3fef99416619ff82a))
* **forest_fullnode_docker_role:** Add task to restart unhealthy container and adjust command syntax ([8013fc6](https://github.com/ChainSafe/fil-ansible-collection/commit/8013fc63a7bda47c52855b967664f417c9abe8d1))
* **forest_fullnode_docker_role:** Refactor network variable usage and enhance documentation ([029a4f0](https://github.com/ChainSafe/fil-ansible-collection/commit/029a4f0d19f1b47e32488608e11c27ab6b81fd8f))
* **forest_fullnode_docker_role:** Update healthcheck and sync command syntax for improved stability ([3fb1f02](https://github.com/ChainSafe/fil-ansible-collection/commit/3fb1f021b68117253bf1cb02c675e4c146526515))
* **forest_snapshots_role:** Add remaining snapshot tracking and improve time estimation ([82dbeab](https://github.com/ChainSafe/fil-ansible-collection/commit/82dbeabfcc6355a23fb70f9508a24edc3fa31b6d))
* **forest_snapshots_role:** Optimize upload and cleanup processes for snapshots ([ea274bc](https://github.com/ChainSafe/fil-ansible-collection/commit/ea274bc1c44f7e1c4b2662e582780ce8109571c2))
* **forest_snapshots_role:** Refactor snapshot handling, update Lotus integration, and optimize configuration ([caff6fa](https://github.com/ChainSafe/fil-ansible-collection/commit/caff6fa344b45573395377b08bc4b92e1034e270))
* **forest_snapshots:** Refactor templates, update variables, and enhance snapshot management logic ([15c8a12](https://github.com/ChainSafe/fil-ansible-collection/commit/15c8a122cb9696ddead1469a38e87bf691d065e6))
* **forest_snapshots:** Remove unused validation script, improve disk configuration, enhance RabbitMQ setup, and refine snapshot logic ([8d08cfe](https://github.com/ChainSafe/fil-ansible-collection/commit/8d08cfed1fb6e0ae12ea2b3f48a465b1e801e7a7))
* **install_packages:** Add IPv6 support for Docker ([a5317da](https://github.com/ChainSafe/fil-ansible-collection/commit/a5317da3b6470ab32cd9198658705d1344b82173))
* **lotus_fountain_docker_role:** Add role to deploy Lotus Fountain with Nginx support ([1328cda](https://github.com/ChainSafe/fil-ansible-collection/commit/1328cda3f546cf720f7122672f9e139fc0af7f6c))
* **lotus_fullnode_docker_role:** Add role to deploy and configure Lotus Full Node with Docker ([b3d8f31](https://github.com/ChainSafe/fil-ansible-collection/commit/b3d8f31d60eba94f1e87d1c2eb693770e72daba2))
* **lotus_fullnode_docker_role:** Refactor role variables, script paths, and container configuration ([a093b0e](https://github.com/ChainSafe/fil-ansible-collection/commit/a093b0ed12f368091bfea7585f4ccc6d9c4f02f8))
* Refactor roles and integrate Nginx support ([c27da44](https://github.com/ChainSafe/fil-ansible-collection/commit/c27da442d1a1c7452ff39124189a06f24752dbe6))


### Bug Fixes

* **forest_fullnode_docker_role:** Add condition to ensure tasks only run when `forest_docker_start` changes ([b79ef26](https://github.com/ChainSafe/fil-ansible-collection/commit/b79ef2621b9a593f842924487cb11c9be1f1d579))
* **forest_snapshot:** Adjust snapshot logic and improve template handling for consistency in forest_snapshots ([eba5b16](https://github.com/ChainSafe/fil-ansible-collection/commit/eba5b16293c8372836feab677c984668e7054b67))
* update documentation ([f19b474](https://github.com/ChainSafe/fil-ansible-collection/commit/f19b4743c039aa4b96cc7fc559d7c00deeb6952f))

## [0.5.0](https://github.com/ChainSafe/fil-ansible-collection/compare/0.4.0...0.5.0) (2025-09-09)


### Features

* Separate historic and latest snapshot tasks, adjust queue wait timeout, and update Docker/templates for distinct configurations ([655f3dd](https://github.com/ChainSafe/fil-ansible-collection/commit/655f3dde8fee758cdb9db7f76bc9e61ce62338c6))
* Update forest_snapshots for historic configuration, adjust templates and defaults for new variables ([03e5da7](https://github.com/ChainSafe/fil-ansible-collection/commit/03e5da754cabf36609ad78b53650ddafa9dc571a))

## [0.4.0](https://github.com/ChainSafe/fil-ansible-collection/compare/0.3.1...0.4.0) (2025-09-09)


### Features

* Enhance snapshot processes with new task configurations, adjust state computation logic, and refine logging/debugging ([b1d16d0](https://github.com/ChainSafe/fil-ansible-collection/commit/b1d16d0f959c03a0eb769f3046b85711923289e3))
* Enhance snapshot validation with metadata gathering and upload ([302abf4](https://github.com/ChainSafe/fil-ansible-collection/commit/302abf495fd81ee82eb5c85d8b99529549b8b4f5))


### Bug Fixes

* Adjust ownership, add root user in Docker, and refine RabbitMQ configurations for durability ([af17288](https://github.com/ChainSafe/fil-ansible-collection/commit/af172886090c7445c3baa75e6fd958528cc4d81d))
* Correct processing and upload ([81b8c9d](https://github.com/ChainSafe/fil-ansible-collection/commit/81b8c9dd06e80c1281c6727783ea1dcb78ed803f))
* Update ownership, logging, and error handling in forest_snapshots tasks and scripts ([5759716](https://github.com/ChainSafe/fil-ansible-collection/commit/5759716b4e8157182ebc703e53906c15e852cf74))

## [0.3.1](https://github.com/ChainSafe/fil-ansible-collection/compare/v0.3.0...0.3.1) (2025-09-07)


### Bug Fixes

* Ansible-galaxy doesnt tollerate v in tags ([f8c4169](https://github.com/ChainSafe/fil-ansible-collection/commit/f8c4169c9efcf218ff0c0d989ff874461ae17578))

## [0.3.0](https://github.com/ChainSafe/fil-ansible-collection/compare/v0.2.0...v0.3.0) (2025-09-07)


### Features

* Python setup for archival process ([06702e6](https://github.com/ChainSafe/fil-ansible-collection/commit/06702e63ed8d0afbb408507e06e526f8ab5e38d6))

## [0.2.0](https://github.com/ChainSafe/fil-ansible-collection/compare/v0.1.0...v0.2.0) (2025-09-03)


### Features

* Separate filecoin roles ([143f68a](https://github.com/ChainSafe/fil-ansible-collection/commit/143f68ac0d814aa7720be3d660af89a430abea3d))
