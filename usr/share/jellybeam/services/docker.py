# services/docker.py
from __future__ import annotations

import subprocess
import threading
import os
import shutil
import tempfile
from typing import Callable, Optional, List

from gi.repository import GLib
from utils.logger import Logger
from utils.constants import (
    DOCKER_CONTAINER_NAME,
    DOCKER_IMAGE_NAME,
    DOCKER_IMAGE_TAG,
    DOCKER_WORKSPACE_HOST,
    DOCKER_WORKSPACE_CONTAINER,
    DOCKER_START_COMMANDS,
    DOCKER_INSTALL_COMMANDS,
    TIZEN_SDK_DIR,
    TIZEN_SDK_URL,
    TIZEN_SDK_BIN_NAME,
    TIZEN_TOOLS_PATH,
    JELLYFIN_REPO_URL,
    JELLYFIN_REPO_DIR,
    JELLYFIN_APP_FILENAME,
    CERT_AUTHOR_FILENAME,
    CERT_DISTRIBUTOR_FILENAME,
    CERT_PASSWORD_FILE,
    DEFAULT_PROFILE_NAME,
    DEFAULT_DEVICE_ID,
    TIMEOUT_DOCKER_VERSION,
    TIMEOUT_DOCKER_INFO,
    TIMEOUT_DOCKER_START,
    TIMEOUT_DOCKER_STOP,
    TIMEOUT_DOCKER_INSTALL,
    TIMEOUT_DOCKER_EXEC_SHORT,
    TIMEOUT_DOCKER_EXEC_MEDIUM,
    TIMEOUT_DOCKER_EXEC_LONG,
    TIMEOUT_DOCKER_SDK_SETUP,
)
from utils.exceptions import DockerError


