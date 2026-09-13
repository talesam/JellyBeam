# services/samsung_cert.py
"""Issues a Samsung signing certificate without Tizen Studio.

Samsung TVs running Tizen 8 or newer only install packages whose signing chain
reaches a root baked into the firmware. That leaves exactly one option: a
certificate Samsung itself issues, against the user's account, naming their
TV. The documented way to get one is Tizen Studio's Certificate Manager -- a
gigabyte of IDE for two small files.

It does not have to be. The Certificate Manager talks to a plain REST API, and
everything else is openssl. What cannot be avoided is the Samsung account
login, so the app opens the real login page in the user's own browser and
listens on loopback for the redirect. Their password manager works, they can
see the padlock and the samsung.com address, and the app never sees the
password.

Nothing here is a published API; it is the flow the Certificate Manager uses,
and Samsung may change it. Rather than hardcode what would then break, the
client id and the CA certificates are read at run time out of the official
Samsung Certificate Extension.
"""

from __future__ import annotations

import http.server
import logging
import re
import secrets
import shutil
import socket
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
import zipfile

from gi.repository import GLib
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from utils.constants import (
    SAMSUNG_CERT_CA_AUTHOR,
    SAMSUNG_CERT_CA_DISTRIBUTOR,
    SAMSUNG_CERT_EXTENSION_INFO,
    SAMSUNG_CERT_EXTENSION_ZIP,
    SAMSUNG_CERT_LOGIN,
    SAMSUNG_DEV_API,
    TIMEOUT_HTTP_REQUEST,
)
from utils.exceptions import SamsungCertificateError

_logger = logging.getLogger(__name__)


