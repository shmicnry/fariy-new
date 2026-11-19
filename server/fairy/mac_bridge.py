"""Realpath-confined Mac bridge with read-only probes and explicit write scopes."""

from __future__ import annotations

import hashlib
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
                    "mac_file_write": False,
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

    @staticmethod
    def _helper_status():
        configured = os.getenv("FAIRY_MAC_BRIDGE_EXECUTABLE", "").strip()
        default = (
            Path(__file__).resolve().parents[2]
            / "apps"
            / "mac-bridge"
            / "FairyMacBridge"
            / ".build"
            / "release"
            / "FairyMacBridge"
        )
        executable = Path(configured) if configured else default
        if not executable.is_file():
            return None
        try:
            process = subprocess.run(
                [str(executable), "status"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if process.returncode != 0:
                return None
            payload = json.loads(process.stdout)
            if payload.get("bridge") != "fairy-mac-bridge":
                return None
            return payload
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            return None

    def status(self):
        config = self._config()
        version, build = self._sw_vers()
        helper = self._helper_status()
        tcc = helper.get("tcc", {}) if helper else {}
        return {
            "platform": sys_platform(),
            "machine": platform.machine(),
            "release": platform.release(),
            "macos_version": version,
            "macos_build": build,
            "executor_mode": (
                "scoped_actions"
                if config.get("mac_execute") or config.get("mac_file_write")
                else "observe_only"
            ),
            "configured_app_count": len(config.get("mac_allowed_apps", [])),
            "configured_path_count": len(config.get("mac_allowed_paths", [])),
            "accessibility_permission": (
                tcc.get("accessibility", "unknown_not_probed")
                if tcc
                else "unknown_not_probed"
            ),
            "screen_recording_permission": (
                tcc.get("screen_recording", "unknown_not_probed")
                if tcc
                else "unknown_not_probed"
            ),
            "helper_version": helper.get("version") if helper else None,
            "arbitrary_shell": False,
            "input_injection": False,
            "screen_capture": False,
            "execute_action_available": bool(
                config.get("mac_execute") and config.get("mac_allowed_apps")
            ),
            "file_create_action_available": bool(
                config.get("mac_file_write") and config.get("mac_allowed_paths")
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

    def create_file(self, requested, content):
        config = self._config()
        if not config.get("mac_file_write"):
            fail(409, "mac_file_write_not_enabled")
        if not requested:
            fail(422, "path_required")
        if not isinstance(content, str) or not content:
            fail(422, "file_content_required")
        payload = content.encode("utf-8")
        if len(payload) > 256 * 1024:
            fail(413, "file_content_too_large")
        target = Path(requested)
        if not target.is_absolute() or target.name in ("", ".", ".."):
            fail(422, "file_path_must_be_absolute")

        roots = []
        for raw in config.get("mac_allowed_paths", []):
            try:
                roots.append(Path(raw).resolve(strict=True))
            except (OSError, RuntimeError):
                continue
        if not roots:
            fail(409, "no_allowlisted_paths")
        try:
            parent = target.parent.resolve(strict=True)
        except (OSError, RuntimeError):
            fail(404, "parent_directory_not_found")
        resolved = parent / target.name
        if not any(
            resolved == root or resolved.is_relative_to(root)
            for root in roots
        ):
            fail(403, "path_outside_allowlist")
        if resolved.exists() or target.is_symlink():
            fail(409, "file_already_exists")

        try:
            directory_fd = os.open(
                parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
        except OSError:
            fail(403, "parent_directory_not_writable")

        created = False
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                file_fd = os.open(
                    target.name,
                    flags,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                fail(409, "file_already_exists")
            except OSError:
                fail(403, "file_not_writable")
            created = True
            try:
                with os.fdopen(file_fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                try:
                    os.unlink(target.name, dir_fd=directory_fd)
                except OSError:
                    pass
                fail(503, "file_write_failed")
        finally:
            os.close(directory_fd)

        try:
            written = resolved.read_bytes()
        except OSError:
            if created:
                try:
                    resolved.unlink()
                except OSError:
                    pass
            fail(503, "file_verification_failed")
        digest = hashlib.sha256(written).hexdigest()
        expected = hashlib.sha256(payload).hexdigest()
        if written != payload or digest != expected:
            try:
                resolved.unlink()
            except OSError:
                pass
            fail(503, "file_verification_failed")
        return {
            "path": str(resolved),
            "bytes": len(written),
            "sha256": digest,
            "overwrote": False,
            "verification": "hash_and_byte_readback_matched",
        }

    def ax_tree(self, bundle_id=None):
        helper = self._helper_status()
        if helper is None:
            fail(503, "mac_bridge_helper_unavailable")
        configured = os.getenv("FAIRY_MAC_BRIDGE_EXECUTABLE", "").strip()
        executable = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2]
            / "apps"
            / "mac-bridge"
            / "FairyMacBridge"
            / ".build"
            / "release"
            / "FairyMacBridge"
        )
        command = [str(executable), "ax-tree"]
        if bundle_id:
            command.append(bundle_id)
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            fail(503, "mac_ax_tree_failed")
        if process.returncode != 0:
            if "accessibility_permission_required" in process.stderr:
                fail(403, "accessibility_permission_required")
            fail(503, "mac_ax_tree_failed")
        try:
            payload = json.loads(process.stdout)
        except (ValueError, TypeError):
            fail(503, "mac_ax_tree_invalid_output")
        if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
            fail(503, "mac_ax_tree_invalid_output")
        return dict(payload, read_only=True, input_injection=False)


def sys_platform():
    return os.uname().sysname if hasattr(os, "uname") else platform.system()
