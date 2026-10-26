# tests/services/test_docker.py
"""Tests for Docker service."""

import os
import threading

import pytest
from unittest.mock import Mock, patch
import subprocess

from services.docker import DockerService
from utils.exceptions import DockerError


class TestDockerService:
    """Tests for DockerService class."""

    @pytest.fixture
    def docker_service(self):
        """Create a DockerService instance with a mock logger."""
        mock_logger = Mock()
        return DockerService(logger=mock_logger)

    def test_init_default_logger(self):
        """Test initialization with default logger."""
        service = DockerService()
        assert service.logger is not None
        assert service.container_name is not None
        assert service.image_name is not None

    def test_init_custom_logger(self, docker_service):
        """Test initialization with custom logger."""
        assert docker_service.logger is not None

    @patch("subprocess.run")
    def test_is_docker_installed_true(self, mock_run, docker_service):
        """Test Docker installation check when installed."""
        mock_run.return_value = Mock(returncode=0)
        assert docker_service.is_docker_installed() is True
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_is_docker_installed_false(self, mock_run, docker_service):
        """Test Docker installation check when not installed."""
        mock_run.return_value = Mock(returncode=1)
        assert docker_service.is_docker_installed() is False

    @patch("subprocess.run")
    def test_is_docker_installed_timeout(self, mock_run, docker_service):
        """Test Docker installation check on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        assert docker_service.is_docker_installed() is False

    @patch("subprocess.run")
    def test_is_docker_installed_not_found(self, mock_run, docker_service):
        """Test Docker installation check when docker not found."""
        mock_run.side_effect = FileNotFoundError()
        assert docker_service.is_docker_installed() is False

    @patch("subprocess.run")
    def test_is_docker_running_true(self, mock_run, docker_service):
        """Test Docker running check when running."""
        mock_run.return_value = Mock(returncode=0)
        assert docker_service.is_docker_running() is True

    @patch("subprocess.run")
    def test_is_docker_running_false(self, mock_run, docker_service):
        """Test Docker running check when not running."""
        mock_run.return_value = Mock(returncode=1)
        assert docker_service.is_docker_running() is False

    @patch("subprocess.run")
    def test_is_docker_running_timeout(self, mock_run, docker_service):
        """Test Docker running check on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=5)
        assert docker_service.is_docker_running() is False

    @patch("subprocess.run")
    def test_stop_all_processes_with_nothing_running(self, mock_run, docker_service):
        """Cancel with no run in progress touches nothing and does not raise."""
        docker_service.stop_all_processes()
        mock_run.assert_not_called()

    def test_install_docker_unsupported_distro(self, docker_service):
        """Test Docker installation for unsupported distribution."""
        with pytest.raises(DockerError):
            docker_service.install_docker("unsupported_distro")


