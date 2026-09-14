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
sign-in URL and the CA certificates are read at run time out of the official
Samsung Certificate Extension.

Reading the sign-in URL rather than composing one is not a nicety. Samsung
only honours redirect targets it has registered, and the registered one is a
fixed loopback address -- a port and path chosen years ago, not one this app
may pick. Building the URL by hand gets "redirect_uri is not registered" and
no login at all.
"""

from __future__ import annotations

import http.server
import json
import logging
import re
import secrets
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile

from gi.repository import GLib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from utils.i18n import _
from utils.constants import (
    SAMSUNG_CERT_AUTHOR_API,
    SAMSUNG_CERT_CA_AUTHOR,
    SAMSUNG_CERT_CA_DISTRIBUTOR,
    SAMSUNG_CERT_DISTRIBUTOR_API,
    SAMSUNG_CERT_EXTENSION_INFO,
    SAMSUNG_CERT_EXTENSION_ZIP,
    TIMEOUT_HTTP_REQUEST,
)
from utils.exceptions import SamsungCertificateError

_logger = logging.getLogger(__name__)

LOGIN_URL_FILE = "login_url.txt"

# A printable run starting at Samsung's account host. Class files store string
# constants as bare UTF-8, so the run ends where the next pool entry's tag byte
# begins; the character class below is what a URL may legally contain.
_LOGIN_URL = re.compile(rb"https://account\.samsung\.com/[A-Za-z0-9_./?=&:%~+-]+")


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
        """Return the CA files and the sign-in URL, downloading them once.

        Read from the Samsung Certificate Extension rather than written into
        this file: the service id has already changed once in the wild, the
        loopback port belongs to Samsung's registration rather than to us, and
        the CAs will eventually roll over too.
        """
        autor = self._cached(SAMSUNG_CERT_CA_AUTHOR)
        dist = self._cached(SAMSUNG_CERT_CA_DISTRIBUTOR)
        cid = self._cached(LOGIN_URL_FILE)
        if autor and dist and cid:
            return {"author_ca": autor, "distributor_ca": dist, "login_url": cid}

        log(_("Downloading Samsung's certificate tooling (44 MB, once)..."))
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
        cid = self._cached(LOGIN_URL_FILE)
        if not (autor and dist and cid):
            raise SamsungCertificateError(
                "the extension did not contain the expected certificates"
            )
        return {"author_ca": autor, "distributor_ca": dist, "login_url": cid}

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

            # The whole sign-in URL is compiled into the dialog as one string
            # constant, redirect target included. Taking it whole is what keeps
            # the redirect registered.
            url = self._login_url_from_jar(z)
            if not url:
                raise SamsungCertificateError("could not find the sign-in URL")
            (self.cache / LOGIN_URL_FILE).write_text(url, encoding="utf-8")
        log(_("Samsung certificate tooling ready"))

    @staticmethod
    def _login_url_from_jar(z: zipfile.ZipFile) -> str:
        """Pull the sign-in URL out of the compiled dialog.

        Class files store string constants as plain UTF-8 runs, so the URL can
        be found without parsing the constant pool: the surrounding bytes are
        pool tags and lengths, which are not printable and end the match.
        """
        for nome in z.namelist():
            if "SigninDialog" not in nome:
                continue
            for m in _LOGIN_URL.finditer(z.read(nome)):
                candidato = m.group(0).decode()
                # The dialog holds several account.samsung.com URLs; the one
                # that starts a login is the one naming where to come back to.
                if "redirect_uri=" in candidato:
                    return candidato
        return ""

    @staticmethod
    def redirect_target(login_url: str) -> Tuple[int, str]:
        """Return the loopback port and path Samsung will call back on."""
        alvo = urllib.parse.parse_qs(
            urllib.parse.urlparse(login_url).query
        ).get("redirect_uri", [""])[0]
        partes = urllib.parse.urlparse(alvo)
        if partes.hostname not in ("localhost", "127.0.0.1") or not partes.port:
            raise SamsungCertificateError(
                f"unexpected sign-in redirect target: {alvo or login_url}"
            )
        return partes.port, partes.path or "/"

    # ------------------------------------------------------------------
    # The login, in the user's own browser
    # ------------------------------------------------------------------

    @staticmethod
    def parse_callback(corpo: str) -> Dict[str, str]:
        """Read the account details out of the callback Samsung posts.

        The body is one form field carrying a JSON document. Older builds sent
        the fields as a query string instead, and both shapes still turn up, so
        both are read.
        """
        campos = urllib.parse.parse_qs(corpo)
        carga = (campos.get("code") or campos.get("response") or [corpo])[0].strip()

        dados: Dict[str, str] = {}
        if carga.startswith("{"):
            try:
                dados = {k: str(v) for k, v in json.loads(carga).items()}
            except ValueError as e:
                raise SamsungCertificateError(f"unreadable sign-in reply: {e}") from e
        else:
            dados = {
                k: v[0]
                for k, v in urllib.parse.parse_qs(carga.lstrip("?")).items()
            }

        return {
            "access_token": dados.get("access_token", ""),
            # Samsung spells it userId here and user_id in the issuing API.
            "user_id": dados.get("userId") or dados.get("user_id", ""),
            "email": dados.get("inputEmailID", "").replace("%40", "@"),
        }

    def wait_for_token(self, port: int, path: str, timeout: int = 300) -> Dict[str, str]:
        """Serve loopback until Samsung posts the account details back.

        Bound to 127.0.0.1 and shut down as soon as the answer arrives, so
        nothing is reachable from the network and nothing outlives the login.
        The port is Samsung's, not ours, so it cannot be moved out of the way
        if something else holds it -- hence the explicit message.
        """
        resultado: Dict[str, str] = {}
        falha: Dict[str, str] = {}
        pronto = threading.Event()
        cert = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _entregar(self, corpo: str) -> None:
                try:
                    resultado.update(cert.parse_callback(corpo))
                except SamsungCertificateError as e:
                    falha["reason"] = str(e)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;padding:3em'>"
                    b"<h2>You can close this tab</h2>"
                    b"<p>JellyBeam has what it needs.</p></body></html>"
                )
                pronto.set()

            def do_POST(self):  # noqa: N802 - required name
                if urllib.parse.urlparse(self.path).path != path:
                    self.send_error(404)
                    return
                tamanho = int(self.headers.get("Content-Length") or 0)
                self._entregar(self.rfile.read(tamanho).decode("utf-8", "replace"))

            def do_GET(self):  # noqa: N802 - required name
                partes = urllib.parse.urlparse(self.path)
                if partes.path != path:
                    self.send_error(404)
                    return
                self._entregar(partes.query)

            def log_message(self, *args):
                pass

        try:
            servidor = http.server.HTTPServer(("127.0.0.1", port), Handler)
        except OSError as e:
            raise SamsungCertificateError(
                f"port {port} is busy, and Samsung only accepts that one: {e}"
            ) from e

        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            if not pronto.wait(timeout):
                raise SamsungCertificateError("the sign-in was not completed in time")
        finally:
            servidor.shutdown()
            servidor.server_close()

        if falha:
            raise SamsungCertificateError(falha["reason"])
        return resultado

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

        # The field lists below mirror CertificateGenerator.fetchCRT in the
        # Certificate Manager, in its order. The distributor one really does
        # carry platform twice -- Gear2 from DistributorGenerator, then VD for
        # television mode -- and that is what the server has been accepting.
        log(_("Requesting the author certificate..."))
        autor = self._one(
            destino,
            "author",
            subject="/CN=JellyBeam",
            endpoint=SAMSUNG_CERT_AUTHOR_API,
            extra=[("platform", "VD")],
            ca=cas["author_ca"],
            access_token=access_token,
            user_id=user_id,
            password=password,
        )

        log(_("Requesting the distributor certificate..."))
        dist = self._one(
            destino,
            "distributor",
            subject="/CN=TizenSDK",
            endpoint=SAMSUNG_CERT_DISTRIBUTOR_API,
            extra=[
                ("privilege_level", "Public"),
                ("developer_type", "Individual"),
                ("platform", "Gear2"),
                ("platform", "VD"),
            ],
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
        extra: List[Tuple[str, str]],
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
            [("access_token", access_token), ("user_id", user_id), *extra],
            {"csr": (csr.name, csr.read_bytes())},
        )
        pedido_http = urllib.request.Request(
            endpoint, data=corpo, headers={"Content-Type": tipo}
        )
        try:
            with urllib.request.urlopen(pedido_http, timeout=60) as r:
                resposta = r.read()
        except urllib.error.HTTPError as e:
            # Refusals come back as JSON with a description; that line is the
            # useful one, not the status code.
            raise SamsungCertificateError(
                f"Samsung refused the request: {_error_description(e)}"
            ) from e
        except OSError as e:
            raise SamsungCertificateError(f"could not reach Samsung: {e}") from e

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
                url = cas["login_url"].read_text(encoding="utf-8").strip()
                porta, caminho = self.cert.redirect_target(url)

                duid = self.docker.read_duid(tv_ip)
                if not duid:
                    raise SamsungCertificateError(
                        "could not read the TV id; is Developer Mode on?"
                    )
                log(_("TV id: {duid}").format(duid=duid))

                log(_("Opening the Samsung sign-in in your browser. Log in there; this window will continue by itself."))
                webbrowser.open(url)

                dados = self.cert.wait_for_token(porta, caminho)
                token = dados.get("access_token", "")
                user = dados.get("user_id", "")
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


def _error_description(e: urllib.error.HTTPError) -> str:
    """The description in Samsung's JSON error, or the bare status.

    Observed shape: {"error": {"status": 400, "code": "201", "description":
    "Userid or accesstoken token is required."}}.
    """
    try:
        corpo = json.loads(e.read().decode("utf-8", "replace"))
        erro = corpo.get("error", corpo) if isinstance(corpo, dict) else {}
        return str(erro.get("description") or erro.get("message") or e)
    except (ValueError, AttributeError, OSError):
        return str(e)


def _multipart(campos: List[Tuple[str, str]], arquivos: Dict) -> Tuple[bytes, str]:
    """Build a multipart/form-data body; the API accepts nothing else.

    Fields are a list, not a dict: the distributor request repeats a name.
    """
    limite = f"----JellyBeam{secrets.token_hex(12)}"
    partes = []
    for chave, valor in campos:
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