class SamsungCertificate:
    """Fetches the pieces Samsung's tooling uses, then issues a certificate."""

    def __init__(self, cache_dir: Path) -> None:
        # The extension archive is ~44 MB and only three small artefacts are
        # wanted from it, so the extraction is kept and the archive discarded.
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # The pieces that live inside Samsung's own extension
    # ------------------------------------------------------------------

    def _cached(self, name: str) -> Optional[Path]:
        caminho = self.cache / name
        return caminho if caminho.is_file() and caminho.stat().st_size else None

    def ensure_extension(self, log: Callable[[str], None]) -> Dict[str, Path]:
        """Return the CA files and client id, downloading them once.

        Read from the Samsung Certificate Extension rather than written into
        this file: the client id has already changed once in the wild, and the
        CAs will eventually roll over too.
        """
        autor = self._cached(SAMSUNG_CERT_CA_AUTHOR)
        dist = self._cached(SAMSUNG_CERT_CA_DISTRIBUTOR)
        cid = self._cached("client_id.txt")
        if autor and dist and cid:
            return {"author_ca": autor, "distributor_ca": dist, "client_id": cid}

        log("Fetching Samsung's certificate tooling...")
        versao = self._latest_extension_version()
        url = SAMSUNG_CERT_EXTENSION_ZIP.format(version=versao)
        _logger.info("Downloading certificate extension %s", versao)

        trabalho = self.cache / "work"
        shutil.rmtree(trabalho, ignore_errors=True)
        trabalho.mkdir(parents=True)
        arquivo = trabalho / "ext.zip"
        try:
            urllib.request.urlretrieve(url, arquivo)
            self._extract_artifacts(arquivo, trabalho, log)
        except OSError as e:
            raise SamsungCertificateError(f"could not fetch the extension: {e}") from e
        finally:
            shutil.rmtree(trabalho, ignore_errors=True)

        autor = self._cached(SAMSUNG_CERT_CA_AUTHOR)
        dist = self._cached(SAMSUNG_CERT_CA_DISTRIBUTOR)
        cid = self._cached("client_id.txt")
        if not (autor and dist and cid):
            raise SamsungCertificateError(
                "the extension did not contain the expected certificates"
            )
        return {"author_ca": autor, "distributor_ca": dist, "client_id": cid}

    def _latest_extension_version(self) -> str:
        """Ask Samsung which version of the extension is current."""
        try:
            with urllib.request.urlopen(
                SAMSUNG_CERT_EXTENSION_INFO, timeout=TIMEOUT_HTTP_REQUEST * 4
            ) as r:
                texto = r.read().decode("utf-8", "replace")
        except OSError as e:
            raise SamsungCertificateError(f"could not reach Samsung: {e}") from e

        achados = re.findall(r"tizen-certificate-extension_([0-9.]+)\.zip", texto)
        if not achados:
            raise SamsungCertificateError(
                "no certificate extension listed by Samsung"
            )
        return sorted(achados, key=lambda v: [int(p) for p in v.split(".")])[-1]

    def _extract_artifacts(
        self, arquivo: Path, trabalho: Path, log: Callable[[str], None]
    ) -> None:
        """Dig the two CA files and the client id out of the archive.

        They sit three levels down: the published zip holds a per-platform
        add-on zip, which holds the plugin jar, which holds res/ca/*.
        """
        with zipfile.ZipFile(arquivo) as z:
            addon = next(
                (n for n in z.namelist() if "cert-add-on" in n and "ubuntu" in n), None
            )
            if not addon:
                raise SamsungCertificateError("no Linux add-on in the extension")
            z.extract(addon, trabalho)

        with zipfile.ZipFile(trabalho / addon) as z:
            jar = next(
                (n for n in z.namelist() if n.endswith(".jar") and "cert" in n), None
            )
            if not jar:
                raise SamsungCertificateError("no certificate plugin in the add-on")
            z.extract(jar, trabalho)

        with zipfile.ZipFile(trabalho / jar) as z:
            for nome, destino in (
                (f"res/ca/{SAMSUNG_CERT_CA_AUTHOR}", SAMSUNG_CERT_CA_AUTHOR),
                (f"res/ca/{SAMSUNG_CERT_CA_DISTRIBUTOR}", SAMSUNG_CERT_CA_DISTRIBUTOR),
            ):
                if nome not in z.namelist():
                    raise SamsungCertificateError(f"{destino} missing from the plugin")
                (self.cache / destino).write_bytes(z.read(nome))

            # The client id is compiled into the sign-in dialog; the class file
            # is searched rather than parsed, which is enough for a token.
            cid = self._client_id_from_jar(z)
            if not cid:
                raise SamsungCertificateError("could not find the sign-in client id")
            (self.cache / "client_id.txt").write_text(cid, encoding="utf-8")
        log("Samsung certificate tooling ready")

    @staticmethod
    def _client_id_from_jar(z: zipfile.ZipFile) -> str:
        """Pull the sign-in client id out of the compiled dialog.

        It is a ten-character token mixing letters and digits, stored as a
        string constant. Reading the class file beats writing the value here:
        Samsung has already rotated it once.
        """
        for nome in z.namelist():
            if "SigninDialog" not in nome:
                continue
            dados = z.read(nome)
            for m in re.finditer(rb"(?<![A-Za-z0-9])([a-z0-9]{10})(?![A-Za-z0-9])", dados):
                candidato = m.group(1).decode()
                if any(c.isdigit() for c in candidato) and any(
                    c.isalpha() for c in candidato
                ):
                    return candidato
        return ""

    # ------------------------------------------------------------------
    # The login, in the user's own browser
    # ------------------------------------------------------------------

    def login_url(self, client_id: str, port: int, state: str) -> str:
        return (
            f"{SAMSUNG_CERT_LOGIN}?clientId={client_id}&tokenType=TOKEN"
            f"&redirect_uri=http://127.0.0.1:{port}/callback&state={state}"
        )

    def wait_for_token(self, port: int, state: str, timeout: int = 300) -> Dict:
        """Serve loopback until Samsung redirects back with the token.

        Bound to 127.0.0.1 and shut down as soon as the answer arrives, so
        nothing is reachable from the network and nothing outlives the login.
        """
        resultado: Dict = {}
        pronto = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - required name
                partes = urllib.parse.urlparse(self.path)
                campos = urllib.parse.parse_qs(partes.query)
                if campos.get("state", [""])[0] != state:
                    # Only our own redirect may deliver a token.
                    self.send_error(400)
                    return
                resultado.update({k: v[0] for k, v in campos.items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;padding:3em'>"
                    b"<h2>You can close this tab</h2>"
                    b"<p>JellyBeam has what it needs.</p></body></html>"
                )
                pronto.set()

            def log_message(self, *args):
                pass

        servidor = http.server.HTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            if not pronto.wait(timeout):
                raise SamsungCertificateError("the sign-in was not completed in time")
        finally:
            servidor.shutdown()
            servidor.server_close()
        return resultado

    @staticmethod
    def free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @staticmethod
    def new_state() -> str:
        return secrets.token_urlsafe(16)

    # ------------------------------------------------------------------
    # Issuing the pair
    # ------------------------------------------------------------------

    def issue(
        self,
        duid: str,
        access_token: str,
        user_id: str,
        destino: Path,
        password: str,
        cas: Dict[str, Path],
        log: Callable[[str], None],
    ) -> Tuple[Path, Path]:
        """Ask Samsung for both certificates and write the two .p12 files."""
        destino.mkdir(parents=True, exist_ok=True)

        log("Requesting the author certificate...")
        autor = self._one(
            destino,
            "author",
            subject="/CN=JellyBeam",
            endpoint=f"{SAMSUNG_DEV_API}/apis/v2/authors",
            extra={"platform": "VD"},
            ca=cas["author_ca"],
            access_token=access_token,
            user_id=user_id,
            password=password,
        )

        log("Requesting the distributor certificate...")
        dist = self._one(
            destino,
            "distributor",
            subject="/CN=TizenSDK",
            endpoint=f"{SAMSUNG_DEV_API}/apis/v2/distributors",
            extra={"privilege_level": "Public", "developer_type": "Individual"},
            ca=cas["distributor_ca"],
            access_token=access_token,
            user_id=user_id,
            password=password,
            # This is what binds the certificate to the television; it is the
            # value the Certificate Manager asks people to paste by hand.
            san=f"URI:URN:tizen:packageid=,URI:URN:tizen:deviceid={duid}",
        )
        return autor, dist

    def _one(
        self,
        destino: Path,
        nome: str,
        subject: str,
        endpoint: str,
        extra: Dict[str, str],
        ca: Path,
        access_token: str,
        user_id: str,
        password: str,
        san: str = "",
    ) -> Path:
        chave = destino / f"{nome}.key"
        csr = destino / f"{nome}.csr"
        crt = destino / f"{nome}.crt"
        p12 = destino / f"{nome}.p12"

        self._openssl(["genrsa", "-out", str(chave), "2048"])
        pedido = ["req", "-new", "-key", str(chave), "-out", str(csr), "-subj", subject]
        if san:
            pedido += ["-addext", f"subjectAltName = {san}"]
        self._openssl(pedido)

        corpo, tipo = _multipart(
            {"access_token": access_token, "user_id": user_id, **extra},
            {"csr": (csr.name, csr.read_bytes())},
        )
        pedido_http = urllib.request.Request(
            endpoint, data=corpo, headers={"Content-Type": tipo}
        )
        try:
            with urllib.request.urlopen(pedido_http, timeout=60) as r:
                resposta = r.read()
        except OSError as e:
            raise SamsungCertificateError(f"Samsung refused the request: {e}") from e

        if b"-----BEGIN CERTIFICATE-----" not in resposta:
            trecho = resposta[:200].decode("utf-8", "replace").strip()
            raise SamsungCertificateError(f"Samsung did not return a certificate: {trecho}")
        crt.write_bytes(resposta)

        # The leaf alone is not enough: the TV checks the chain, so the CA goes
        # into the bundle with it.
        cadeia = destino / f"{nome}-chain.crt"
        cadeia.write_bytes(crt.read_bytes() + b"\n" + ca.read_bytes())

        self._openssl(
            [
                "pkcs12", "-export", "-out", str(p12),
                "-inkey", str(chave), "-in", str(cadeia),
                "-name", "usercertificate", "-passout", f"pass:{password}",
            ],
            allow_legacy=True,
        )
        for lixo in (chave, csr, crt, cadeia):
            lixo.unlink(missing_ok=True)
        return p12

    @staticmethod
    def _openssl(args, allow_legacy: bool = False) -> None:
        """Run openssl, retrying with -legacy where OpenSSL 3 needs it.

        Tizen's tooling reads only the old PKCS#12 encryption. OpenSSL 3 stopped
        writing it by default and takes -legacy to go back; OpenSSL 1.1 writes it
        already and rejects the flag. Which one is installed varies by distro, so
        the flag is tried and dropped rather than guessed.
        """
        tentativas = [args + ["-legacy"], args] if allow_legacy else [args]
        erro = ""
        for tentativa in tentativas:
            r = subprocess.run(
                ["openssl", *tentativa], capture_output=True, text=True, timeout=60
            )
            if r.returncode == 0:
                return
            erro = (r.stderr or "").strip()
        raise SamsungCertificateError(f"openssl failed: {erro[:200]}")


class SamsungCertificateFlow:
    """Runs the whole issuance off the main thread, reporting back on it."""

    def __init__(self, docker_service, cache_dir: Path, destino: Path) -> None:
        self.docker = docker_service
        self.cert = SamsungCertificate(cache_dir)
        self.destino = destino

    def create_async(
        self,
        tv_ip: str,
        log: Callable[[str], None],
        callback: Callable[..., None],
    ) -> None:
        """Fetch tooling, sign in, read the TV id, issue both certificates."""

        def run() -> None:
            try:
                cas = self.cert.ensure_extension(log)
                client_id = cas["client_id"].read_text(encoding="utf-8").strip()

                duid = self.docker.read_duid(tv_ip)
                if not duid:
                    raise SamsungCertificateError(
                        "could not read the TV id; is Developer Mode on?"
                    )
                log(f"TV id: {duid}")

                porta = self.cert.free_port()
                state = self.cert.new_state()
                url = self.cert.login_url(client_id, porta, state)
                log("Waiting for the Samsung sign-in in your browser...")
                webbrowser.open(url)

                dados = self.cert.wait_for_token(porta, state)
                token = dados.get("access_token", "")
                user = dados.get("userId") or dados.get("user_id", "")
                if not (token and user):
                    raise SamsungCertificateError(
                        "the sign-in did not return a token"
                    )

                senha = secrets.token_urlsafe(12)
                autor, dist = self.cert.issue(
                    duid, token, user, self.destino, senha, cas, log
                )
                GLib.idle_add(
                    callback, True, "", str(autor), str(dist), senha
                )
            except SamsungCertificateError as e:
                _logger.error("Samsung certificate flow failed: %s", e)
                GLib.idle_add(callback, False, e.details.get("reason", str(e)))
            except Exception as e:  # noqa: BLE001 - surfaced to the user
                _logger.exception("Unexpected failure issuing the certificate")
                GLib.idle_add(callback, False, str(e))

        threading.Thread(target=run, daemon=True).start()


def _multipart(campos: Dict[str, str], arquivos: Dict) -> Tuple[bytes, str]:
    """Build a multipart/form-data body; the API accepts nothing else."""
    limite = f"----JellyBeam{secrets.token_hex(12)}"
    partes = []
    for chave, valor in campos.items():
        partes.append(
            f"--{limite}\r\nContent-Disposition: form-data; name=\"{chave}\"\r\n\r\n"
            f"{valor}\r\n".encode()
        )
    for chave, (nome, dados) in arquivos.items():
        partes.append(
            f"--{limite}\r\nContent-Disposition: form-data; name=\"{chave}\"; "
            f"filename=\"{nome}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        )
        partes.append(dados + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"
