"""Tests for the Samsung certificate flow.

The issuing call needs a real Samsung account and cannot be tested here. What
can be tested is everything that decides *where* the login goes and *how* its
reply is read -- which is where this went wrong in the first place: the app
composed its own redirect target, Samsung answered "redirect_uri is not
registered", and no login ever happened.
"""

import io
import json
import urllib.error
import zipfile

import pytest

from services.samsung_cert import SamsungCertificate, _error_description, _multipart
from utils.exceptions import SamsungCertificateError

REAL_URL = (
    "https://account.samsung.com/mobile/account/check.do"
    "?serviceID=v285zxnl3h&actionID=StartOAuth2&accessToken=Y"
    "&redirect_uri=http://localhost:4794/signin/callback"
)


def _jar(*strings: str) -> zipfile.ZipFile:
    """A stand-in for the plugin jar, with class-file style string constants.

    The constants are wrapped in the non-printable tag bytes a real constant
    pool puts around them, so the extraction has to stop at the right place.
    """
    buf = io.BytesIO()
    corpo = b"".join(b"\x01\x00\x20" + s.encode() for s in strings)
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("org/tizen/common/cert/ui/SigninDialog.class", corpo)
    return zipfile.ZipFile(buf)


class TestLoginURL:
    def test_reads_the_url_whole(self):
        assert SamsungCertificate._login_url_from_jar(_jar(REAL_URL)) == REAL_URL

    def test_ignores_account_urls_that_are_not_a_login(self):
        """The dialog holds several; only one names where to come back to."""
        outra = "https://account.samsung.com/mobile/account/deviceInterfaceCloseOAuth2.do?"
        assert SamsungCertificate._login_url_from_jar(_jar(outra, REAL_URL)) == REAL_URL

    def test_missing_url_reports_empty(self):
        assert SamsungCertificate._login_url_from_jar(_jar("nothing here")) == ""


class TestRedirectTarget:
    def test_takes_port_and_path_from_the_url(self):
        """Both belong to Samsung's registration; neither may be invented."""
        assert SamsungCertificate.redirect_target(REAL_URL) == (4794, "/signin/callback")

    def test_rejects_a_target_that_is_not_loopback(self):
        with pytest.raises(SamsungCertificateError):
            SamsungCertificate.redirect_target(
                "https://account.samsung.com/x?redirect_uri=http://evil.example/cb"
            )

    def test_rejects_a_target_without_a_port(self):
        with pytest.raises(SamsungCertificateError):
            SamsungCertificate.redirect_target(
                "https://account.samsung.com/x?redirect_uri=http://localhost/cb"
            )


class TestParseCallback:
    def test_reads_the_json_samsung_posts(self):
        carga = json.dumps(
            {
                "access_token": "tok",
                "userId": "user-1",
                "inputEmailID": "a%40b.com",
                "access_token_expires_in": "3600",
            }
        )
        dados = SamsungCertificate.parse_callback(f"code={carga}")
        assert dados["access_token"] == "tok"
        assert dados["user_id"] == "user-1"
        assert dados["email"] == "a@b.com"

    def test_survives_a_token_containing_padding(self):
        """Splitting on every '=' would truncate a base64 token."""
        carga = json.dumps({"access_token": "aGVsbG8=", "userId": "u"})
        dados = SamsungCertificate.parse_callback(f"code={carga}")
        assert dados["access_token"] == "aGVsbG8="

    def test_reads_the_query_string_shape_too(self):
        dados = SamsungCertificate.parse_callback("access_token=tok&userId=user-1")
        assert dados["access_token"] == "tok"
        assert dados["user_id"] == "user-1"

    def test_unreadable_json_is_reported(self):
        with pytest.raises(SamsungCertificateError):
            SamsungCertificate.parse_callback("code={not json")


def _http_error(body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://svdca.samsungqbe.com/apis/v3/authors", 400, "Bad Request", {}, io.BytesIO(body)
    )


class TestErrorDescription:
    def test_reads_the_nested_description_samsung_sends(self):
        """Body observed from the live host on an empty request."""
        corpo = (
            b'{"error":{"status":400,"code":"201",'
            b'"description":"Userid or accesstoken token is required."}}'
        )
        assert _error_description(_http_error(corpo)) == (
            "Userid or accesstoken token is required."
        )

    def test_falls_back_to_the_status_when_the_body_is_not_json(self):
        assert "400" in _error_description(_http_error(b"<html>nope</html>"))