class TestDockerServiceAsync:
    """Tests for DockerService async methods."""

    @pytest.fixture
    def docker_service(self):
        """Create a DockerService instance with a mock logger."""
        mock_logger = Mock()
        return DockerService(logger=mock_logger)

    @patch("subprocess.run")
    @patch("services.docker.GLib")
    def test_start_docker_async_success(self, mock_glib, mock_run, docker_service):
        """Test starting Docker asynchronously."""
        mock_run.return_value = Mock(returncode=0)
        mock_callback = Mock()

        # Call the async method
        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()
        docker_service.start_docker_async(mock_callback)
        done.wait(timeout=2)

    @patch("subprocess.run")
    @patch("services.docker.GLib")
    def test_start_docker_asks_through_pkexec_not_sudo(
        self, mock_glib, mock_run, docker_service
    ):
        """The reported bug: sudo's prompt went to a pipe and never showed.

        sudo needs a terminal. Captured, its prompt is invisible and the app
        hangs; pkexec puts up the desktop's own dialog instead.
        """
        mock_run.return_value = Mock(returncode=0, stderr="")
        done = threading.Event()
        mock_glib.idle_add.side_effect = lambda fn, *a, **kw: done.set()

        docker_service.start_docker_async(Mock())
        done.wait(timeout=2)

        chamadas = [c.args[0] for c in mock_run.call_args_list if c.args]
        primeira = chamadas[0]
        assert primeira[0] == "pkexec", primeira
        assert "sudo" not in primeira, primeira
        # One prompt, not one per fallback.
        assert primeira[1:3] == ["sh", "-c"]
        assert "||" in primeira[3]

    @patch("subprocess.run")
    @patch("services.docker.GLib")
    def test_start_docker_says_when_the_dialog_is_dismissed(
        self, mock_glib, mock_run, docker_service
    ):
        """Cancelling the password dialog must explain itself, not fail mutely."""
        mock_run.return_value = Mock(returncode=126, stderr="")
        recebido = []
        done = threading.Event()

        def capture(fn, *a, **kw):
            recebido.append(a)
            done.set()

        mock_glib.idle_add.side_effect = capture
        docker_service.start_docker_async(Mock())
        done.wait(timeout=2)

        assert recebido, "callback never ran"
        ok, mensagem = recebido[0][0], recebido[0][1]
        assert ok is False
        assert mensagem, "a dismissed dialog must come with a reason"

    @patch("subprocess.run", side_effect=FileNotFoundError)
    @patch("services.docker.GLib")
    def test_start_docker_survives_missing_pkexec(
        self, mock_glib, mock_run, docker_service
    ):
        """No polkit agent is a plausible setup; it must not raise."""
        recebido = []
        done = threading.Event()

        def capture(fn, *a, **kw):
            recebido.append(a)
            done.set()

        mock_glib.idle_add.side_effect = capture
        docker_service.start_docker_async(Mock())
        done.wait(timeout=2)

        assert recebido and recebido[0][0] is False

    @patch("services.docker.GLib")
    def test_prepare_environment_only_pulls(self, mock_glib, docker_service):
        """The image is pulled; no idle "jellybeam-builder" container is created."""
        corridas = []
        resultado = []
        done = threading.Event()

        def stream(cmd, *a, **kw):
            corridas.append(cmd)
            return 0

        def idle(fn, *args):
            resultado.append(args)
            done.set()

        mock_glib.idle_add.side_effect = idle
        with patch.object(docker_service, "_stream", side_effect=stream):
            docker_service.prepare_environment_async(Mock())
            assert done.wait(timeout=2)
        assert corridas == [["docker", "pull", f"{docker_service.image_name}:{docker_service.image_tag}"]]
        assert resultado[-1][0] is True


class TestCertificateDecision:
    """Only Tizen 8+ gets its own certificate.

    Earlier versions install the published package as published, which is
    faster and long proven. Generating a certificate for them would change
    a working path for no gain.
    """

    @pytest.fixture
    def docker_service(self, mock_logger):
        return DockerService(logger=mock_logger)

    @pytest.mark.parametrize("version", ["6.5", "7.0", "7.6"])
    def test_older_tizen_uses_the_published_package(self, version, docker_service):
        assert docker_service.needs_own_certificate(version) is False

    @pytest.mark.parametrize("version", ["8.0", "9.0", "10.1"])
    def test_tizen_8_and_newer_need_their_own(self, version, docker_service):
        # 10.1 matters: compared as text it sorts below "8".
        assert docker_service.needs_own_certificate(version) is True

    @pytest.mark.parametrize("version", ["", None, "unknown", "x.y"])
    def test_unreadable_version_keeps_the_old_path(self, version, docker_service):
        # Guessing "needs a certificate" here would break every TV whose
        # version we simply failed to read.
        assert docker_service.needs_own_certificate(version) is False


