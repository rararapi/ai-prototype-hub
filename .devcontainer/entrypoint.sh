#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'ProtoHub Dev Container initialization refused: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == 0 ]] || fail 'the initializer must start as root, then drop to developer'
developer_uid="$(id -u developer)"
developer_gid="$(id -g developer)"
[[ "$developer_uid" != 0 && "$developer_gid" != 0 ]] || fail 'developer must be a non-root user/group'

# These are the only writable roots whose ownership this initializer can change.
# Reject symlink ancestors before inspecting mountpoints or touching any owner.
for directory in \
  /opt /opt/protohub-venv \
  /workspaces /workspaces/protohub /workspaces/protohub/apps /workspaces/protohub/apps/web \
  /workspaces/protohub/apps/web/node_modules /workspaces/protohub/tests \
  /workspaces/protohub/tests/e2e /workspaces/protohub/tests/e2e/node_modules; do
  [[ ! -L "$directory" && -d "$directory" ]] || fail "expected a real directory: $directory"
done

dependency_volumes=(
  /opt/protohub-venv
  /workspaces/protohub/apps/web/node_modules
  /workspaces/protohub/tests/e2e/node_modules
)

# Check all boundaries first so a malformed launch fails before any ownership change.
for directory in "${dependency_volumes[@]}"; do
  mountpoint -q -- "$directory" || fail "a declared dependency volume is missing: $directory"
  mapfile -t submounts < <(findmnt --raw --noheadings --submounts --mountpoint "$directory" --output TARGET)
  [[ "${#submounts[@]}" == 1 && "${submounts[0]}" == "$directory" ]] \
    || fail "unexpected nested mount inside dependency volume: $directory"
done

for directory in "${dependency_volumes[@]}"; do
  # Scan on every launch so an interrupted UID migration is recoverable even if the
  # volume root already has the new owner. Only mismatched entries are changed.
  # -P/-xdev plus chown -h leave symlink targets and the source bind untouched.
  find -P "$directory" -xdev \( ! -uid "$developer_uid" -o ! -gid "$developer_gid" \) \
    -exec chown --no-dereference "$developer_uid:$developer_gid" {} +
done

exec gosu developer "$@"
