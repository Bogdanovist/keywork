"""Docker sandbox launcher for the Keywork TUI.

Provides credential validation and image management for launching agent
processes inside the Docker sandbox. Builds sandbox commands with repo-aware
mount strategies and optional per-repo configuration.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import platform
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_NAME = "keywork-sandbox"
SANDBOX_DIR = Path("agents/sandbox")
DOCKERFILE_PATH = SANDBOX_DIR / "Dockerfile"

# Module-level container tracking for cleanup on exit
_tracked_containers: list[str] = []


def _get_claude_credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _export_macos_keychain_credentials() -> tuple[bool, str]:
    """On macOS, export Claude credentials from Keychain to file.

    Returns (exported, error_message). If credentials already exist on disk,
    returns (True, ""). If export fails, returns (False, reason).
    """
    creds_path = _get_claude_credentials_path()
    if creds_path.exists():
        return True, ""

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False, (
                "Claude credentials not found in macOS Keychain or on disk.\n"
                "Run 'claude' on the host first to authenticate."
            )
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        creds_path.write_text(result.stdout.strip())
        creds_path.chmod(0o600)
        return True, ""
    except FileNotFoundError:
        return False, "macOS 'security' command not found."
    except subprocess.TimeoutExpired:
        return False, "Timed out reading Claude credentials from Keychain."


def _check_token_expiry(creds_path: Path) -> tuple[bool, str]:
    """Check Claude OAuth token expiry from credentials JSON.

    Returns (valid, warning_or_error). Empty string means no issue.
    """
    try:
        data = json.loads(creds_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Failed to read credentials file: {e}"

    expires_at = None
    oauth_data = data.get("claudeAiOauth", {})
    if isinstance(oauth_data, dict):
        expires_at = oauth_data.get("expiresAt")

    if expires_at is None:
        return True, ""

    try:
        expires_at = int(expires_at)
    except (ValueError, TypeError):
        return True, ""

    now_ms = int(time.time() * 1000)

    if expires_at <= now_ms:
        return False, (
            "Claude OAuth token has expired.\n"
            "Run 'claude' in your terminal to re-authenticate, then retry."
        )

    margin_ms = 30 * 60 * 1000
    if (expires_at - now_ms) <= margin_ms:
        remaining_min = (expires_at - now_ms) // 60000
        return True, f"WARNING: Claude OAuth token expires in ~{remaining_min} minutes."

    return True, ""


def validate_credentials() -> tuple[bool, str]:
    """Validate Docker, Claude, and SSH credentials on the host.

    Returns (valid, error_message). If valid is True the sandbox can launch.
    error_message may contain a warning even when valid is True.
    """
    # Check Docker is available
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=15,
        )
    except FileNotFoundError:
        return False, (
            "Docker is required to run the agent sandbox.\n"
            "Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
        )
    except subprocess.TimeoutExpired:
        return False, "Docker daemon is not responding. Is Docker Desktop running?"

    # Claude credentials
    if platform.system() == "Darwin":
        ok, err = _export_macos_keychain_credentials()
        if not ok:
            return False, err

    creds_path = _get_claude_credentials_path()
    if not creds_path.exists():
        return False, (
            "Claude credentials not found.\n"
            "Run 'claude' on the host first to authenticate."
        )

    valid, msg = _check_token_expiry(creds_path)
    if not valid:
        return False, msg

    # SSH agent check
    ssh_sock = os.environ.get("SSH_AUTH_SOCK")
    if not ssh_sock:
        warning = "WARNING: SSH_AUTH_SOCK not set. Git operations requiring SSH keys will fail."
        msg = f"{msg}\n{warning}".strip() if msg else warning

    # Return with optional warning
    return True, msg


def _read_repo_config(repo_name: str) -> dict:
    """Read repo-specific sandbox config from agents/repos/{repo_name}/config.yaml.

    Uses a simple regex-based parser to extract sandbox configuration without
    requiring a YAML library. Returns an empty dict if the config file is
    missing or unreadable.

    Expected format:
        sandbox:
          env_vars:
            KEY: value
          volumes:
            - /host/path:/container/path
          ports:
            - 8080
    """
    config_path = Path.cwd() / "agents" / "repos" / repo_name / "config.yaml"
    if not config_path.exists():
        return {}

    try:
        content = config_path.read_text()
    except OSError:
        logger.warning("Failed to read repo config: %s", config_path)
        return {}

    result: dict = {"env_vars": {}, "volumes": [], "ports": []}

    # Find the sandbox: section
    sandbox_match = re.search(r"^sandbox:\s*$", content, re.MULTILINE)
    if not sandbox_match:
        return result

    sandbox_text = content[sandbox_match.end():]
    # Trim at the next top-level key (non-indented, non-empty line that isn't a comment)
    next_top = re.search(r"^\S", sandbox_text, re.MULTILINE)
    if next_top:
        sandbox_text = sandbox_text[:next_top.start()]

    # Parse env_vars section
    env_match = re.search(r"^\s+env_vars:\s*$", sandbox_text, re.MULTILINE)
    if env_match:
        env_text = sandbox_text[env_match.end():]
        for line in env_text.splitlines():
            if not line.strip() or not line.startswith("      "):
                # Stop at de-dent or empty line
                if line.strip() and not line.startswith("      "):
                    break
                continue
            kv_match = re.match(r"^\s+(\w+):\s*(.+)$", line)
            if kv_match:
                result["env_vars"][kv_match.group(1)] = kv_match.group(2).strip()

    # Parse volumes section
    vol_match = re.search(r"^\s+volumes:\s*$", sandbox_text, re.MULTILINE)
    if vol_match:
        vol_text = sandbox_text[vol_match.end():]
        for line in vol_text.splitlines():
            if not line.strip():
                continue
            if not line.startswith("      "):
                break
            item_match = re.match(r"^\s+-\s+(.+)$", line)
            if item_match:
                result["volumes"].append(item_match.group(1).strip())

    # Parse ports section
    port_match = re.search(r"^\s+ports:\s*$", sandbox_text, re.MULTILINE)
    if port_match:
        port_text = sandbox_text[port_match.end():]
        for line in port_text.splitlines():
            if not line.strip():
                continue
            if not line.startswith("      "):
                break
            item_match = re.match(r"^\s+-\s+(\d+)", line)
            if item_match:
                result["ports"].append(int(item_match.group(1)))

    return result


def _get_image_creation_time() -> float | None:
    """Get the creation time of the keywork-sandbox Docker image.

    Returns epoch seconds or None if image doesn't exist.
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Created}}", IMAGE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        created_str = result.stdout.strip()
        if not created_str:
            return None
        from datetime import datetime, timezone

        # Docker format: 2024-01-15T10:30:00.123456789Z
        # Truncate nanoseconds to microseconds for fromisoformat
        if "." in created_str:
            base, frac = created_str.split(".", 1)
            frac = frac.rstrip("Z")[:6]
            created_str = f"{base}.{frac}+00:00"
        else:
            created_str = created_str.rstrip("Z") + "+00:00"
        dt = datetime.fromisoformat(created_str)
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _image_exists() -> bool:
    """Check if the keywork-sandbox Docker image exists."""
    try:
        result = subprocess.run(
            ["docker", "images", "-q", IMAGE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ensure_sandbox_image(on_output: callable | None = None) -> bool:
    """Build sandbox Docker image if needed.

    Checks if the image exists and whether the Dockerfile has been modified
    since the last build. Rebuilds if necessary, streaming output via the
    on_output callback.

    Returns True if the image is ready.
    """
    needs_build = False

    if not _image_exists():
        needs_build = True
        if on_output:
            on_output("Sandbox image not found, building...")
    else:
        # Compare Dockerfile mtime to image creation time
        if DOCKERFILE_PATH.exists():
            dockerfile_mtime = DOCKERFILE_PATH.stat().st_mtime
            image_created = _get_image_creation_time()
            if image_created is None or dockerfile_mtime > image_created:
                needs_build = True
                if on_output:
                    on_output("Dockerfile changed since last build, rebuilding...")

    if not needs_build:
        if on_output:
            on_output("Sandbox image is up to date.")
        return True

    if not DOCKERFILE_PATH.exists():
        if on_output:
            on_output(f"ERROR: Dockerfile not found at {DOCKERFILE_PATH}")
        return False

    # Build the image
    if on_output:
        on_output(f"=== Building sandbox image ({IMAGE_NAME}) ===")

    try:
        process = subprocess.Popen(
            ["docker", "build", "-t", IMAGE_NAME, "-f", str(DOCKERFILE_PATH), str(SANDBOX_DIR)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in process.stdout:
            if on_output:
                on_output(line.rstrip())
        process.wait()

        if process.returncode != 0:
            if on_output:
                on_output(f"ERROR: Image build failed with exit code {process.returncode}")
            return False

        if on_output:
            on_output("Sandbox image built successfully.")
        return True
    except FileNotFoundError:
        if on_output:
            on_output("ERROR: Docker not found. Cannot build sandbox image.")
        return False
    except OSError as e:
        if on_output:
            on_output(f"ERROR: Failed to build sandbox image: {e}")
        return False


def build_sandbox_command(
    script: str,
    args: list[str] | None = None,
    repo_name: str = "",
    goal_name: str = "",
    interactive: bool = False,
    extra_ports: list[int] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> tuple[list[str], str]:
    """Construct the docker run command for launching a sandbox container.

    Args:
        script: Path to the script to run inside the container.
        args: Additional arguments passed to the script.
        repo_name: Name of the target repository (for workspace mount and config).
        goal_name: Name of the goal (for state mount and env vars).
        interactive: Whether to attach a TTY for interactive sessions.
        extra_ports: Additional ports to forward from the container.
        env_overrides: Extra environment variables to inject.

    Returns (command_list, container_name). The container_name is used
    internally for tracking and cleanup.
    """
    container_name = f"keywork-agent-{uuid.uuid4().hex[:8]}"

    cmd = ["docker", "run", "--rm", "--name", container_name]

    # TTY flags for interactive sessions
    if interactive:
        cmd.extend(["-it"])

    # Mount workspace repo (read-write, for code changes)
    workspace_path = str(Path.cwd() / "workspace" / repo_name) if repo_name else str(Path.cwd() / "workspace")
    cmd.extend(["-v", f"{workspace_path}:/workspace"])

    # Mount goal state (read-write, for state updates)
    if goal_name:
        goal_path = str(Path.cwd() / "agents" / "goals" / goal_name)
        cmd.extend(["-v", f"{goal_path}:/state"])

    # Mount agents directory (read-only, for prompts/skills/repos)
    agents_path = str(Path.cwd() / "agents")
    cmd.extend(["-v", f"{agents_path}:/agents:ro"])

    # Claude credentials
    claude_dir = str(Path.home() / ".claude")
    cmd.extend(["-v", f"{claude_dir}:/home/agent/.claude-host:ro"])

    # Named volume for cache persistence across containers
    cmd.extend(["-v", "keywork-cache:/home/agent/.cache/uv"])

    # SSH agent forwarding (platform-specific socket path)
    ssh_sock = os.environ.get("SSH_AUTH_SOCK")
    if ssh_sock:
        if platform.system() == "Darwin":
            cmd.extend(["-v", "/run/host-services/ssh-auth.sock:/ssh-agent:ro"])
        else:
            cmd.extend(["-v", f"{ssh_sock}:/ssh-agent:ro"])
        cmd.extend(["-e", "SSH_AUTH_SOCK=/ssh-agent"])

    # Core environment variables
    cmd.extend(["-e", "KEYWORK_SANDBOX=1"])
    if repo_name:
        cmd.extend(["-e", f"REPO_NAME={repo_name}"])
    if goal_name:
        cmd.extend(["-e", f"GOAL_NAME={goal_name}"])

    # Pass through git identity from host
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"):
        val = os.environ.get(var)
        if val:
            cmd.extend(["-e", f"{var}={val}"])

    # Env file with static defaults
    env_file = SANDBOX_DIR / ".env"
    if env_file.exists():
        cmd.extend(["--env-file", str(env_file)])

    # Extra port forwarding
    if extra_ports:
        for port in extra_ports:
            cmd.extend(["-p", f"{port}:{port}"])

    # Caller-provided environment overrides
    if env_overrides:
        for key, val in env_overrides.items():
            cmd.extend(["-e", f"{key}={val}"])

    # Repo-specific sandbox config
    if repo_name:
        repo_config = _read_repo_config(repo_name)
        for key, val in repo_config.get("env_vars", {}).items():
            cmd.extend(["-e", f"{key}={val}"])
        for volume in repo_config.get("volumes", []):
            cmd.extend(["-v", volume])
        for port in repo_config.get("ports", []):
            cmd.extend(["-p", f"{port}:{port}"])

    # Image and command
    cmd.append(IMAGE_NAME)
    cmd.extend(["bash", script])
    if args:
        cmd.extend(args)

    return cmd, container_name


def _stream_output(process: subprocess.Popen, on_output: callable) -> None:
    """Stream process stdout lines to callback in a background thread."""
    try:
        for line in process.stdout:
            on_output(line.rstrip())
    except (ValueError, OSError):
        pass  # Process stdout closed


def launch_sandboxed(
    script: str,
    args: list[str] | None = None,
    repo_name: str = "",
    goal_name: str = "",
    interactive: bool = False,
    extra_ports: list[int] | None = None,
    env_overrides: dict[str, str] | None = None,
    on_output: callable | None = None,
) -> subprocess.Popen:
    """Launch a script inside the Docker sandbox.

    Returns the Popen handle for the docker run process. For non-interactive
    mode, stdout/stderr are piped and streamed via the on_output callback.
    For interactive mode, stdin/stdout/stderr are inherited.
    """
    cmd, container_name = build_sandbox_command(
        script=script,
        args=args,
        repo_name=repo_name,
        goal_name=goal_name,
        interactive=interactive,
        extra_ports=extra_ports,
        env_overrides=env_overrides,
    )

    _tracked_containers.append(container_name)

    if interactive:
        process = subprocess.Popen(cmd)
    else:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if on_output:
            thread = threading.Thread(
                target=_stream_output,
                args=(process, on_output),
                daemon=True,
            )
            thread.start()

    return process


def cleanup_containers() -> None:
    """Stop all sandbox containers started by this TUI session."""
    for name in list(_tracked_containers):
        try:
            subprocess.run(
                ["docker", "stop", name],
                capture_output=True,
                timeout=30,
            )
            logger.info("Stopped container %s", name)
        except subprocess.TimeoutExpired:
            logger.warning("Timeout stopping container %s", name)
        except OSError as e:
            logger.warning("Failed to stop container %s: %s", name, e)
    _tracked_containers.clear()


atexit.register(cleanup_containers)
