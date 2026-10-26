# services/docker.py
from __future__ import annotations

import ipaddress
import os
import shlex
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from gi.repository import GLib
from utils.i18n import _
from utils.logger import Logger
from utils.constants import (
    DOCKER_CONTAINER_NAME,
    DOCKER_IMAGE_NAME,
    DOCKER_IMAGE_TAG,
    DOCKER_WORKSPACE_HOST,
    DOCKER_WORKSPACE_CONTAINER,
    DOCKER_START_COMMANDS,
    PKEXEC_DISMISSED,
    PKEXEC_NOT_AUTHORIZED,
    DOCKER_INSTALL_COMMANDS,
    JELLYFIN_WWW_DIR,
    JELLYFIN_BUILDS_RELEASES,
    JELLYFIN_BUILD_DEFAULT,
    TIZEN_SIGN_PROFILE,
    CUSTOMIZATION_PKG_DIR,
    TIZEN_TOOLS_DIR,
    SDB_PORT,
    TIZEN_STRICT_CERT_VERSION,
    DEVICE_CERT_DIR,
    CERT_AUTHOR_FILENAME,
    CERT_DISTRIBUTOR_FILENAME,
    TIMEOUT_DOCKER_VERSION,
    TIMEOUT_DOCKER_INFO,
    TIMEOUT_DOCKER_START,
    TIMEOUT_DOCKER_STOP,
    TIMEOUT_DOCKER_INSTALL,
    TIMEOUT_DOCKER_EXEC_MEDIUM,
    TIMEOUT_DOCKER_EXEC_LONG,
)
from utils.config import ConfigManager
from utils.exceptions import (
    AppInstallError,
    CustomizationError,
    DockerError,
    InstallationCancelledError,
    SamsungCertificateError,
)
from services import customization


def checked_tv_ip(tv_ip: str) -> str:
    """The TV address as a plain dotted IPv4, else AppInstallError.

    It ends up inside shell scripts run in the container (sdb connect ...),
    and it comes from a text field and from a JSON file anyone can edit --
    "1.2.3.4; anything" must never reach a shell.
    """
    try:
        return str(ipaddress.IPv4Address(str(tv_ip).strip()))
    except ValueError as e:
        raise AppInstallError(str(tv_ip), "not a valid IPv4 address") from e


