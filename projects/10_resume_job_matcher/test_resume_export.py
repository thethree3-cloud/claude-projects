import io
import unittest
import zipfile

import resume_export
import resume_source

RESUME = {
    "name": "José Rivera",
    "location": "Portland, OR",
    "email": "jose@example.com",
    "phone": "503-555-0100",
    "links": ["github.com/jrivera", "linkedin.com/in/jrivera"],
    "summary": "Analyst who builds Python pipelines — end to end.",
    "skills": ["Python", "SQL", "pandas"],
    "experience": [
        {
            "title": "IT Support Analyst",
            "organization": "Cascade Precision",
            "dates": "2021 - Present",
            "highlights": ["Built a pandas pipeline.", "Ran the help desk."],
        },
        {
            "title": "Bookkeeper",
            "organization": "Rose City Coffee",
            "dates": "2018 - 2021",
            "highlights": ["Reconciled monthly accounts."],
        },
    ],
    "education": [
        {"credential": "AAS, Network Admin", "institution": "PCC", "year": "2019"}
    ],
    "certifications": [{"name": "CompTIA A+", "issuer": "CompTIA", "year": "2019"}],
}

EMPTY = {
    "name": "X",
    "location": "",
    "email": "",
    "phone": "",
    "links": [],
    "summary": "",
    "skills": [],
    "experience": [],
    "education": [],
    "certifications": [],
}


class PdfTests(unittest.TestCase):
    def test_returns_pdf_bytes(self):
        data = resume_export.to_pdf(RESUME)
        self.assertIsInstance(data, bytes)
        self.assertTrue(data.startswith(b"%PDF-"))

    def test_round_trips_through_the_reader(self):
        text = resume_source.extract_text(resume_export.to_pdf(RESUME), "r.pdf")
        self.assertIn("José Rivera", text)
        self.assertIn("jose@example.com", text)
        self.assertIn("SKILLS", text)
        self.assertIn("EXPERIENCE", text)
        self.assertIn("Built a pandas pipeline.", text)
        self.assertIn("Reconciled monthly accounts.", text)
        self.assertIn("CompTIA A+", text)

    def test_non_latin1_characters_do_not_raise(self):
        weird = {**RESUME, "name": "王小明 — 履歴書", "summary": "★ leads with impact ★"}
        data = resume_export.to_pdf(weird)  # must not raise UnicodeEncodeError
        self.assertTrue(data.startswith(b"%PDF-"))

    def test_empty_resume_is_still_a_valid_pdf(self):
        self.assertTrue(resume_export.to_pdf(EMPTY).startswith(b"%PDF-"))


class DocxTests(unittest.TestCase):
    def test_returns_a_valid_zip(self):
        data = resume_export.to_docx(RESUME)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
        self.assertIn("word/document.xml", names)
        self.assertIn("[Content_Types].xml", names)
        self.assertIn("_rels/.rels", names)

    def test_round_trips_through_the_reader(self):
        text = resume_source.extract_text(resume_export.to_docx(RESUME), "r.docx")
        self.assertIn("José Rivera", text)
        self.assertIn("Analyst who builds Python pipelines — end to end.", text)  # em-dash kept
        self.assertIn("EXPERIENCE", text)
        self.assertIn("Reconciled monthly accounts.", text)
        self.assertIn("AAS, Network Admin, PCC (2019)", text)

    def test_ampersand_in_content_is_escaped(self):
        data = resume_export.to_docx({**RESUME, "organization": "x", "skills": ["R&D", "C++"]})
        # would be invalid XML (and unreadable) if & weren't escaped
        text = resume_source.extract_text(data, "r.docx")
        self.assertIn("R&D", text)

    def test_empty_resume_is_still_a_valid_docx(self):
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(resume_export.to_docx(EMPTY))))


if __name__ == "__main__":
    unittest.main()
