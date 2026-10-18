"""Build the submission PDFs from the Markdown sources in docs/ and evidence/.

Needs pandoc (https://pandoc.org) and Playwright with Chromium (pip install playwright && playwright install chromium).
This is a convenience script for the team; it is not needed to run HishabAI.

Run:  python scripts/build_docs.py
"""
import asyncio
import os
import re
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = [
    ("docs/TECHNICAL_DOCUMENTATION.md", "docs/HishabAI_Technical_Documentation.pdf"),
    ("docs/SECURITY_SELF_ASSESSMENT.md", "docs/HishabAI_Security_Self_Assessment.pdf"),
    ("evidence/EXECUTION_EVIDENCE.md", "evidence/HishabAI_Execution_Evidence.pdf"),
    ("docs/TEAM_SUBMISSION_GUIDE.md", "docs/Team_Submission_Guide.pdf"),
]

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: Inter, "Segoe UI", "Noto Sans Bengali", FreeSans, sans-serif; font-size: 10pt; line-height: 1.5;
       color: #1b2a24; max-width: none; margin: 0; }
header#title-block-header { border-bottom: 3px solid #0b6e4f; padding-bottom: 8px; margin-bottom: 18px; }
h1.title { font-size: 22pt; color: #0b6e4f; margin: 0 0 4px; }
p.subtitle { font-size: 11pt; color: #5d6b64; margin: 0; }
p.author { font-size: 9.5pt; color: #1b2a24; margin: 6px 0 0; }
h1 { font-size: 15pt; color: #0b6e4f; margin: 22px 0 8px; page-break-after: avoid; }
h2 { font-size: 12pt; margin: 16px 0 6px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 8.8pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #e8f3ee; text-align: left; }
th, td { border: 1px solid #cfd8d2; padding: 4px 6px; vertical-align: top; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.6pt; background: #f2f5f3; padding: 0 3px; border-radius: 3px; }
pre { background: #f5f7f6; border: 1px solid #dfe5df; border-radius: 6px; padding: 8px 10px; white-space: pre-wrap;
      font-size: 8.4pt; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
img { max-width: 100%; display: block; margin: 8px auto; page-break-inside: avoid; }
figure { margin: 8px 0; } figcaption { display: none; }
blockquote { border-left: 3px solid #0b6e4f; margin: 8px 0; padding: 2px 12px; color: #4a5a52; }
"""


def md_to_html(src, html_path):
    with open(os.path.join(ROOT, src), encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---"):
        # documents without a title block: promote the first heading to the title
        m = re.match(r"# (.+)\n", text)
        if m:
            text = f'---\ntitle: "{m.group(1)}"\n---\n' + text[m.end():]
    tmp_md = html_path + ".md"
    with open(tmp_md, "w", encoding="utf-8") as f:
        f.write(text)
    css_path = html_path + ".css"
    with open(css_path, "w") as f:
        f.write(CSS)
    subprocess.run(["pandoc", tmp_md, "-s", "-o", html_path, "--css", css_path, "--embed-resources",
                    "--resource-path", os.path.dirname(os.path.join(ROOT, src)), "--metadata", "lang=en"],
                   check=True)


async def html_to_pdf(pairs):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        for html, pdf in pairs:
            await page.goto("file://" + html)
            await page.pdf(path=pdf, format="A4", print_background=True, display_header_footer=True,
                           header_template="<span></span>",
                           footer_template='<div style="font-size:8px;color:#888;width:100%;text-align:center;">'
                                           'HishabAI · page <span class="pageNumber"></span> / '
                                           '<span class="totalPages"></span></div>',
                           margin={"top": "16mm", "bottom": "16mm", "left": "15mm", "right": "15mm"})
        await b.close()


def main():
    tmp = tempfile.mkdtemp(prefix="hishab_docs_")
    pairs = []
    for src, out in DOCS:
        html = os.path.join(tmp, os.path.basename(src).replace(".md", ".html"))
        md_to_html(src, html)
        pairs.append((html, os.path.join(ROOT, out)))
    asyncio.run(html_to_pdf(pairs))
    for _, out in DOCS:
        print("wrote", out)


if __name__ == "__main__":
    main()
