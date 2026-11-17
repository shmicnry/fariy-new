"""Read-only Mac bridge with realpath confinement and no arbitrary command surface."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .service import fail


class MacBridge:
    def __init__(self, service):
        self.service = service

    def _config(self):
        with self.service.db.sessions() as session:
            configs = [
                row
                for row in self.service.rows(session, "config")
                if row.status == "active"
            ]
            if not configs:
                return {
                    "mac_allowed_apps": [],
                    "mac_allowed_paths": [],
                    "mac_execute": False,
                }
            return json.loads(configs[0].payload)

    @staticmethod
    def _sw_vers():
        try:
            product = subprocess.run(
                ["/usr/bin/sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
            build = subprocess.run(
                ["/usr/bin/sw_vers", "-buildVersion"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
            return product, build
        except (OSError, subprocess.TimeoutExpired):
            return None, None

    def status(self):
        config = self._config()
        version, build = self._sw_vers()
        return {
            "platform": sys_platform(),
            "machine": platform.machine(),
            "release": platform.release(),
            "macos_version": version,
            "macos_build": build,
            "executor_mode": "execute" if config.get("mac_execute") else "observe_only",
            "configured_app_count": len(config.get("mac_allowed_apps", [])),
            "configured_path_count": len(config.get("mac_allowed_paths", [])),
            "accessibility_permission": "unknown_not_probed",
            "screen_recording_permission": "unknown_not_probed",
            "arbitrary_shell": False,
            "input_injection": False,
            "screen_capture": False,
            "execute_action_available": bool(
                config.get("mac_execute") and config.get("mac_allowed_apps")
            ),
        }

    def applications(self):
        allowed = set(self._config().get("mac_allowed_apps", []))
        discovered = {}
        roots = (Path("/Applications"), Path("/System/Applications"))
        for root in roots:
            if not root.is_dir():
                continue
            try:
                entries = sorted(root.iterdir(), key=lambda path: path.name.casefold())
            except OSError:
                continue
            for item in entries[:500]:
                if item.suffix != ".app":
                    continue
                bundle = item.stem
                discovered[bundle] = {
                    "name": bundle,
                    "bundle_path": str(item),
                    "allowed": bundle in allowed or str(item) in allowed,
                }
                if len(discovered) >= 200:
                    break
        return {
            "applications": list(discovered.values()),
            "allowlist_count": len(allowed),
            "launch_available": bool(self._config().get("mac_execute") and allowed),
        }

    def open_app(self, name):
        config = self._config()
        if not config.get("mac_execute"):
            fail(409, "mac_execute_not_enabled")
        allowed = set(config.get("mac_allowed_apps", []))
        applications = {
            item["name"]: item["bundle_path"]
            for item in self.applications()["applications"]
        }
        if name in allowed:
            if name in applications:
                flag, target = "-a", applications[name]
            else:
                flag, target = "-b", name
        elif applications.get(name) in allowed:
            flag, target = "-a", applications[name]
        else:
            fail(403, "application_outside_allowlist")
        try:
            process = subprocess.run(
                ["/usr/bin/open", flag, target],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env={"PATH": os.defpath},
            )
        except (OSError, subprocess.TimeoutExpired):
            fail(503, "application_launch_failed")
        if process.returncode != 0:
            fail(503, "application_launch_failed")
        return {
            "application": name,
            "command_result": "success",
            "verification": "launch_command_succeeded_window_not_verified",
        }

    def files(self, requested):
        if not requested:
            fail(422, "path_required")
        roots = []
        for raw in self._config().get("mac_allowed_paths", []):
            try:
                roots.append(Path(raw).resolve(strict=True))
            except (OSError, RuntimeError):
                continue
        if not roots:
            fail(409, "no_allowlisted_paths")
        try:
            target = Path(requested).resolve(strict=True)
        except (OSError, RuntimeError):
            fail(404, "path_not_found")
        allowed = any(target == root or target.is_relative_to(root) for root in roots)
        if not allowed:
            fail(403, "path_outside_allowlist")
        if not target.is_dir():
            fail(422, "directory_required")
        entries = []
        try:
            children = sorted(target.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            fail(403, "directory_not_readable")
        for child in children[:100]:
            try:
                resolved = child.resolve(strict=False)
                contained = any(
                    resolved == root or resolved.is_relative_to(root) for root in roots
                )
                stat = child.stat(follow_symlinks=False)
                entries.append(
                    {
                        "name": child.name,
                        "kind": (
                            "directory"
                            if child.is_dir()
                            else "file" if child.is_file() else "other"
                        ),
                        "bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                        "contained": contained,
                        "symlink": child.is_symlink(),
                    }
                )
            except OSError:
                continue
        return {
            "path": str(target),
            "entries": entries,
            "truncated": len(children) > 100,
            "read_only": True,
        }


def sys_platform():
    return os.uname().sysname if hasattr(os, "uname") else platform.system()
