import io
import unittest
import zipfile

import resume_source


def _make_pdf(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_docx(paragraphs) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


class ExtractTextTests(unittest.TestCase):
    def test_pdf(self):
        text = resume_source.extract_text(_make_pdf("Jordan Rivera — Python"), "cv.pdf")
        self.assertIn("Jordan Rivera", text)
        self.assertIn("Python", text)

    def test_docx_joins_paragraphs(self):
        data = _make_docx(["Jordan Rivera", "Skills: Python, SQL", "Experience"])
        text = resume_source.extract_text(data, "cv.docx")
        self.assertEqual(text, "Jordan Rivera\nSkills: Python, SQL\nExperience")

    def test_docx_unescapes_entities(self):
        text = resume_source.extract_text(
            _make_docx(["Ben &amp; Jerry's — 2021"]), "cv.docx"
        )
        self.assertIn("Ben & Jerry's", text)

    def test_txt_and_md_pass_through(self):
        self.assertEqual(
            resume_source.extract_text(b"line one\nline two", "r.txt"), "line one\nline two"
        )
        self.assertEqual(
            resume_source.extract_text(b"# Heading\n\ntext", "r.md"), "# Heading\n\ntext"
        )

    def test_crlf_is_normalised(self):
        self.assertEqual(
            resume_source.extract_text(b"a\r\nb\r\n", "r.txt"), "a\nb"
        )

    def test_unsupported_extension_raises_valueerror(self):
        with self.assertRaises(ValueError):
            resume_source.extract_text(b"data", "resume.pages")

    def test_no_extension_raises_valueerror(self):
        with self.assertRaises(ValueError):
            resume_source.extract_text(b"data", "resume")

    def test_empty_pdf_raises_runtimeerror(self):
        with self.assertRaises(RuntimeError):
            resume_source.extract_text(_make_pdf("   "), "blank.pdf")

    def test_corrupt_docx_raises_runtimeerror(self):
        with self.assertRaises(RuntimeError):
            resume_source.extract_text(b"this is not a zip file", "cv.docx")


if __name__ == "__main__":
    unittest.main()
