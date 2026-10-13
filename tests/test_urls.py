import pytest

from isss_bot.urls import classify_link, is_isss_document, is_isss_page, normalize_url, url_key

HOME = "https://drexel.edu/studentlife/student-success/international-student-support"
DOCS = (
    "https://drexel.edu/studentlife/~/media/Drexel/EMSS-Site-Group/StudentLife/Documents/international-student-support"
)


def test_normalize_url_cleans_host_scheme_slash_and_fragment():
    assert normalize_url("http://WWW.Drexel.edu/studentlife/student-success/international-student-support/#top") == HOME


def test_normalize_url_encodes_spaces_consistently():
    assert normalize_url(f"{HOME}/announcements/2025/may/new travel faq") == normalize_url(
        f"{HOME}/announcements/2025/may/new%20travel%20faq"
    )


def test_normalize_url_keeps_query():
    assert normalize_url("https://drexel.edu/~/media/Files/hr/guide.ashx?la=en&hash=AB12").endswith("?la=en&hash=AB12")


def test_url_key_treats_case_spaces_and_hyphens_alike():
    assert url_key(f"{HOME}/announcements/2025/december/uscis%20policy%20memo") == url_key(
        f"{HOME}/announcements/2025/December/USCIS-Policy-Memo"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (HOME, True),
        (f"{HOME}/current-students/employment/cpt", True),
        ("https://www.drexel.edu/studentlife/student-success/international-student-support/travel/", True),
        ("https://drexel.edu/studentlife/student-success/international-student-support-archive", False),
        ("https://drexel.edu/scdc/co-op/international", False),
        ("https://example.com/studentlife/student-success/international-student-support", False),
        (f"{DOCS}/arrival-guide.pdf", False),
    ],
)
def test_is_isss_page(url, expected):
    assert is_isss_page(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{DOCS}/arrival-guide.pdf", True),
        (f"{DOCS}/forms/opt-application-checklist.pdf", True),
        ("https://drexel.edu/~/media/Files/studentlife/ISSS/j1-form.pdf", True),
        (f"{HOME}/-/media/isss/stem-guide.pdf", True),
        ("https://drexel.edu/~/media/Files/hr/Internal-Drexel-Careers-Login.ashx?la=en", False),
        (
            "https://drexel.edu/studentlife/~/media/Drexel/EMSS-Site-Group/StudentLife/Images/international-student-support/a.jpg",
            False,
        ),
        ("https://www.ice.gov/doclib/sevis/pdf/i983Instructions.pdf", False),
    ],
)
def test_is_isss_document(url, expected):
    assert is_isss_document(url) is expected


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        (f"{HOME}/forms", "isss_page"),
        (f"{DOCS}/arrival-guide.pdf", "isss_document"),
        ("https://drexel.edu/~/media/Files/hr/guide.ashx", "drexel_other"),
        ("https://drexel.edu/scdc/co-op/international", "drexel_other"),
        ("https://catalog.drexel.edu/", "drexel_other"),
        ("https://drexel0.sharepoint.com/sites/ISSS-StudentPortal/SitePages/ISSS-Student-Forms.aspx", "login_only"),
        ("https://forms.microsoft.com/Pages/ResponsePage.aspx?id=abc", "login_only"),
        ("https://one.drexel.edu/", "login_only"),
        ("https://www.uscis.gov/i-765", "external"),
        ("https://travel.state.gov/content/travel.html", "external"),
        ("mailto:isss@drexel.edu", None),
        ("https://www.facebook.com/sharer/sharer.php?u=x", None),
        ("https://www.google.com/maps?q=39.95,-75.18", None),
        ("https://drexel.edu/sitecore/service/notfound.aspx?item=web%3a%7bABC%7d", None),
    ],
)
def test_classify_link(url, kind):
    assert classify_link(url) == kind