class TestTvIp:
    """The TV address reaches shell scripts; only a plain IPv4 gets through."""

    @pytest.mark.parametrize("valor", ["192.168.68.112", " 10.0.0.5 "])
    def test_plain_ipv4(self, valor):
        from services.docker import checked_tv_ip

        assert checked_tv_ip(valor) == valor.strip()

    @pytest.mark.parametrize(
        "valor", ["", "1.2.3.4; rm -rf ~", "1.2.3.4 && x", "$(id)", "fe80::1%eth0", "999.1.1.1", None]
    )
    def test_anything_else_is_refused(self, valor):
        from services.docker import checked_tv_ip
        from utils.exceptions import AppInstallError

        with pytest.raises(AppInstallError):
            checked_tv_ip(valor)

    def test_version_and_duid_reads_never_run_with_a_bad_ip(self, mock_logger):
        service = DockerService(logger=mock_logger)
        with patch("subprocess.run") as run:
            assert service.platform_version("1.1.1.1; reboot") == ""
            assert service.read_duid("$(id)") == ""
        run.assert_not_called()


class TestSgWrapping:
    def test_words_reach_sg_quoted(self, mock_logger):
        """A multi-line script for "sh -c" must arrive as one argument."""
        import shlex

        service = DockerService(logger=mock_logger)
        cmd = ["docker", "run", "--rm", "img", "-c", "set -e\necho 'a b'\n"]
        with patch.object(service, "_needs_sg", return_value=True):
            wrapped = service._wrap_cmd(cmd)
        assert wrapped[:3] == ["sg", "docker", "-c"]
        assert shlex.split(wrapped[3]) == cmd


class TestStream:
    """Timeout and Cancel actually stop a run (measured with real processes)."""

    @pytest.fixture
    def service(self, mock_logger):
        s = DockerService(logger=mock_logger)
        with patch.object(s, "_needs_sg", return_value=False):
            yield s

    def test_output_and_exit_code(self, service):
        linhas = []
        assert service._stream(["sh", "-c", "echo um; echo dois; exit 3"], linhas.append, 10) == 3
        assert linhas == ["um", "dois"]

    def test_a_silent_hang_is_killed_at_the_timeout(self, service):
        import time

        inicio = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            service._stream(["sleep", "30"], lambda _l: None, 1)
        assert time.monotonic() - inicio < 10

    def test_cancel_kills_the_run(self, service):
        from utils.exceptions import InstallationCancelledError

        erro = []

        def roda():
            try:
                service._stream(["sleep", "30"], lambda _l: None, 60)
            except Exception as e:  # noqa: BLE001 - recorded for the assert
                erro.append(e)

        t = threading.Thread(target=roda)
        t.start()
        for _ in range(50):
            if service._runs:
                break
            threading.Event().wait(0.05)
        service.stop_all_processes()
        t.join(10)
        assert not t.is_alive()
        assert isinstance(erro[0], InstallationCancelledError)

    def test_named_runs_are_killed_by_name(self, service):
        """Killing the docker client alone leaves a --rm container running."""
        processo = Mock()
        with patch("subprocess.run") as run:
            service._kill(processo, "jellybeam-builder-abc")
        assert run.call_args[0][0] == ["docker", "kill", "jellybeam-builder-abc"]
        processo.kill.assert_called_once()


class TestDirectInstallLog:
    @patch("services.docker.GLib")
    def test_the_signing_password_never_reaches_the_log(self, mock_glib, mock_logger, tmp_path):
        service = DockerService(logger=mock_logger)
        service.workspace_host = str(tmp_path)
        mostrado = []
        rodado = []
        done = threading.Event()

        def idle(fn, *args):
            if fn is progress:
                mostrado.append(args[0])
            else:
                done.set()

        def progress(msg):
            pass

        mock_glib.idle_add.side_effect = idle

        def stream(cmd, log, timeout, name=None, collect=None):
            rodado.append(cmd)
            return 0

        with patch.object(service, "device_certificate", return_value=(str(tmp_path), "Segr3do.Xyz")), \
                patch.object(service, "_stream", side_effect=stream):
            service.install_jellyfin_direct_async("192.168.68.112", Mock(), progress_callback=progress)
            assert done.wait(timeout=2)
        assert "Segr3do.Xyz" in rodado[0]  # the image needs it as an argument
        juntado = "\n".join(mostrado) + str(mock_logger.info.call_args_list)
        assert "Segr3do.Xyz" not in juntado
        assert "***" in juntado


