# ProtoHub Dev Container internals

This container supplies the coding/check toolchain. App services remain in the separate
WSL-host Compose or kind environment. It has no Docker socket/CLI, kubeconfig, privileged
mode, host network, extra capabilities, automatic application startup, or forwarded ports.
See [the development guide](../docs/DEV_CONTAINER.md) for editor and daily commands.

Open from the repository's WSL/Linux filesystem checkout. `initializeCommand` creates only
the two host `node_modules` placeholder directories as the invoking host user; it preserves
existing contents. Dedicated `volume-nocopy` mounts hide host dependencies and start empty
so Windows/Linux installs do not mix. Each `${devcontainerId}` gets distinct venv/web/e2e volumes.

The image starts root only for `.devcontainer/entrypoint.sh`. All three dependency roots
must be real mountpoints with no symlink ancestors or nested mounts. Each launch scans
those exact volumes and adjusts only entries with mismatched owners, without following
symlinks. This also recovers an interrupted UID migration after the root owner changed.
The source bind and its other files are never recursively chowned. `gosu developer` then
replaces the initializer. Editor sessions, terminals and post-create run as `developer`
(UID/GID 1000 by default; `updateRemoteUserUID` adapts to the host user). No sudo is installed.

Post-create installs only the existing uv/npm lockfiles and checks skill provenance. It
does not start the application, modify host settings, install hooks or contact cloud APIs.
Language versions and image digests match the existing checks image. A built image records
actual Python/Node/npm/uv and apt tool versions in `/usr/local/share/protohub-toolchain.txt`.

Dependency roots:

| Volume suffix | Container path |
|---|---|
| `venv` | `/opt/protohub-venv` (`UV_PROJECT_ENVIRONMENT`) |
| `web-node-modules` | `/workspaces/protohub/apps/web/node_modules` |
| `e2e-node-modules` | `/workspaces/protohub/tests/e2e/node_modules` |

Missing volumes fail closed before any ownership changes. Reopening/stopping the editor
stops this toolchain container (`shutdownAction: stopContainer`) and retains dependency
volumes. App resources retain their separate existing lifecycle and ownership rules.
