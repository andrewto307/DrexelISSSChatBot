import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from isss_bot import config

ISSS_PATH = urlsplit(config.ISSS_HOME).path.lower()
DREXEL_HOSTS = {"drexel.edu", "www.drexel.edu"}

ISSS_DOCUMENT_FOLDER = re.compile(r"/[~-]/media/(.+/documents/international-student-support/|files/studentlife/isss/)")

LOGIN_ONLY_HOSTS = {
    "forms.microsoft.com",
    "forms.office.com",
    "one.drexel.edu",
    "login.microsoftonline.com",
    "drexel.qualtrics.com",
    "app.smartsheet.com",
    "secure.touchnet.com",
}
LOGIN_ONLY_HOST_SUFFIXES = (".sharepoint.com",)

IGNORED_LINK = re.compile(
    r"facebook\.com/sharer|pinterest\.com/pin/create|twitter\.com/intent|x\.com/intent|linkedin\.com/share"
    r"|google\.com/maps|maps\.google\.|/sitecore/service/notfound\.aspx",
    re.IGNORECASE,
)

PATH_SAFE_CHARACTERS = "/:@!$&'()*+,;=~"


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if host in DREXEL_HOSTS:
        scheme, host = "https", "drexel.edu"
    path = quote(unquote(parts.path), safe=PATH_SAFE_CHARACTERS)
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, parts.query, ""))


def url_key(url: str) -> str:
    parts = urlsplit(normalize_url(url))
    path = unquote(parts.path).lower().replace(" ", "-")
    return f"{parts.netloc}{path}"


def _drexel_path(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in DREXEL_HOSTS:
        return None
    return unquote(parts.path).lower()


def is_isss_document(url: str) -> bool:
    path = _drexel_path(url)
    if path is None:
        return False
    in_isss_media = path.startswith((ISSS_PATH + "/-/media/", ISSS_PATH + "/~/media/"))
    return in_isss_media or bool(ISSS_DOCUMENT_FOLDER.search(path))


def is_isss_page(url: str) -> bool:
    path = _drexel_path(url)
    if path is None or is_isss_document(url):
        return False
    path = path.rstrip("/")
    return path == ISSS_PATH or path.startswith(ISSS_PATH + "/")


def classify_link(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or IGNORED_LINK.search(url):
        return None
    host = parts.netloc.lower()
    if host in LOGIN_ONLY_HOSTS or host.endswith(LOGIN_ONLY_HOST_SUFFIXES):
        return "login_only"
    if is_isss_document(url):
        return "isss_document"
    if is_isss_page(url):
        return "isss_page"
    if host in DREXEL_HOSTS or host.endswith(".drexel.edu"):
        return "drexel_other"
    return "external"
