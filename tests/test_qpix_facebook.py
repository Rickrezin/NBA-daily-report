"""Exercise the Facebook send boundary and durable recovery without network access."""

import contextlib
import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import qpix_facebook as publisher
import render_qpix_dashboard as dashboard

DATE = "2026-11-19"
NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
MESSAGE = "QPIX daily report for November 19, 2026\nExample result.\n"
POST_ID = publisher.PAGE_ID + "_123456"
KEY = f"data/social/facebook/{publisher.PAGE_ID}/{DATE}.json"
MANIFEST = {
    "date_et": DATE, "report_sha256": "a" * 64, "source_commit": "b" * 40,
    "run_id": "1234", "run_attempt": "2",
}


class FakeLedger:
    """The state survives a new client, and writes honor the remote SHA lease."""

    def __init__(self, state=None, events=None):
        self.state = state if state is not None else {"revision": 0, "records": {}}
        self.events = events if events is not None else []
        self.fail_writes = {}
        self.writes = []

    def read(self, key):
        self.events.append(("read", key))
        stored = self.state["records"].get(key)
        return (copy.deepcopy(stored["receipt"]), stored["sha"]) if stored else (None, None)

    def write(self, key, receipt, expected_sha):
        self.events.append(("write", receipt["status"]))
        self.writes.append(copy.deepcopy(receipt))
        stored = self.state["records"].get(key)
        actual_sha = stored["sha"] if stored else None
        if actual_sha != expected_sha:
            raise publisher.PublicationError("Receipt reservation conflicted")
        status = receipt["status"]
        if self.fail_writes.get(status, 0):
            self.fail_writes[status] -= 1
            raise publisher.PublicationError("Receipt write was not confirmed")
        self.state["revision"] += 1
        sha = f"{self.state['revision']:040x}"
        self.state["records"][key] = {"receipt": copy.deepcopy(receipt), "sha": sha}
        return sha


class FakeFacebook:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.page_id = publisher.PAGE_ID
        self.posts = []
        self.post_count = 0
        self.lookup_messages = []
        self.lookup_error = False
        self.timeout_after_accept = False
        self.response_id = POST_ID

    def identity(self):
        self.events.append(("identity", self.page_id))
        return {"id": self.page_id, "name": "QPIX"}

    def find_message(self, message, since):
        self.events.append(("lookup", message))
        self.lookup_messages.append(message)
        if self.lookup_error:
            raise publisher.PublicationError("Post lookup failed")
        for post in self.posts:
            if publisher.message_digest(post["message"]) == publisher.message_digest(message):
                return copy.deepcopy(post)
        return None

    def publish(self, message):
        self.events.append(("post", message))
        self.post_count += 1
        self.posts.append({"id": POST_ID, "message": message})
        if self.timeout_after_accept:
            self.timeout_after_accept = False
            raise publisher.PublicationError("Facebook response was not confirmed; no automatic retry")
        return {"id": self.response_id}


class SendBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.ledger = FakeLedger(events=self.events)
        self.facebook = FakeFacebook(events=self.events)

    def send(self, message=MESSAGE, ledger=None):
        return publisher.publish_once(message, MANIFEST, self.facebook, ledger or self.ledger, now=NOW)

    def receipt(self):
        return self.ledger.state["records"][KEY]["receipt"]

    def leave_accepted_pending(self):
        self.facebook.timeout_after_accept = True
        with self.assertRaises(publisher.PublicationError):
            self.send()
        self.assertEqual(self.receipt()["status"], "pending")
        self.assertEqual(self.facebook.post_count, 1)

    def test_reservation_precedes_post_and_rerun_skips(self):
        result = self.send()
        self.assertEqual(result["action"], "published")
        self.assertEqual(self.receipt()["post_id"], POST_ID)
        self.assertLess(self.events.index(("write", "pending")), self.events.index(("post", MESSAGE)))
        self.assertLess(self.events.index(("post", MESSAGE)), self.events.index(("write", "published")))
        new_client = FakeLedger(self.ledger.state, self.events)
        self.assertEqual(self.send(ledger=new_client)["action"], "already_published")
        self.assertEqual(self.facebook.post_count, 1)
        self.assertEqual(new_client.writes, [])

    def test_wrong_page_identity_never_reserves_or_posts(self):
        self.facebook.page_id = "999999"
        with self.assertRaisesRegex(publisher.PublicationError, "does not belong"):
            self.send()
        self.assertEqual(self.ledger.writes, [])
        self.assertEqual(self.facebook.post_count, 0)

    def test_denied_reservation_prevents_post(self):
        self.ledger.fail_writes["pending"] = 1
        with self.assertRaises(publisher.PublicationError):
            self.send()
        self.assertEqual(self.facebook.post_count, 0)
        self.assertNotIn(KEY, self.ledger.state["records"])

    def test_timeout_after_acceptance_recovers_without_second_post(self):
        self.leave_accepted_pending()
        result = self.send(ledger=FakeLedger(self.ledger.state, self.events))
        self.assertEqual(result["action"], "recovered")
        self.assertEqual(self.receipt()["status"], "published")
        self.assertEqual(self.facebook.post_count, 1)

    def test_pending_without_exact_match_is_held(self):
        self.leave_accepted_pending()
        self.facebook.posts[0]["message"] += "different content"
        with self.assertRaisesRegex(publisher.PublicationError, "posting held"):
            self.send()
        self.assertEqual(self.receipt()["status"], "pending")
        self.assertEqual(self.facebook.post_count, 1)

    def test_changed_same_day_text_recovers_the_original_pending_message(self):
        self.leave_accepted_pending()
        result = self.send("A newly edited social post")
        self.assertEqual(result["action"], "recovered")
        self.assertEqual(self.facebook.lookup_messages[-1], MESSAGE)
        self.assertEqual(self.receipt()["message"], MESSAGE)
        self.assertEqual(self.facebook.post_count, 1)

    def test_final_receipt_save_failure_recovers_accepted_post(self):
        self.ledger.fail_writes["published"] = 1
        with self.assertRaises(publisher.PublicationError):
            self.send()
        self.assertEqual(self.receipt()["status"], "pending")
        self.assertEqual(self.facebook.post_count, 1)
        result = self.send(ledger=FakeLedger(self.ledger.state, self.events))
        self.assertEqual(result["action"], "recovered")
        self.assertEqual(self.facebook.post_count, 1)

    def test_invalid_publish_response_keeps_reservation(self):
        self.facebook.response_id = "999999_123456"
        with self.assertRaisesRegex(publisher.PublicationError, "post ID"):
            self.send()
        self.assertEqual(self.receipt()["status"], "pending")
        self.assertEqual(self.facebook.post_count, 1)

    def test_invalid_published_receipt_cannot_authorize_another_post(self):
        self.send()
        original = copy.deepcopy(self.receipt())
        bad_fields = {
            "post_id": "999999_123456", "page_id": "999999", "date_et": "2026-11-18",
            "kind": "weekly", "message_sha256": "0" * 64, "status": "unknown",
        }
        for field, value in bad_fields.items():
            with self.subTest(field=field):
                self.ledger.state["records"][KEY]["receipt"] = {**original, field: value}
                with self.assertRaises(publisher.PublicationError):
                    self.send()
                self.assertEqual(self.facebook.post_count, 1)

    def test_lookup_failure_never_reserves_or_posts(self):
        self.facebook.lookup_error = True
        with self.assertRaisesRegex(publisher.PublicationError, "lookup failed"):
            self.send()
        self.assertEqual(self.ledger.writes, [])
        self.assertEqual(self.facebook.post_count, 0)

    def test_reconcile_only_recovers_after_the_game_date_without_new_send(self):
        self.leave_accepted_pending()
        result = publisher.publish_once("", {"date_et": DATE}, self.facebook, self.ledger,
                                        now=datetime(2026, 11, 25, tzinfo=timezone.utc), allow_new=False)
        self.assertEqual(result["action"], "recovered")
        self.assertEqual(self.facebook.post_count, 1)

    def test_reconcile_only_cannot_reserve_or_send_without_receipt(self):
        with self.assertRaisesRegex(publisher.PublicationError, "never creates"):
            publisher.publish_once("", {"date_et": DATE}, self.facebook, self.ledger, allow_new=False)
        self.assertEqual(self.facebook.post_count, 0)
        self.assertEqual(self.ledger.writes, [])