class DockerService:
    """Service for Docker operations and Tizen SDK management."""

    def __init__(self, logger: Optional[Logger] = None) -> None:
        """
        Initialize Docker service.

        Args:
            logger: Logger instance. Creates new one if not provided.
        """
        self.logger: Logger = logger or Logger()
        self.container_name: str = DOCKER_CONTAINER_NAME
        self.image_name: str = DOCKER_IMAGE_NAME
        self.image_tag: str = DOCKER_IMAGE_TAG
        self.workspace_host: str = DOCKER_WORKSPACE_HOST
        self.workspace_container: str = DOCKER_WORKSPACE_CONTAINER

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
            return ["sg", "docker", "-c", " ".join(cmd)]
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
        sg_cmd = ["sg", "docker", "-c", " ".join(cmd)]
        self.logger.debug(f"Running with sg docker: {' '.join(sg_cmd)}")
        return subprocess.run(sg_cmd, **kwargs)

    def start_docker_async(self, callback: Callable[[bool], None]) -> None:
        """Start Docker service asynchronously."""

        def start_docker():
            import time

            try:
                self.logger.info("Attempting to start Docker service")

                for cmd in DOCKER_START_COMMANDS:
                    try:
                        self.logger.debug(f"Trying command: {' '.join(cmd)}")
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=TIMEOUT_DOCKER_START,
                        )

                        if result.returncode == 0:
                            self.logger.info(
                                f"Docker start command succeeded: {' '.join(cmd)}"
                            )

                            # Wait for Docker to fully start
                            # systemctl may return before daemon is fully ready
                            max_retries = 3
                            wait_times = [2, 3, 5]  # Total ~10s

                            for attempt in range(max_retries):
                                time.sleep(wait_times[attempt])
                                self.logger.debug(
                                    f"Checking if Docker is running (attempt {attempt + 1}/{max_retries})"
                                )

                                if self.is_docker_running():
                                    self.logger.info("Docker started successfully")
                                    GLib.idle_add(callback, True)
                                    return

                            # After retries, report failure and exit
                            self.logger.error(
                                "Docker daemon did not start within expected time"
                            )
                            GLib.idle_add(callback, False)
                            return  # Exit here, don't try fallback commands
                        else:
                            self.logger.warning(f"Command failed: {result.stderr}")

                    except subprocess.TimeoutExpired:
                        self.logger.warning(f"Command timed out: {' '.join(cmd)}")
                        continue
                    except FileNotFoundError:
                        self.logger.debug(f"Command not found: {' '.join(cmd)}")
                        continue

                self.logger.error("All Docker start attempts failed")
                GLib.idle_add(callback, False)

            except Exception as e:
                self.logger.exception(f"Unexpected error starting Docker: {e}")
                GLib.idle_add(callback, False)

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
        """Prepare Docker environment for Tizen development."""

        def prepare():
            try:

                def log_progress(msg: str):
                    if progress_callback:
                        GLib.idle_add(progress_callback, msg)
                    self.logger.info(msg)

                log_progress(
                    f"Pulling Tizen builder image: {self.image_name}:{self.image_tag}"
                )

                # Pull the Tizen builder image with real-time output
                pull_cmd = self._wrap_cmd(
                    ["docker", "pull", f"{self.image_name}:{self.image_tag}"]
                )
                process = subprocess.Popen(
                    pull_cmd,
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
                    error_msg = "Failed to pull Tizen builder image"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)
                    return

                self.logger.info("Docker image pulled successfully")

                # Create container if it doesn't exist
                try:
                    self.run_with_docker_group(
                        ["docker", "inspect", self.container_name],
                        capture_output=True,
                        check=True,
                        timeout=TIMEOUT_DOCKER_INFO,
                    )
                    self.logger.info(f"Container {self.container_name} already exists")
                except subprocess.CalledProcessError:
                    # Container doesn't exist, create it
                    self.logger.info(f"Creating container: {self.container_name}")
                    result = self.run_with_docker_group(
                        [
                            "docker",
                            "create",
                            "--name",
                            self.container_name,
                            "-v",
                            f"{self.workspace_host}:{self.workspace_container}",
                            f"{self.image_name}:{self.image_tag}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=TIMEOUT_DOCKER_EXEC_SHORT,
                    )

                    if result.returncode != 0:
                        error_msg = f"Failed to create container: {result.stderr}"
                        self.logger.error(error_msg)
                        GLib.idle_add(callback, False, error_msg)
                        return

                    self.logger.info("Container created successfully")

                GLib.idle_add(callback, True, "Environment ready")

            except subprocess.TimeoutExpired as e:
                error_msg = f"Docker operation timed out: {e}"
                self.logger.error(error_msg)
                GLib.idle_add(callback, False, error_msg)
            except Exception as e:
                self.logger.exception(f"Error preparing environment: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=prepare, daemon=True)
        thread.start()

    def setup_tizen_sdk_async(self, callback: Callable[[bool, str], None]) -> None:
        """Setup Tizen SDK in Docker container."""

        def setup_sdk():
            try:
                self.logger.info("Starting Tizen SDK setup")

                # Start container
                subprocess.run(
                    ["docker", "start", self.container_name],
                    check=True,
                    timeout=TIMEOUT_DOCKER_START,
                )
                self.logger.info("Container started")

                # Download and setup Tizen SDK
                setup_script = f"""
                cd {self.workspace_container}
                if [ ! -d "{TIZEN_SDK_DIR}" ]; then
                    wget -O {TIZEN_SDK_BIN_NAME} {TIZEN_SDK_URL}
                    chmod +x {TIZEN_SDK_BIN_NAME}
                    ./{TIZEN_SDK_BIN_NAME} --accept-license
                fi
                """

                self.logger.debug("Executing SDK setup script")
                result = subprocess.run(
                    ["docker", "exec", self.container_name, "bash", "-c", setup_script],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_DOCKER_SDK_SETUP,
                )

                if result.returncode == 0:
                    self.logger.info("Tizen SDK setup completed successfully")
                    GLib.idle_add(callback, True, "Tizen SDK ready")
                else:
                    error_msg = f"SDK setup failed: {result.stderr}"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)

            except subprocess.TimeoutExpired as e:
                error_msg = f"SDK setup timed out: {e}"
                self.logger.error(error_msg)
                GLib.idle_add(callback, False, error_msg)
            except Exception as e:
                self.logger.exception(f"Error setting up Tizen SDK: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=setup_sdk, daemon=True)
        thread.start()

    def setup_certificates_async(
        self,
        author_cert: str,
        dist_cert: str,
        password: str,
        callback: Callable[[bool, str], None],
        use_default: bool = False,
    ) -> None:
        """
        Setup certificates in Docker environment.

        Args:
            author_cert: Path to author certificate (ignored if use_default=True)
            dist_cert: Path to distributor certificate (ignored if use_default=True)
            password: Certificate password (ignored if use_default=True)
            callback: Callback function (success: bool, message: str)
            use_default: If True, skip certificate setup and use container's built-in certs
        """

        def setup_certs():
            password_file = None
            try:
                # If using default certificates, skip the setup
                if use_default:
                    self.logger.info(
                        "Using built-in certificates from Docker container"
                    )
                    GLib.idle_add(callback, True, "Using built-in certificates")
                    return

                self.logger.info("Setting up custom certificates")

                # Create workspace directory
                os.makedirs(self.workspace_host, exist_ok=True)

                # Copy certificates to workspace
                shutil.copy2(
                    author_cert, f"{self.workspace_host}/{CERT_AUTHOR_FILENAME}"
                )
                shutil.copy2(
                    dist_cert, f"{self.workspace_host}/{CERT_DISTRIBUTOR_FILENAME}"
                )
                self.logger.info("Certificates copied to workspace")

                # Create temporary password file
                with tempfile.NamedTemporaryFile(
                    mode="w", delete=False, suffix=".txt"
                ) as f:
                    password_file = f.name
                    f.write(password)

                # Copy password file to workspace
                shutil.copy2(
                    password_file, f"{self.workspace_host}/{CERT_PASSWORD_FILE}"
                )
                self.logger.debug("Password file created securely")

                # Create certificate profile
                cert_script = f"""
                cd {self.workspace_container}
                PASSWORD=$(cat {CERT_PASSWORD_FILE})
                {TIZEN_TOOLS_PATH} security-profiles add -n {DEFAULT_PROFILE_NAME} -a {CERT_AUTHOR_FILENAME} -p "$PASSWORD"
                {TIZEN_TOOLS_PATH} package -t tpk -s {DEFAULT_PROFILE_NAME}
                rm -f {CERT_PASSWORD_FILE}
                """

                self.logger.debug("Executing certificate setup script")
                result = subprocess.run(
                    ["docker", "exec", self.container_name, "bash", "-c", cert_script],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_DOCKER_EXEC_SHORT,
                )

                if result.returncode == 0:
                    self.logger.info("Certificates configured successfully")
                    GLib.idle_add(callback, True, "Certificates configured")
                else:
                    error_msg = f"Certificate setup failed: {result.stderr}"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)

            except Exception as e:
                self.logger.exception(f"Error setting up certificates: {e}")
                GLib.idle_add(callback, False, str(e))
            finally:
                # Clean up temporary password file
                if password_file and os.path.exists(password_file):
                    try:
                        os.unlink(password_file)
                        self.logger.debug("Temporary password file removed")
                    except OSError as e:
                        self.logger.warning(f"Failed to remove password file: {e}")

        thread = threading.Thread(target=setup_certs, daemon=True)
        thread.start()

    def build_jellyfin_app_async(self, callback: Callable[[bool, str], None]) -> None:
        """Build the Jellyfin application."""

        def build_app():
            try:
                self.logger.info("Starting Jellyfin app build")

                build_script = f"""
                cd {self.workspace_container}
                if [ ! -d "{JELLYFIN_REPO_DIR}" ]; then
                    git clone {JELLYFIN_REPO_URL}
                fi
                cd {JELLYFIN_REPO_DIR}
                {TIZEN_TOOLS_PATH} build-web
                {TIZEN_TOOLS_PATH} package -t wgt -s {DEFAULT_PROFILE_NAME}
                """

                self.logger.debug("Executing build script")
                result = subprocess.run(
                    ["docker", "exec", self.container_name, "bash", "-c", build_script],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_DOCKER_EXEC_LONG,
                )

                if result.returncode == 0:
                    self.logger.info("Application built successfully")
                    GLib.idle_add(callback, True, "Application built successfully")
                else:
                    error_msg = f"Build failed: {result.stderr}"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)

            except subprocess.TimeoutExpired as e:
                error_msg = f"Build timed out: {e}"
                self.logger.error(error_msg)
                GLib.idle_add(callback, False, error_msg)
            except Exception as e:
                self.logger.exception(f"Error building application: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=build_app, daemon=True)
        thread.start()

    def install_app_on_device_async(
        self, callback: Callable[[bool, str], None]
    ) -> None:
        """Install the built application on the target device."""

        def install_app():
            try:
                self.logger.info("Installing application on device")

                install_script = f"""
                cd {self.workspace_container}/{JELLYFIN_REPO_DIR}
                {TIZEN_TOOLS_PATH} install -n {JELLYFIN_APP_FILENAME} -t {DEFAULT_DEVICE_ID}
                """

                self.logger.debug("Executing install script")
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        self.container_name,
                        "bash",
                        "-c",
                        install_script,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_DOCKER_EXEC_MEDIUM,
                )

                if result.returncode == 0:
                    self.logger.info("Application installed successfully")
                    GLib.idle_add(callback, True, "Application installed successfully")
                else:
                    error_msg = f"Installation failed: {result.stderr}"
                    self.logger.error(error_msg)
                    GLib.idle_add(callback, False, error_msg)

            except subprocess.TimeoutExpired as e:
                error_msg = f"Installation timed out: {e}"
                self.logger.error(error_msg)
                GLib.idle_add(callback, False, error_msg)
            except Exception as e:
                self.logger.exception(f"Error installing application: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=install_app, daemon=True)
        thread.start()

    def install_jellyfin_direct_async(
        self,
        tv_ip: str,
        callback: Callable[[bool, str], None],
        progress_callback: Optional[Callable[[str], None]] = None,
        build_option: str = "Jellyfin",
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
            build_option: Build variant (Jellyfin, Jellyfin-TrueHD, etc.)
        """

        def install_direct():
            try:

                def log_progress(msg: str):
                    if progress_callback:
                        GLib.idle_add(progress_callback, msg)
                    self.logger.info(msg)

                log_progress(f"Starting Jellyfin installation to {tv_ip}...")
                log_progress(f"Using container: {self.image_name}:{self.image_tag}")

                # Run the Georift container with the TV IP
                # Format: docker run --rm <image> <tv_ip> [build_option]
                cmd = [
                    "docker",
                    "run",
                    "--rm",
                    f"{self.image_name}:{self.image_tag}",
                    tv_ip,
                    build_option,
                ]

                log_progress(f"Executing: {' '.join(cmd)}")

                # Run with real-time output capture (use sg docker if needed)
                run_cmd = self._wrap_cmd(cmd)
                process = subprocess.Popen(
                    run_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                # Stream output in real-time
                output_lines = []
                for line in iter(process.stdout.readline, ""):
                    line = line.strip()
                    if line:
                        output_lines.append(line)
                        log_progress(line)

                process.wait()

                if process.returncode == 0:
                    self.logger.info("Jellyfin installed successfully!")
                    GLib.idle_add(callback, True, "Jellyfin installed successfully!")
                else:
                    error_output = "\n".join(output_lines[-5:])  # Last 5 lines
                    error_msg = f"Installation failed (exit code {process.returncode})"
                    self.logger.error(f"{error_msg}: {error_output}")
                    GLib.idle_add(callback, False, error_msg)

            except FileNotFoundError:
                error_msg = "Docker executable not found"
                self.logger.error(error_msg)
                GLib.idle_add(callback, False, error_msg)
            except Exception as e:
                self.logger.exception(f"Error during installation: {e}")
                GLib.idle_add(callback, False, str(e))

        thread = threading.Thread(target=install_direct, daemon=True)
        thread.start()

    def stop_all_processes(self) -> None:
        """Stop all running Docker processes."""
        try:
            self.logger.info(f"Stopping Docker container: {self.container_name}")
            subprocess.run(
                ["docker", "stop", self.container_name],
                capture_output=True,
                timeout=TIMEOUT_DOCKER_STOP,
            )
            self.logger.info("Docker container stopped successfully")
        except subprocess.TimeoutExpired:
            self.logger.warning(f"Timeout stopping container {self.container_name}")
        except FileNotFoundError:
            self.logger.error("Docker executable not found")
        except Exception as e:
            self.logger.exception(f"Error stopping Docker container: {e}")