class TestCertificates:
    @pytest.fixture
    def service(self, mock_logger, tmp_path):
        config = Mock()
        valores = {
            "certificates.use_default": False,
            "certificates.author_cert_path": str(tmp_path / "author.p12"),
            "certificates.distributor_cert_path": str(tmp_path / "distributor.p12"),
        }
        config.get.side_effect = lambda k, d=None: valores.get(k, d)
        s = DockerService(logger=mock_logger, config=config)
        s.workspace_host = str(tmp_path / "ws")
        return s

    def test_missing_files_are_an_error_not_a_silent_fallback(self, service):
        from utils.exceptions import AppInstallError

        with pytest.raises(AppInstallError) as e:
            service.device_certificate(lambda _m: None, "pw", "192.168.68.112")
        assert "not found" in e.value.details["reason"]

    def test_distributor_without_password_is_accepted(self, service, tmp_path):
        from utils.exceptions import SamsungCertificateError

        (tmp_path / "author.p12").write_bytes(b"x")
        (tmp_path / "distributor.p12").write_bytes(b"x")
        chamadas = []

        def rewrap(src, password, dst, new):
            chamadas.append((src.name, password))
            if src.name == "distributor.p12" and password:
                raise SamsungCertificateError("wrong password")

        with patch("services.samsung_cert.rewrap_p12", side_effect=rewrap):
            destino, _senha = service.device_certificate(lambda _m: None, "pw", "1.2.3.4")
        assert chamadas == [("author.p12", "pw"), ("distributor.p12", "pw"), ("distributor.p12", "")]
        assert oct(os.stat(service.workspace_host).st_mode & 0o777) == "0o700"
        assert destino.startswith(service.workspace_host)

    def test_certs_are_discarded(self, service):
        pasta = os.path.join(service.workspace_host, "certs")
        os.makedirs(pasta)
        open(os.path.join(pasta, "author.p12"), "wb").close()
        service._discard_certs()
        assert not os.path.exists(pasta)

    def test_workspace_is_per_user(self, mock_logger):
        assert DockerService(logger=mock_logger).workspace_host.endswith(f"-{os.getuid()}")


class TestScripts:
    def test_fetch_stops_without_a_release_tag(self):
        from services.docker import fetch_script

        s = fetch_script("/workspace", "Jellyfin-OSA")
        assert 'if [ -z "$TAG" ]' in s and "tail -n 1" in s and "wget -nv" in s

    def test_install_reads_the_tv_name_by_serial(self):
        from services.docker import install_script

        s = install_script("/workspace", "/workspace/pkg", "192.168.68.112", None)
        assert 'awk -v s="192.168.68.112:26101"' in s
        assert "grep -E 'device" not in s
        assert "profile.xml" not in s  # 'dev' profile, no user certificate

    def test_own_certificate_profile_inserted_once(self):
        from services.docker import install_script

        s = install_script("/workspace", "/workspace/pkg", "192.168.68.112", "abcd1234.efgh")
        assert "0,/<\\/profile>/" in s and "-s custom" in s and "abcd1234.efgh" in s

    @pytest.mark.parametrize("senha", [None, "abcd1234.efgh"])
    def test_scripts_are_valid_shell(self, senha):
        import shutil as sh
        from services.docker import fetch_script, install_script

        if not sh.which("bash"):
            pytest.skip("bash not available")
        for texto in (fetch_script("/w", "Jellyfin-OSA"), install_script("/w", "/w/pkg", "10.0.0.2", senha)):
            r = subprocess.run(["bash", "-n"], input=texto, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