class FacebookHistoryTest(unittest.TestCase):
    def test_changed_manual_copy_for_same_date_blocks_initial_post(self):
        prior = "QCORE LABS QPIX™ NBA DAILY PERFORMANCE INDEX\nThursday, November 19, 2026\nDifferent wording."
        result = {"data": [{"id": POST_ID, "message": prior}]}
        with mock.patch.object(publisher, "request_json", return_value=result):
            with self.assertRaisesRegex(publisher.PublicationError, "already exists with different text"):
                publisher.Facebook("fake-token").find_message(MESSAGE, 0)

    def test_different_report_date_does_not_block(self):
        prior = "QPIX daily report for November 18, 2026\nDifferent wording."
        with mock.patch.object(publisher, "request_json", return_value={"data": [{"id": POST_ID, "message": prior}]}):
            self.assertIsNone(publisher.Facebook("fake-token").find_message(MESSAGE, 0))

    def test_transport_failure_never_discloses_token_or_retries(self):
        token = "not-a-real-secret-token"
        opener = mock.Mock()
        opener.open.side_effect = publisher.urllib.error.URLError("example " + token)
        with mock.patch.object(publisher.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(publisher.PublicationError) as caught:
                publisher.Facebook(token).publish(MESSAGE)
        self.assertNotIn(token, str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)


@unittest.skipUnless((ROOT / "data" / "daily" / f"{DATE}.json").exists(), "November 19 fixture unavailable")
class BundleAndCommandTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.bundle = self.directory / "bundle"
        # Keep the real dated inputs isolated from newer daily reports in the repo.
        source = self.directory / "source"
        relative_report = f"data/daily/{DATE}.json"
        report = json.loads((ROOT / relative_report).read_text(encoding="utf-8"))
        for relative in (relative_report, report["source_archive"]["path"]):
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        (source / "dashboard").mkdir()
        (source / "dashboard" / "index.html").write_text(
            f"<!doctype html><title>QPIX {DATE}</title>", encoding="utf-8")
        # Avoid relying on a shell git executable for a source-revision fixture.
        with mock.patch.object(dashboard, "DATA", dashboard.DATA), \
                mock.patch.object(publisher.subprocess, "check_output", return_value="b" * 40 + "\n"):
            self.manifest = publisher.create_bundle(source, self.bundle, "1234", "2")
        self.assertEqual(self.manifest["date_et"], DATE)
        self.assertTrue(self.manifest["publishable"])

    def test_actual_fixture_bundle_preserves_verified_inputs(self):
        manifest, report = publisher.load_bundle(self.bundle, "1234", "2")
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(len(report["games"]), 4)
        self.assertEqual(len(report["players"]), 89)

    def test_different_run_or_attempt_is_rejected(self):
        for run, attempt in (("5678", "2"), ("1234", "1")):
            with self.subTest(run=run, attempt=attempt), self.assertRaises(publisher.PublicationError):
                publisher.load_bundle(self.bundle, run, attempt)

    def test_report_and_archive_tampering_is_rejected(self):
        for field in ("report_path", "archive_path"):
            with self.subTest(field=field):
                path = self.bundle / self.manifest[field]
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                try:
                    with self.assertRaisesRegex(publisher.PublicationError, "digest"):
                        publisher.load_bundle(self.bundle, "1234", "2")
                finally:
                    path.write_bytes(original)

    def invoke_publish(self, environment):
        defaults = {"QPIX_DEPLOY_RUN_ID": "1234", "QPIX_DEPLOY_RUN_ATTEMPT": "2"}
        with mock.patch.dict(os.environ, {**defaults, **environment}, clear=True), \
                mock.patch.object(publisher, "ROOT", self.directory / "working"), \
                mock.patch.object(publisher, "previous_date", return_value=DATE), \
                contextlib.redirect_stdout(io.StringIO()):
            return publisher.main(["publish", "--bundle", str(self.bundle)])

    def test_disabled_cli_preserves_preview_without_external_calls(self):
        with mock.patch.object(publisher, "request_json") as api, \
                mock.patch.object(publisher, "verify_live_html") as live, \
                mock.patch.object(publisher, "Facebook") as facebook, \
                mock.patch.object(publisher, "GitHubLedger") as ledger:
            self.assertEqual(self.invoke_publish({"QPIX_FACEBOOK_ENABLED": "false"}), 0)
            api.assert_not_called()
            live.assert_not_called()
            facebook.assert_not_called()
            ledger.assert_not_called()
        self.assertTrue((self.directory / "working" / "docs" / "social" / f"{DATE}.facebook.txt").is_file())

    def test_missing_credentials_fail_before_external_calls(self):
        for credentials in ({}, {"GITHUB_TOKEN": "github-placeholder"},
                            {"FACEBOOK_PAGE_ACCESS_TOKEN": "facebook-placeholder"}):
            with self.subTest(credentials=list(credentials)), \
                    mock.patch.object(publisher, "request_json") as api, \
                    mock.patch.object(publisher, "verify_live_html") as live, \
                    mock.patch.object(publisher, "Facebook") as facebook, \
                    mock.patch.object(publisher, "GitHubLedger") as ledger:
                with self.assertRaisesRegex(publisher.PublicationError, "needs"):
                    self.invoke_publish({"QPIX_FACEBOOK_ENABLED": "true", **credentials})
                api.assert_not_called()
                live.assert_not_called()
                facebook.assert_not_called()
                ledger.assert_not_called()

    def test_live_html_mismatch_blocks_before_clients_or_mutations(self):
        with mock.patch.object(publisher.urllib.request, "urlopen", return_value=io.BytesIO(b"stale page")) as live, \
                mock.patch.object(publisher, "request_json") as api, \
                mock.patch.object(publisher, "Facebook") as facebook, \
                mock.patch.object(publisher, "GitHubLedger") as ledger:
            with self.assertRaisesRegex(publisher.PublicationError, "differs"):
                self.invoke_publish({"QPIX_FACEBOOK_ENABLED": "true", "GITHUB_TOKEN": "github-placeholder",
                                     "FACEBOOK_PAGE_ACCESS_TOKEN": "facebook-placeholder"})
            live.assert_called_once()
            api.assert_not_called()
            facebook.assert_not_called()
            ledger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
