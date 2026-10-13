from datetime import date

import pymupdf

from isss_bot.extract import announcement_date_from_url, document_title, extract_html, extract_pdf

HOME = "https://drexel.edu/studentlife/student-success/international-student-support"
PAGE_URL = f"{HOME}/current-students/employment/cpt"

PAGE = f"""
<html><head><title>CPT | Drexel</title><meta property="og:url" content="http://drexel.edu/studentlife/student-success/international-student-support/current-students/employment/CPT"></head>
<body>
<nav class="global-nav"><a href="/studentlife/housing">Housing</a></nav>
<main id="main-content">
  <div class="go-back"><a href="{HOME}">International Students &amp; Scholars Services</a></div>
  <nav class="secondary-navigation"><ul><li><a href="{HOME}/current-students/employment/opt">OPT</a></li></ul></nav>
  <nav class="breadcrumbs"><a href="/studentlife">Student Life</a></nav>
  <h1>Curricular Practical Training (CPT)</h1>
  <div class="share"><a href="https://www.facebook.com/sharer/sharer.php?u=x">Facebook</a></div>
  <div class="rich-text">
    <p>CPT is an <strong>F-1</strong> work authorization.<br>It needs a job offer.</p>
    <h2>Procedure</h2>
    <ul>
      <li>Meet your <a href="/scdc/co-op">co-op advisor</a>.</li>
      <li>Submit the form on the <a href="https://drexel0.sharepoint.com/sites/ISSS-StudentPortal">ISSS Student Portal</a>.
        <ul><li>Attach your offer letter.</li></ul>
      </li>
      <li>Questions? Email <a href="mailto:isss@drexel.edu">isss@drexel.edu</a>.</li>
    </ul>
    <p>See the <a href="https://www.uscis.gov/i-765">USCIS I-765 page</a> and the
       <a href="/studentlife/~/media/Drexel/EMSS-Site-Group/StudentLife/Documents/international-student-support/arrival-guide.pdf">Pre-Arrival Guide [PDF]</a>.</p>
    <table><tr><th>Type</th><th>Hours</th></tr><tr><td>Part-time</td><td>20</td></tr></table>
  </div>
  <div class="accordion-group">
    <h2 class="accordion-group__title">FAQ</h2>
    <div class="simple-accordion">
      <button class="simple-accordion__trigger js-simple-accordion"><span class="simple-accordion__plus-sign"></span>Can I work full-time?</button>
      <div class="simple-accordion__body"><h4>Co-op students</h4><p>Yes, during co-op.</p></div>
    </div>
    <div class="simple-accordion">
      <button class="simple-accordion__trigger js-simple-accordion">Do I need an offer?</button>
      <div class="simple-accordion__body"><p>Yes.</p></div>
    </div>
  </div>
  <div class="container container--prefooter"><div class="prefooter"><h2>Contact Us</h2><p>Main Building, Suite 222</p></div></div>
</main>
</body></html>
"""


def test_extract_html_keeps_content_and_drops_navigation():
    page = extract_html(PAGE, PAGE_URL)
    assert page.title == "Curricular Practical Training (CPT)"
    assert page.page_type == "page"
    assert page.text.startswith("# Curricular Practical Training (CPT)")
    assert "CPT is an **F-1** work authorization.\nIt needs a job offer." in page.text
    for boilerplate in (
        "Housing",
        "Student Life",
        "Facebook",
        "International Students & Scholars Services",
        "Contact Us",
    ):
        assert boilerplate not in page.text


def test_extract_html_renders_lists_links_and_tables():
    text = extract_html(PAGE, PAGE_URL).text
    assert "- Meet your [co-op advisor](https://drexel.edu/scdc/co-op)." in text
    assert "  - Attach your offer letter." in text
    assert "- Questions? Email isss@drexel.edu." in text
    assert "[USCIS I-765 page](https://www.uscis.gov/i-765)" in text
    assert "| Part-time | 20 |" in text


def test_extract_html_turns_accordions_into_nested_headings():
    text = extract_html(PAGE, PAGE_URL).text
    assert (
        "## FAQ\n\n### Can I work full-time?\n\n#### Co-op students\n\nYes, during co-op.\n\n### Do I need an offer?"
        in text
    )


def test_extract_html_records_links_by_kind():
    links = {link.url: link for link in extract_html(PAGE, PAGE_URL).links}
    kinds = {link.kind for link in links.values()}
    assert kinds == {"drexel_other", "login_only", "external", "isss_document"}
    assert links["https://www.uscis.gov/i-765"].anchor_text == "USCIS I-765 page"


def test_extract_html_finds_isss_pages_linked_from_navigation():
    assert f"{HOME}/current-students/employment/opt" in extract_html(PAGE, PAGE_URL).linked_pages


def test_extract_html_uses_declared_canonical_url_for_the_same_page():
    assert extract_html(PAGE, PAGE_URL).url == f"{HOME}/current-students/employment/CPT"


def test_extract_html_ignores_canonical_url_of_another_page():
    html = PAGE.replace("employment/CPT", "employment/opt")
    assert extract_html(html, PAGE_URL).url == PAGE_URL


def test_extract_html_keeps_contact_box_when_asked():
    assert "Main Building, Suite 222" in extract_html(PAGE, PAGE_URL, keep_contact_box=True).text


def test_extract_html_dates_announcements():
    url = f"{HOME}/announcements/2025/December/USCIS-Policy-Memo"
    html = PAGE.replace("<head>", '<head><meta property="article:published_time" content="2025-12-09T10:29:25">')
    page = extract_html(html, url)
    assert page.page_type == "announcement"
    assert page.announcement_date == date(2025, 12, 9)


def test_announcement_date_from_url():
    assert announcement_date_from_url(f"{HOME}/announcements/2025/september/visa%20update") == date(2025, 9, 1)
    assert announcement_date_from_url(f"{HOME}/announcements/2025/september") is None
    assert announcement_date_from_url(f"{HOME}/announcements") is None
    assert announcement_date_from_url(f"{HOME}/current-students/employment/cpt") is None


def test_document_title():
    assert (
        document_title("Download Pre-Arrival Guide [PDF]", "https://drexel.edu/x/arrival-guide.pdf")
        == "Pre-Arrival Guide"
    )
    assert document_title(None, "https://drexel.edu/x/opt-application-checklist.pdf") == "Opt Application Checklist"


def test_extract_pdf():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "OPT Application Checklist")
        page.insert_text((72, 120), "Bring your I-20 and passport.")
        body = pdf.tobytes()
    document = extract_pdf(body, "https://drexel.edu/x/forms/opt-application-checklist.pdf", "OPT Checklist [PDF]")
    assert document.page_type == "document"
    assert document.title == "OPT Checklist"
    assert "OPT Application Checklist" in document.text
    assert "Bring your I-20 and passport." in document.text
