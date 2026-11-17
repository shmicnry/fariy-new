# Mac bridge and execution boundary

Fairy 0.3 includes a read-only Mac bridge inside the local API:

- `GET /v2/mac/status`: macOS version, executor mode and explicit “permission not probed” states.
- `GET /v2/mac/apps`: application names and paths; never launches an app.
- `GET /v2/mac/files?path=`: lists metadata inside configured roots; realpath and symlink escapes are rejected.

The `Mac 启动允许应用` built-in skill can run `/usr/bin/open` only when all of these are true:

1. the owner enabled `mac_execute`;
2. the application name or bundle ID is in `mac_allowed_apps`;
3. the skill was installed, explicitly granted with a time limit, and invoked by the owner.

The result says `launch_command_succeeded_window_not_verified`. It does not claim that an application task completed.

Not enabled: arbitrary shell, argument passthrough, keyboard or pointer injection, window automation, ScreenCaptureKit,
screen recording, microphone, camera, file writes and self-modification of Fairy's permissions. Those require a separately
packaged bridge with device identity, TCC checks, a fresh observation, fencing, stop handling and result reconciliation.