class TestLegacyP12:
    """Tizen's CLI reads only PBES1 PKCS#12; a modern file reads as a wrong password."""

    @staticmethod
    def _self_signed(cn: str):
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        agora = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(1).not_valid_before(agora)
            .not_valid_after(agora + datetime.timedelta(days=1))
            .sign(chave, hashes.SHA256())
        )
        return (
            chave.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
            cert.public_bytes(serialization.Encoding.PEM),
        )

    def test_writes_pbes1_that_openssl_legacy_reads(self, tmp_path):
        import subprocess

        from services.samsung_cert import write_legacy_p12

        chave, folha = self._self_signed("leaf")
        _, ca = self._self_signed("ca")
        p12 = tmp_path / "author.p12"
        write_legacy_p12(p12, chave, folha, ca, "s3cret")
        assert p12.stat().st_mode & 0o777 == 0o600

        info = subprocess.run(
            ["openssl", "pkcs12", "-info", "-in", str(p12), "-passin", "pass:s3cret",
             "-nokeys", "-noout", "-legacy"],
            capture_output=True, text=True, timeout=30,
        )
        if info.returncode != 0:
            pytest.skip("host openssl has no legacy provider; cannot inspect")
        assert "3-KeyTripleDES" in info.stderr
        assert "MAC: sha1" in info.stderr
        assert "AES" not in info.stderr and "PBKDF2" not in info.stderr

    def test_bundle_carries_leaf_and_ca(self, tmp_path):
        from cryptography.hazmat.primitives.serialization import pkcs12

        from services.samsung_cert import write_legacy_p12

        chave, folha = self._self_signed("leaf")
        _, ca = self._self_signed("ca")
        p12 = tmp_path / "d.p12"
        write_legacy_p12(p12, chave, folha, ca, "pw")
        k, c, extras = pkcs12.load_key_and_certificates(p12.read_bytes(), b"pw")
        assert k is not None and c is not None
        assert len(extras) == 1  # the CA travels with the leaf


class TestSafePassword:
    """The Tizen CLI base64-decodes a password that looks decodable; ours never does."""

    def test_never_looks_like_base64(self):
        from services.samsung_cert import looks_like_base64, safe_password

        for _ in range(500):
            assert not looks_like_base64(safe_password())

    def test_detector_matches_what_the_cli_did(self):
        """Cases measured in the container: the first failed, the rest signed."""
        from services.samsung_cert import looks_like_base64

        assert looks_like_base64("Abcdefgh12345678")
        assert not looks_like_base64("Abcdefgh1234567")
        assert not looks_like_base64("Abcdefg-12345678")
        assert not looks_like_base64("Abcdefg.12345678")

    def test_is_safe_for_sed_and_xml(self):
        from services.samsung_cert import safe_password

        for _ in range(200):
            assert not set(safe_password()) & set("&\\/<>\"'")


class TestRewrap:
    def test_rewraps_with_a_new_password_and_keeps_the_chain(self, tmp_path):
        from cryptography.hazmat.primitives.serialization import pkcs12

        from services.samsung_cert import rewrap_p12, write_legacy_p12

        chave, folha = TestLegacyP12._self_signed("leaf")
        _, ca = TestLegacyP12._self_signed("ca")
        origem = tmp_path / "user.p12"
        write_legacy_p12(origem, chave, folha, ca, "Abcdefgh12345678")  # a bad one
        destino = tmp_path / "author.p12"
        rewrap_p12(origem, "Abcdefgh12345678", destino, "Abcdefg.12345678")
        k, c, extras = pkcs12.load_key_and_certificates(destino.read_bytes(), b"Abcdefg.12345678")
        assert k is not None and c is not None and len(extras) == 1
        assert destino.stat().st_mode & 0o777 == 0o600

    def test_wrong_password_fails_here_with_a_message(self, tmp_path):
        from services.samsung_cert import rewrap_p12, write_legacy_p12

        chave, folha = TestLegacyP12._self_signed("leaf")
        origem = tmp_path / "user.p12"
        write_legacy_p12(origem, chave, folha, folha, "right")
        with pytest.raises(SamsungCertificateError, match="wrong password"):
            rewrap_p12(origem, "wrong", tmp_path / "out.p12", "x.y")


class TestSavedPassword:
    def test_round_trips_and_is_private(self, tmp_path):
        SamsungCertificate.save_password(tmp_path, "s3cret")
        assert SamsungCertificate.load_password(tmp_path) == "s3cret"
        assert (tmp_path / ".password").stat().st_mode & 0o777 == 0o600

    def test_missing_file_is_empty_not_an_error(self, tmp_path):
        assert SamsungCertificate.load_password(tmp_path) == ""


class TestMultipart:
    def test_keeps_a_repeated_field_name(self):
        """The distributor request sends platform twice; a dict would drop one."""
        corpo, tipo = _multipart(
            [("platform", "Gear2"), ("platform", "VD")], {"csr": ("d.csr", b"x")}
        )
        assert corpo.count(b'name="platform"') == 2
        assert tipo.startswith("multipart/form-data; boundary=")
