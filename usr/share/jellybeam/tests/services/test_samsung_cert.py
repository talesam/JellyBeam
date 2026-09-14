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


class TestMultipart:
    def test_keeps_a_repeated_field_name(self):
        """The distributor request sends platform twice; a dict would drop one."""
        corpo, tipo = _multipart(
            [("platform", "Gear2"), ("platform", "VD")], {"csr": ("d.csr", b"x")}
        )
        assert corpo.count(b'name="platform"') == 2
        assert tipo.startswith("multipart/form-data; boundary=")
