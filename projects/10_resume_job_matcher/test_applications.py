import datetime
import unittest

import applications


class ApplicationsTests(unittest.TestCase):
    def setUp(self):
        self.conn = applications.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_add_defaults_and_roundtrip(self):
        app_id = applications.add_application(
            self.conn, company="Northwind", role="Data Analyst"
        )
        rows = applications.list_applications(self.conn)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], app_id)
        self.assertEqual(row["company"], "Northwind")
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["applied_on"], datetime.date.today().isoformat())
        self.assertTrue(row["created_at"])

    def test_add_with_explicit_fields(self):
        applications.add_application(
            self.conn,
            company="Helix",
            role="ML Scientist",
            applied_on="2026-08-01",
            resume_variant="tailored",
            status="interview",
            next_action="thank-you note",
            next_action_on="2026-08-15",
            link="https://jobs.example/helix",
            notes="phone screen went well",
        )
        row = applications.list_applications(self.conn)[0]
        self.assertEqual(row["status"], "interview")
        self.assertEqual(row["next_action_on"], "2026-08-15")
        self.assertEqual(row["link"], "https://jobs.example/helix")

    def test_add_rejects_unknown_field(self):
        with self.assertRaises(ValueError):
            applications.add_application(
                self.conn, company="X", role="Y", salary="lots"
            )

    def test_add_rejects_bad_status(self):
        with self.assertRaises(ValueError):
            applications.add_application(
                self.conn, company="X", role="Y", status="ghosted"
            )

    def test_update_patches_fields_and_bumps_updated_at(self):
        app_id = applications.add_application(self.conn, company="X", role="Y")
        before = applications.list_applications(self.conn)[0]["updated_at"]
        applications.update_application(
            self.conn, app_id, status="rejected", notes="not moving forward"
        )
        row = applications.list_applications(self.conn)[0]
        self.assertEqual(row["status"], "rejected")
        self.assertEqual(row["notes"], "not moving forward")
        self.assertGreaterEqual(row["updated_at"], before)

    def test_update_with_no_fields_is_a_noop(self):
        app_id = applications.add_application(self.conn, company="X", role="Y")
        applications.update_application(self.conn, app_id)  # must not raise
        self.assertEqual(len(applications.list_applications(self.conn)), 1)

    def test_update_can_clear_the_next_action_date(self):
        app_id = applications.add_application(
            self.conn, company="X", role="Y", next_action_on="2026-09-01"
        )
        applications.update_application(self.conn, app_id, next_action_on=None)
        self.assertIsNone(applications.list_applications(self.conn)[0]["next_action_on"])

    def test_delete(self):
        app_id = applications.add_application(self.conn, company="X", role="Y")
        applications.delete_application(self.conn, app_id)
        self.assertEqual(applications.list_applications(self.conn), [])

    def test_list_filters_by_status_and_orders_newest_first(self):
        applications.add_application(
            self.conn, company="Old", role="R", applied_on="2026-01-01"
        )
        applications.add_application(
            self.conn, company="New", role="R", applied_on="2026-08-01", status="offer"
        )
        self.assertEqual(
            [a["company"] for a in applications.list_applications(self.conn)],
            ["New", "Old"],
        )
        offers = applications.list_applications(self.conn, status="offer")
        self.assertEqual([a["company"] for a in offers], ["New"])

    def test_agenda_buckets_by_date_and_skips_closed_and_undated(self):
        today = datetime.date(2026, 8, 20)
        applications.add_application(
            self.conn, company="Overdue", role="R", next_action_on="2026-08-10"
        )
        applications.add_application(
            self.conn, company="Soon", role="R", next_action_on="2026-08-24"
        )
        applications.add_application(
            self.conn, company="Later", role="R", next_action_on="2026-09-30"
        )
        applications.add_application(self.conn, company="NoDate", role="R")
        applications.add_application(
            self.conn,
            company="Closed",
            role="R",
            next_action_on="2026-08-11",
            status="rejected",
        )

        buckets = applications.agenda(self.conn, today=today)
        self.assertEqual([r["company"] for r in buckets["overdue"]], ["Overdue"])
        self.assertEqual([r["company"] for r in buckets["this_week"]], ["Soon"])
        self.assertEqual([r["company"] for r in buckets["later"]], ["Later"])


if __name__ == "__main__":
    unittest.main()