class DockerService:
    """Service for Docker operations and Tizen SDK management."""

    def __init__(
        self,
        logger: Optional[Logger] = None,
        config: Optional[ConfigManager] = None,
    ) -> None:
        """
        Initialize Docker service.

        Args:
            logger: Logger instance. Creates new one if not provided.
            config: Configuration manager, read for the customization step.
                Creates new one if not provided.
        """
        self.logger: Logger = logger or Logger()
        self.config: ConfigManager = config or ConfigManager()
        self.container_name: str = DOCKER_CONTAINER_NAME
        self.image_name: str = DOCKER_IMAGE_NAME
        self.image_tag: str = DOCKER_IMAGE_TAG
        # One per user: a shared /tmp path could be created first, or have
        # files swapped between download and signing, by another account.
        self.workspace_host: str = f"{DOCKER_WORKSPACE_HOST}-{os.getuid()}"
        self.workspace_container: str = DOCKER_WORKSPACE_CONTAINER
        # Containers and docker clients running now, so Cancel can stop them.
        self._runs: Dict[str, Tuple[subprocess.Popen, Optional[str]]] = {}
        self._runs_lock = threading.Lock()
        self._cancelled = threading.Event()

    def is_docker_installed(self) -> bool:
        """Check if Docker is installed."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_DOCKER_VERSION,
            )
            is_installed = result.returncode == 0
            if is_installed:
                self.logger.info("Docker is installed")
            else:
                self.logger.warning("Docker is not installed")
            return is_installed
        except subprocess.TimeoutExpired:
            self.logger.error("Docker version check timed out")
            return False
        except FileNotFoundError:
            self.logger.error("Docker executable not found")
            return False
        except Exception as e:
            self.logger.exception(f"Unexpected error checking Docker installation: {e}")
            return False

    def is_docker_running(self) -> bool:
        """Check if Docker daemon is running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_DOCKER_INFO,
            )
            if result.returncode == 0:
                self.logger.info("Docker daemon is running")
                return True

            # If failed, try with sg docker (for freshly added group membership)
            # This works even without logout/login after usermod -aG docker
            result = subprocess.run(
                ["sg", "docker", "-c", "docker info"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_DOCKER_INFO,
            )
            if result.returncode == 0:
                self.logger.info("Docker daemon is running (via sg docker)")
                return True

            self.logger.warning("Docker daemon is not running")
            return False
        except subprocess.TimeoutExpired:
            self.logger.error("Docker info check timed out")
            return False
        except FileNotFoundError:
            self.logger.error("Docker executable not found")
            return False
        except Exception as e:
            self.logger.exception(f"Unexpected error checking Docker status: {e}")
            return False

    def is_user_in_docker_group(self) -> bool:
        """Check if current user is in the docker group."""
        try:
            import grp
            import pwd

            username = pwd.getpwuid(os.getuid()).pw_name

            try:
                docker_group = grp.getgrnam("docker")
                is_member = username in docker_group.gr_mem

                # Also check if docker is the user's primary group
                user_info = pwd.getpwnam(username)
                if user_info.pw_gid == docker_group.gr_gid:
                    is_member = True

                if is_member:
                    self.logger.info(f"User '{username}' is in docker group")
                else:
                    self.logger.warning(f"User '{username}' is NOT in docker group")

                return is_member

            except KeyError:
                self.logger.warning("Docker group does not exist")
                return False

        except Exception as e:
            self.logger.exception(f"Error checking docker group membership: {e}")
            return False

    def add_user_to_docker_group_async(
        self, callback: Callable[[bool, str], None]
    ) -> None:
        """
        Add current user to docker group using pkexec (graphical sudo).

        Args:
            callback: Callback function (success: bool, message: str)
        """

        def add_to_group():
            try:
                import pwd

                username = pwd.getpwuid(os.getuid()).pw_name

                self.logger.info(f"Adding user '{username}' to docker group via pkexec")

                # Use pkexec for graphical password prompt
                result = subprocess.run(
                    ["pkexec", "usermod", "-aG", "docker", username],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode == 0:
                    self.logger.info(
                        f"User '{username}' added to docker group successfully"
                    )

                    # Now apply the group to the current session
                    # We use 'newgrp docker' but since it starts a new shell,
                    # we'll set an environment variable to signal the change
                    GLib.idle_add(
                        callback,
                        True,
                        f"Usuário '{username}' adicionado ao grupo docker.\n"
                        "O grupo foi aplicado para esta sessão.",
                    )
                else:
                    error_msg = (
                        result.stderr.strip() if result.stderr else "Operação cancelada"
                    )
                    self.logger.error(
                        f"Failed to add user to docker group: {error_msg}"
                    )
                    GLib.idle_add(
                        callback, False, f"Falha ao adicionar ao grupo: {error_msg}"
                    )

            except subprocess.TimeoutExpired:
                self.logger.error("pkexec command timed out")
                GLib.idle_add(callback, False, "Tempo limite excedido")
            except FileNotFoundError:
                self.logger.error("pkexec not found")
                GLib.idle_add(callback, False, "pkexec não encontrado")
            except Exception as e:
                self.logger.exception(f"Error adding user to docker group: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=add_to_group, daemon=True)
        thread.start()

    def _needs_sg(self) -> bool:
        """Check if we need 'sg docker' to run docker commands.

        Returns True if user is in the group on disk but the current
        process doesn't have the group in its supplementary groups yet
        (e.g. just added without re-login).
        """
        try:
            import grp

            docker_gid = grp.getgrnam("docker").gr_gid
            if docker_gid in os.getgroups():
                return False
            # User was added to group but process doesn't have it yet
            return self.is_user_in_docker_group()
        except (KeyError, Exception):
            return False

    def _wrap_cmd(self, cmd: List[str]) -> List[str]:
        """Wrap command with 'sg docker' if the current process lacks the group."""
        if self._needs_sg():
            # sg hands its argument to a shell: each word must arrive quoted,
            # or a multi-line script passed to "sh -c" is torn apart.
            return ["sg", "docker", "-c", shlex.join(cmd)]
        return cmd

    def run_with_docker_group(
        self, cmd: List[str], **kwargs
    ) -> subprocess.CompletedProcess:
        """
        Run a command with the docker group, even if user just joined.
        Uses 'sg docker' to run command with docker group privileges.

        Args:
            cmd: Command to run as list
            **kwargs: Additional arguments for subprocess.run

        Returns:
            CompletedProcess result
        """
        # If user is in docker group, run normally
        if self.is_user_in_docker_group():
            return subprocess.run(cmd, **kwargs)

        # Otherwise, try with sg docker (runs command with group privileges)
        # This works even if user was just added to group without logout
        sg_cmd = ["sg", "docker", "-c", shlex.join(cmd)]
        self.logger.debug(f"Running with sg docker: {shlex.join(sg_cmd)}")
        return subprocess.run(sg_cmd, **kwargs)

    def start_docker_async(self, callback: Callable[[bool, str], None]) -> None:
        """Start the Docker daemon, asking for authorisation graphically.

        Through pkexec rather than sudo. sudo wants a terminal: with the output
        captured its prompt went into a pipe, so launched from the menu nothing
        appeared on screen and the app hung until the timeout. pkexec puts up
        the desktop's own password dialog.

        The fallbacks are chained inside a single script so the user is asked
        for the password once, not once per attempt.
        """

        def start_docker():
            import time

            try:
                self.logger.info("Attempting to start Docker service")

                # `a || b || c`: first one that works wins, single prompt.
                script = " || ".join(
                    " ".join(cmd) for cmd in DOCKER_START_COMMANDS
                )
                self.logger.debug(f"pkexec script: {script}")

                result = subprocess.run(
                    ["pkexec", "sh", "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_DOCKER_START,
                )

                if result.returncode == PKEXEC_DISMISSED:
                    self.logger.info("Authorisation dialog dismissed by the user")
                    GLib.idle_add(
                        callback, False, _("Authorization was cancelled")
                    )
                    return
                if result.returncode == PKEXEC_NOT_AUTHORIZED:
                    self.logger.warning("pkexec refused: not authorised")
                    GLib.idle_add(
                        callback, False, _("Could not get administrator access")
                    )
                    return
                if result.returncode != 0:
                    erro = (result.stderr or "").strip()
                    self.logger.error(f"Docker start failed: {erro[:200]}")
                    GLib.idle_add(callback, False, _("Could not start Docker"))
                    return

                # systemctl returns before the daemon is actually accepting
                # connections, so the answer is polled rather than assumed.
                for espera in (2, 3, 5):
                    time.sleep(espera)
                    if self.is_docker_running():
                        self.logger.info("Docker started successfully")
                        GLib.idle_add(callback, True, "")
                        return

                self.logger.error("Docker daemon did not come up in time")
                GLib.idle_add(callback, False, _("Docker did not start in time"))

            except subprocess.TimeoutExpired:
                self.logger.error("Docker start timed out")
                GLib.idle_add(callback, False, _("Docker did not start in time"))
            except FileNotFoundError:
                # No polkit agent installed; sudo would not have worked either.
                self.logger.error("pkexec not found")
                GLib.idle_add(
                    callback,
                    False,
                    _("pkexec was not found. Start Docker manually."),
                )
            except Exception as e:
                self.logger.exception(f"Unexpected error starting Docker: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=start_docker, daemon=True)
        thread.start()

    def install_docker_async(
        self,
        distro: str,
        callback: Callable[[bool, str], None],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Install Docker for specific distribution asynchronously.

        Uses pkexec for a single graphical password prompt.
        Installs, enables, starts Docker and adds user to docker group.
        """

        def do_install():
            try:
                import pwd

                if distro not in DOCKER_INSTALL_COMMANDS:
                    GLib.idle_add(
                        callback, False, f"Unsupported distribution: {distro}"
                    )
                    return

                username = pwd.getpwuid(os.getuid()).pw_name

                def log_progress(msg: str):
                    if progress_callback:
                        GLib.idle_add(progress_callback, msg)
                    self.logger.info(msg)

                # Build a single shell script for pkexec (one password prompt)
                cmds = DOCKER_INSTALL_COMMANDS[distro]
                # Replace $USER and remove sudo (pkexec provides root)
                shell_lines = []
                for cmd_list in cmds:
                    resolved = [username if c == "$USER" else c for c in cmd_list]
                    # Strip leading 'sudo' since we run as root via pkexec
                    if resolved and resolved[0] == "sudo":
                        resolved = resolved[1:]
                    shell_lines.append(" ".join(resolved))

                # Also start Docker and ensure group exists
                shell_lines.append("systemctl start docker")
                script = " && ".join(shell_lines)

                log_progress(f"Installing Docker ({distro})...")
                self.logger.debug(f"pkexec script: {script}")

                process = subprocess.Popen(
                    ["pkexec", "sh", "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                for line in iter(process.stdout.readline, ""):
                    line = line.strip()
                    if line:
                        log_progress(line)

                process.wait()

                if process.returncode != 0:
                    error_msg = "Docker installation failed"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)
                    return

                log_progress("Docker installed and started successfully!")
                GLib.idle_add(callback, True, "Docker ready")

            except FileNotFoundError:
                error_msg = "pkexec not found"
                self.logger.error(error_msg)
                GLib.idle_add(callback, False, error_msg)
            except Exception as e:
                self.logger.exception(f"Error installing Docker: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=do_install, daemon=True)
        thread.start()

    def install_docker(self, distro: str) -> None:
        """Install Docker for specific distribution."""
        if distro not in DOCKER_INSTALL_COMMANDS:
            raise DockerError(f"Unsupported distribution: {distro}")

        self.logger.info(f"Installing Docker for {distro}")

        for cmd_list in DOCKER_INSTALL_COMMANDS[distro]:
            try:
                self.logger.info(f"Executing: {' '.join(cmd_list)}")
                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_DOCKER_INSTALL,
                )

                if result.returncode != 0:
                    self.logger.error(f"Command failed: {result.stderr}")
                    raise DockerError(
                        f"Failed to execute: {' '.join(cmd_list)}",
                        details={"stderr": result.stderr},
                    )

                self.logger.info(f"Command succeeded: {' '.join(cmd_list)}")

            except subprocess.TimeoutExpired:
                self.logger.error(f"Command timed out: {' '.join(cmd_list)}")
                raise DockerError(
                    f"Installation command timed out: {' '.join(cmd_list)}"
                )
            except FileNotFoundError:
                self.logger.error(f"Command not found: {cmd_list[0]}")
                raise DockerError(f"Command not found: {cmd_list[0]}")

        self.logger.info("Docker installation completed successfully")

    def prepare_environment_async(
        self,
        callback: Callable[[bool, str], None],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Pull the builder image, so the install steps start right away.

        It used to create a "jellybeam-builder" container as well. Nothing
        ever ran in it -- every step runs its own throwaway container -- and
        it was the one Cancel tried to stop.
        """

        def prepare():
            try:

                def log_progress(msg: str):
                    if progress_callback:
                        GLib.idle_add(progress_callback, msg)
                    self.logger.info(msg)

                self._cancelled.clear()
                log_progress(
                    f"Pulling Tizen builder image: {self.image_name}:{self.image_tag}"
                )
                codigo = self._stream(
                    ["docker", "pull", f"{self.image_name}:{self.image_tag}"],
                    log_progress,
                    TIMEOUT_DOCKER_INSTALL,
                )
                if codigo != 0:
                    self.logger.error("Failed to pull Tizen builder image")
                    GLib.idle_add(callback, False, _("Failed to pull Tizen builder image"))
                    return

                self.logger.info("Docker image pulled successfully")
                GLib.idle_add(callback, True, "Environment ready")

            except InstallationCancelledError:
                GLib.idle_add(callback, False, _("Installation cancelled"))
            except subprocess.TimeoutExpired:
                self.logger.error("Pulling the builder image timed out")
                GLib.idle_add(callback, False, _("Downloading the Docker image timed out"))
            except FileNotFoundError:
                GLib.idle_add(callback, False, _("Docker executable not found"))
            except Exception as e:
                self.logger.exception(f"Error preparing environment: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=prepare, daemon=True)
        thread.start()

    # ------------------------------------------------------------------
    # Running containers
    # ------------------------------------------------------------------

    def _new_name(self) -> str:
        """A unique container name, so the container can be killed by name."""
        return f"{self.container_name}-{uuid.uuid4().hex[:10]}"

    def _kill(self, process: subprocess.Popen, name: Optional[str]) -> None:
        """Stop a run: the container by name, then the docker client.

        Killing only the client leaves a --rm container running on its own.
        """
        if name:
            try:
                subprocess.run(
                    self._wrap_cmd(["docker", "kill", name]),
                    capture_output=True,
                    timeout=TIMEOUT_DOCKER_STOP,
                )
            except (subprocess.SubprocessError, OSError) as e:
                self.logger.debug(f"docker kill {name}: {e}")
        try:
            process.kill()
        except OSError:
            pass

    def _stream(
        self,
        cmd: List[str],
        log_progress: Callable[[str], None],
        timeout: int,
        name: Optional[str] = None,
        collect: Optional[List[str]] = None,
    ) -> int:
        """Run a docker command, streaming its output line by line.

        A timer enforces the timeout. Reading stdout to the end and only then
        calling wait(timeout) bounded nothing: a stalled sdb or wget never
        closes stdout, and the window spun forever. Cancel goes through the
        same kill.

        Raises InstallationCancelledError after Cancel, TimeoutExpired after
        the timeout; returns the exit code otherwise.
        """
        if self._cancelled.is_set():
            raise InstallationCancelledError()
        process = subprocess.Popen(
            self._wrap_cmd(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        chave = name or f"pid-{process.pid}"
        with self._runs_lock:
            self._runs[chave] = (process, name)
        expirou = threading.Event()

        def estourou() -> None:
            expirou.set()
            self._kill(process, name)

        timer = threading.Timer(timeout, estourou)
        timer.daemon = True
        timer.start()
        try:
            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if line:
                    if collect is not None:
                        collect.append(line)
                    log_progress(line)
            process.wait()
        finally:
            timer.cancel()
            with self._runs_lock:
                self._runs.pop(chave, None)
        if self._cancelled.is_set():
            raise InstallationCancelledError()
        if expirou.is_set():
            raise subprocess.TimeoutExpired(cmd, timeout)
        return process.returncode

    def _prepare_workspace(self) -> None:
        """Create the per-user workspace, private, and make sure it is ours."""
        os.makedirs(self.workspace_host, mode=0o700, exist_ok=True)
        info = os.lstat(self.workspace_host)
        if os.path.islink(self.workspace_host) or info.st_uid != os.getuid():
            raise AppInstallError(
                "", f"{self.workspace_host} belongs to someone else; remove it and retry"
            )
        os.chmod(self.workspace_host, 0o700)

    def _discard_certs(self) -> None:
        """Delete the rewrapped certificates once the install is over.

        They hold the user's private key under a password that also went
        through the install; nothing needs them after signing.
        """
        shutil.rmtree(os.path.join(self.workspace_host, DEVICE_CERT_DIR), ignore_errors=True)

    def _run_in_image(
        self,
        script: str,
        log_progress: Callable[[str], None],
        timeout: int = TIMEOUT_DOCKER_EXEC_LONG,
    ) -> int:
        """Run a shell script in the builder image with the workspace mounted.

        The image's entrypoint installs Jellyfin on its own, so it is replaced
        by a shell here: we need its tools (sdb, tizen, unzip) but our own
        sequence of steps.
        """
        name = self._new_name()
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "-v",
            f"{self.workspace_host}:{self.workspace_container}",
            "--entrypoint",
            "sh",
            f"{self.image_name}:{self.image_tag}",
            "-c",
            script,
        ]
        return self._stream(cmd, log_progress, timeout, name)

    # ------------------------------------------------------------------
    # Installing
    # ------------------------------------------------------------------

    def install_jellyfin_direct_async(
        self,
        tv_ip: str,
        callback: Callable[[bool, str], None],
        progress_callback: Optional[Callable[[str], None]] = None,
        build_option: str = JELLYFIN_BUILD_DEFAULT,
        cert_password: str = "",
    ) -> None:
        """
        Install Jellyfin directly using the Georift container.

        This is the simplified installation method that:
        1. Pulls the pre-built WGT from jellyfin-tizen-builds
        2. Connects to the TV via SDB
        3. Installs the app directly

        Args:
            tv_ip: IP address of the Samsung TV
            callback: Callback function (success: bool, message: str)
            progress_callback: Optional callback for progress updates
            build_option: Published variant to install; see
                JELLYFIN_BUILD_DEFAULT.
        """

        def install_direct():
            try:

                def log_progress(msg: str):
                    if progress_callback:
                        GLib.idle_add(progress_callback, msg)
                    self.logger.info(msg)

                self._cancelled.clear()
                ip = checked_tv_ip(tv_ip)
                log_progress(f"Starting Jellyfin installation to {ip}...")
                log_progress(f"Using container: {self.image_name}:{self.image_tag}")

                par = self.device_certificate(log_progress, cert_password, ip)
                certs, senha = par if par else (None, "")

                name = self._new_name()
                cmd = ["docker", "run", "--rm", "--name", name]
                if certs:
                    # The image signs with these when both files are present
                    # and a password arrives as the fourth argument.
                    cmd += [
                        "-v", f"{certs}/{CERT_AUTHOR_FILENAME}:/certificates/author.p12",
                        "-v",
                        f"{certs}/{CERT_DISTRIBUTOR_FILENAME}:/certificates/distributor.p12",
                    ]
                cmd += [f"{self.image_name}:{self.image_tag}", ip, build_option]
                if certs:
                    # Third argument is the release URL; empty means latest.
                    cmd += ["", senha]

                # The password goes to the log masked: this line is shown in
                # the window, copied with "Copy log" and kept in the log file.
                visivel = ["***" if senha and arg == senha else arg for arg in cmd]
                log_progress(f"Executing: {shlex.join(visivel)}")

                output_lines: List[str] = []
                codigo = self._stream(
                    cmd, log_progress, TIMEOUT_DOCKER_INSTALL, name, collect=output_lines
                )

                if codigo == 0:
                    self.logger.info("Jellyfin installed successfully!")
                    GLib.idle_add(callback, True, _("Jellyfin installed successfully!"))
                else:
                    error_output = "\n".join(output_lines[-5:])  # Last 5 lines
                    self.logger.error(
                        f"Installation failed (exit code {codigo}): {error_output}"
                    )
                    GLib.idle_add(
                        callback, False, _("Installation failed (exit code {code})").format(code=codigo)
                    )

            except InstallationCancelledError:
                GLib.idle_add(callback, False, _("Installation cancelled"))
            except AppInstallError as e:
                self.logger.error(str(e))
                GLib.idle_add(callback, False, e.details.get("reason", e.message))
            except subprocess.TimeoutExpired:
                GLib.idle_add(callback, False, _("Installation timed out"))
            except FileNotFoundError:
                self.logger.error("Docker executable not found")
                GLib.idle_add(callback, False, _("Docker executable not found"))
            except Exception as e:
                self.logger.exception(f"Error during installation: {e}")
                GLib.idle_add(callback, False, str(e))
            finally:
                self._discard_certs()

        thread = threading.Thread(target=install_direct, daemon=True)
        thread.start()

    def device_certificate(
        self, log_progress: Callable[[str], None], password: str = "", tv_ip: str = ""
    ) -> Optional[Tuple[str, str]]:
        """The user's own signing certificate, when they have supplied one.

        Returns (directory holding author.p12 and distributor.p12, password),
        or None to install the package as published.

        There is deliberately no certificate generated here. A self-signed
        pair does not work: the TV validates the chain against roots baked
        into its firmware, and that trust store cannot be written to. An
        earlier attempt generated one and a Tizen 9 TV refused it with the
        same error as before -- the certificate has to be issued by Samsung,
        against the user's own account, with their TV's id registered.

        So the app carries the certificate the user provides rather than
        pretending it can mint one.
        """
        if self.config.get("certificates.use_default", True):
            return None

        autor = self.config.get("certificates.author_cert_path", "")
        dist = self.config.get("certificates.distributor_cert_path", "")
        # The password arrives as an argument, never from the config file: it
        # is a credential and that file is plain JSON on disk.
        senha = password

        if not (autor and dist):
            return None
        if not (os.path.isfile(autor) and os.path.isfile(dist)):
            # Not a silent fall back to the published package: on Tizen 8+
            # that fails only at the very end, far from the actual cause.
            faltando = ", ".join(p for p in (autor, dist) if not os.path.isfile(p))
            raise AppInstallError(tv_ip, f"certificate file not found: {faltando}")

        self._prepare_workspace()
        destino = os.path.join(self.workspace_host, DEVICE_CERT_DIR)
        os.makedirs(destino, mode=0o700, exist_ok=True)
        # Not copied: rewrapped. The CLI in the container only opens legacy
        # PKCS#12, and it misreads a password that happens to be valid base64
        # (see safe_password). Rewrapping with a password of our own makes
        # both problems impossible whatever the user brought -- and a wrong
        # user password fails right here, with a message, instead of as an
        # "Author password:" prompt inside an unattended install.
        from services.samsung_cert import rewrap_p12, safe_password

        senha_assinatura = safe_password()
        try:
            rewrap_p12(Path(autor), senha, Path(destino) / CERT_AUTHOR_FILENAME, senha_assinatura)
            try:
                rewrap_p12(
                    Path(dist), senha, Path(destino) / CERT_DISTRIBUTOR_FILENAME, senha_assinatura
                )
            except SamsungCertificateError:
                if not senha:
                    raise
                # A distributor certificate often carries no password at all.
                rewrap_p12(
                    Path(dist), "", Path(destino) / CERT_DISTRIBUTOR_FILENAME, senha_assinatura
                )
        except SamsungCertificateError as e:
            raise AppInstallError(tv_ip, e.details.get("reason", str(e))) from e
        log_progress("Signing with your own certificate...")
        return destino, senha_assinatura

    def install_jellyfin_customized_async(
        self,
        tv_ip: str,
        server_url: str,
        callback: Callable[[bool, str], None],
        progress_callback: Optional[Callable[[str], None]] = None,
        build_option: str = JELLYFIN_BUILD_DEFAULT,
        cert_password: str = "",
    ) -> None:
        """Install a pre-built package with the server customizations added.

        The image normally downloads a ready-made .wgt and installs it, which
        leaves no place to inject anything. A .wgt is just a zip, so we unpack
        it, edit www/index.html, and sign it again with the image's own 'dev'
        profile -- no certificate needed from the user.

        Three steps rather than one, because the injection runs on the host:
        it is the tested Python in services/customization.py, and the image has
        no Python at all.
        """

        def install():
            try:

                def log_progress(msg: str):
                    if progress_callback:
                        GLib.idle_add(progress_callback, msg)
                    self.logger.info(msg)

                self._cancelled.clear()
                ip = checked_tv_ip(tv_ip)
                self._prepare_workspace()
                ws = self.workspace_container
                pkg = f"{ws}/{CUSTOMIZATION_PKG_DIR}"

                log_progress("Downloading the pre-built package...")
                if self._run_in_image(
                    fetch_script(ws, build_option), log_progress, TIMEOUT_DOCKER_INSTALL
                ) != 0:
                    GLib.idle_add(
                        callback, False, _("Could not download the Jellyfin package")
                    )
                    return

                www = os.path.join(
                    self.workspace_host, CUSTOMIZATION_PKG_DIR, JELLYFIN_WWW_DIR
                )
                resources = customization.inject(www, server_url)
                log_progress(f"Injected {len(resources)} customization resource(s)")
                customization.replace_icon(
                    os.path.join(self.workspace_host, CUSTOMIZATION_PKG_DIR)
                )
                log_progress("Replaced the launcher icon with the square one")
                pkg_host = os.path.join(self.workspace_host, CUSTOMIZATION_PKG_DIR)
                marca = customization.replace_branding(pkg_host)
                log_progress(f"Replaced {len(marca)} Jellyfin logo file(s) with our symbol")
                versao = customization.set_package_version(pkg_host)
                log_progress(f"Package version: {versao}")
                customization.install_tv_scripts(pkg_host)
                log_progress(
                    "TV scripts: 1080p version preselected on Full HD sets, "
                    "search waits for typing to pause, episode paused under "
                    "\"Are you still watching?\""
                )
                if customization.patch_avplay(pkg_host):
                    log_progress(
                        "Native player: video ratio kept, subtitles drawn, "
                        "4K on UHD sets, screen saver held off"
                    )
                else:
                    log_progress("Native player not patched (not present or changed)")

                par = self.device_certificate(log_progress, cert_password, ip)
                certs, senha = par if par else (None, "")

                log_progress("Signing and installing...")
                script = install_script(ws, pkg, ip, senha if certs else None)
                if self._run_in_image(script, log_progress, TIMEOUT_DOCKER_INSTALL) != 0:
                    GLib.idle_add(callback, False, _("Installation failed"))
                    return

                GLib.idle_add(
                    callback, True, _("Jellyfin installed with your customizations!")
                )

            except InstallationCancelledError:
                GLib.idle_add(callback, False, _("Installation cancelled"))
            except AppInstallError as e:
                self.logger.error(str(e))
                GLib.idle_add(callback, False, e.details.get("reason", e.message))
            except CustomizationError as e:
                self.logger.error(f"Customization failed: {e}")
                GLib.idle_add(callback, False, str(e))
            except subprocess.TimeoutExpired:
                GLib.idle_add(callback, False, _("Installation timed out"))
            except FileNotFoundError:
                GLib.idle_add(callback, False, _("Docker executable not found"))
            except Exception as e:
                self.logger.exception(f"Error during installation: {e}")
                GLib.idle_add(callback, False, str(e))
            finally:
                self._discard_certs()

        threading.Thread(target=install, daemon=True).start()

    def _sdb_query(self, tv_ip: str, command: str) -> str:
        """Run one sdb command against the TV from the image; '' on failure."""
        try:
            ip = checked_tv_ip(tv_ip)
        except AppInstallError:
            return ""
        script = (
            f"export PATH={TIZEN_TOOLS_DIR}:$PATH; "
            f"sdb connect {ip} >/dev/null 2>&1; sleep 1; "
            f"sdb -s {ip}:{SDB_PORT} {command} 2>/dev/null"
        )
        try:
            r = subprocess.run(
                self._wrap_cmd(
                    [
                        "docker", "run", "--rm", "--network", "host",
                        "--entrypoint", "sh",
                        f"{self.image_name}:{self.image_tag}", "-c", script,
                    ]
                ),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_DOCKER_EXEC_MEDIUM,
            )
            return (r.stdout or "").strip()
        except Exception as e:
            self.logger.debug(f"sdb {command} failed: {e}")
            return ""

    def platform_version(self, tv_ip: str) -> str:
        """The TV's Tizen version, or empty string. Blocking; call off the UI."""
        for linha in self._sdb_query(tv_ip, "capability").splitlines():
            if linha.startswith("platform_version:"):
                return linha.split(":", 1)[1].strip()
        return ""

    def read_duid(self, tv_ip: str) -> str:
        """The TV's device id, or empty string.

        Answered by a whitelisted sdb command that works even though these
        sets refuse a shell. It is what the distributor certificate has to
        name, and what Samsung's Certificate Manager asks people to paste in.
        """
        return self._sdb_query(tv_ip, "shell 0 getduid")

    def needs_own_certificate(self, version: str) -> bool:
        """Whether this Tizen refuses the published package's expired chain.

        Tizen 8 began enforcing the signing chain's validity dates. Earlier
        versions install the published package happily, so they are left on
        the faster path.
        """
        try:
            return int(version.split(".")[0]) >= TIZEN_STRICT_CERT_VERSION
        except (ValueError, IndexError, AttributeError):
            # Unknown version: assume the lenient path, which is what every
            # TV did before Tizen 8 and what most in the wild still do.
            return False

    def tv_platform_version_async(
        self, tv_ip: str, callback: Callable[[str], None]
    ) -> None:
        """Read the TV's Tizen version, empty string when unavailable.

        Only sdb knows this: the TV's HTTP interface answers
        firmwareVersion "Unknown". Developer Mode therefore has to be on,
        which it is by the time this matters.

        Worth showing because the version decides whether the published
        package installs at all: Tizen 8 enforces the certificate chain
        expiry and rejects it, while 6.x and 7.x accept it.
        """

        def run() -> None:
            GLib.idle_add(callback, self.platform_version(tv_ip))

        threading.Thread(target=run, daemon=True).start()

    def stop_all_processes(self) -> None:
        """Cancel what is running: our containers by name, and their clients.

        It used to "docker stop jellybeam-builder", a container no install
        ever ran in, so Cancel stopped nothing.
        """
        self._cancelled.set()
        with self._runs_lock:
            em_curso = list(self._runs.values())
        for process, name in em_curso:
            self.logger.info(f"Stopping {name or 'docker'} (pid {process.pid})")
            self._kill(process, name)


def fetch_script(ws: str, build_option: str) -> str:
    """Shell script: download the latest published package and unpack it."""
    return f"""set -e
cd {ws}
rm -rf {CUSTOMIZATION_PKG_DIR} && mkdir {CUSTOMIZATION_PKG_DIR}
# The last Location header is the release page; a redirect chain has several.
TAG=$(basename "$(curl -sLI {JELLYFIN_BUILDS_RELEASES}/latest \\
  | grep -i '^location:' | tail -n 1 | sed 's/^[Ll]ocation: //' | tr -d '\\r')")
if [ -z "$TAG" ] || [ "$TAG" = "latest" ]; then
    echo "Could not find the latest release of {build_option}"
    exit 1
fi
echo "Release: $TAG"
wget -nv "{JELLYFIN_BUILDS_RELEASES}/download/$TAG/{build_option}.wgt" -O original.wgt
cd {CUSTOMIZATION_PKG_DIR} && unzip -qo ../original.wgt
# The image runs as root; hand the files back so the injection step can
# write to them as the desktop user.
chown -R {os.getuid()}:{os.getgid()} {ws}
echo "Package unpacked"
"""


def install_script(ws: str, pkg: str, ip: str, cert_password: Optional[str]) -> str:
    """Shell script: sign the edited package and install it on the TV.

    cert_password is set when the user's own certificate was rewrapped into
    the workspace (it is safe_password(): letters, digits and one '.');
    None signs with the image's 'dev' profile.
    """
    if cert_password is not None:
        # A profile pointing at the rewrapped pair. The built-in 'dev' profile
        # signs with the image's own certificate, which expired in 2022 and is
        # exactly what Tizen 8+ refuses. Inserted once, after the first
        # profile, under a name we pick.
        perfil = "custom"
        prep = f"""set -e
cp /home/developer/profile.xml /tmp/p.xml
sed -i 's|<profile name="[^"]*">|<profile name="{perfil}">|' /tmp/p.xml
sed -i 's|/certificates/|{ws}/{DEVICE_CERT_DIR}/|g' /tmp/p.xml
sed -i 's/_CERTIFICATEPASSWORD_/{cert_password}/' /tmp/p.xml
sed -i '0,/<\\/profile>/{{/<\\/profile>/ r /tmp/p.xml
}}' /home/developer/tizen-studio-data/profile/profiles.xml
set +e
"""
    else:
        perfil = TIZEN_SIGN_PROFILE
        prep = ""

    serial = f"{ip}:{SDB_PORT}"
    return prep + f"""cd {pkg} || exit 1
# The old signatures no longer match the edited files.
rm -f author-signature.xml signature1.xml
cd {ws} || exit 1
tizen package -t wgt -s {perfil} -- {CUSTOMIZATION_PKG_DIR} || exit 1
WGT=$(ls {pkg}/*.wgt | head -1)
echo "Signed: $WGT"
sdb connect {ip}
# The name sdb lists for this TV, whatever hyphens or dots it has.
TV_NAME=$(sdb devices | awk -v s="{serial}" '$1 == s && $2 == "device" {{ $1 = ""; $2 = ""; sub(/^ +/, ""); print }}')
if [ -z "$TV_NAME" ]; then
    echo "Could not connect to the TV at {serial}."
    echo "Check that Developer Mode on the TV has this computer's IP as Host PC IP."
    exit 1
fi
echo "Found TV: $TV_NAME"

# tee keeps the output streaming to the user while letting us inspect it.
try_install() {{
    tizen install -n "$WGT" -t "$TV_NAME" 2>&1 | tee /tmp/install.log
    grep -q "successfully installed" /tmp/install.log
}}

if ! try_install; then
    # Tizen refuses to update an app unless the new package carries the same
    # author certificate. The published package is signed by whoever built it,
    # and ours is re-signed here, so the first customized install always
    # collides. Removing the old one is the only way through.
    if grep -q "Author certificate not match" /tmp/install.log; then
        PKGID=$(grep -o 'package="[^"]*"' {pkg}/config.xml | head -1 | cut -d'"' -f2)
        echo ""
        echo "The installed app was signed by a different author."
        echo "Removing it before installing the customized package."
        echo "(Settings stored inside the TV app will be lost.)"
        if [ -z "$PKGID" ]; then echo "Could not read the package id"; exit 1; fi
        # sdb, not "tizen uninstall": the latter answers "The package is not
        # exist" for a package that is plainly installed and that sdb removes
        # without complaint.
        sdb -s {serial} uninstall "$PKGID" 2>&1 | tee /tmp/uninstall.log
        if ! grep -q "uninstall completed" /tmp/uninstall.log; then
            echo "Could not remove the installed app"
            exit 1
        fi
        try_install || exit 1
    else
        exit 1
    fi
fi
"""
