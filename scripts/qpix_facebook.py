#!/usr/bin/env python3
"""Preview and publish the exact deployed QPIX report to its Facebook Page.

One automatic send attempt per Page/date. A durable pending receipt is written
before POST; an uncertain outcome can only be recovered by finding the original
message on Facebook. It never authorizes another automatic POST.
"""
import argparse
import base64
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from qpix_social import load_verified_report, render_social_post

ROOT = Path(__file__).resolve().parents[1]
PAGE_ID = "61583650594496"
DASHBOARD_URL = "https://rickrezin.github.io/NBA-daily-report/"
REPOSITORY = "Rickrezin/NBA-daily-report"


class PublicationError(RuntimeError):
    pass


class ApiError(PublicationError):
    def __init__(self, service, status, code=None):
        self.status = status
        super().__init__(f"{service} request failed (HTTP {status}, code {code}); no automatic retry")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PublicationError("Unexpected API redirect; credentials were not forwarded")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def message_digest(message):
    return digest(message.replace("\r\n", "\n").strip().encode("utf-8"))


def daily_identity(message):
    """Recognize this daily report even when an earlier/manual copy differs."""
    header = "\n".join(message.splitlines()[:6])
    upper = header.upper()
    if "QPIX" not in upper or not any(label in upper for label in ("DAILY PERFORMANCE INDEX", "QPIX DAILY REPORT")):
        return None
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", header)
    if match:
        try:
            return parse_date(match.group(1))
        except (ValueError, PublicationError):
            return None
    match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b", header, re.I)
    if match:
        try:
            return datetime.strptime(" ".join(match.groups()), "%B %d %Y").date().isoformat()
        except ValueError:
            return None
    return None


def parse_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise PublicationError("Expected a game date in YYYY-MM-DD format")
    return value


def previous_date(now=None):
    now = now or datetime.now(timezone.utc)
    return (now.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()


def safe_path(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise PublicationError("Invalid publication bundle path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise PublicationError("Publication bundle path leaves its directory")
    return path


def request_json(service, method, url, token, payload=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json",
               "User-Agent": "QPIX-Facebook-Publisher"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        code = None
        try:
            code = json.loads(exc.read()).get("error", {}).get("code")
        except (ValueError, AttributeError):
            pass
        raise ApiError(service, exc.code, code if isinstance(code, int) else None) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # Never log headers, access tokens, raw API responses, or paging URLs.
        raise PublicationError(f"{service} response was not confirmed; no automatic retry") from None
    if not isinstance(result, dict):
        raise PublicationError(f"{service} returned an unexpected response")
    if "error" in result:
        code = result["error"].get("code") if isinstance(result["error"], dict) else None
        raise ApiError(service, 200, code if isinstance(code, int) else None)
    return result


class Facebook:
    def __init__(self, token, page_id=PAGE_ID, version="v27.0"):
        if page_id != PAGE_ID or not re.fullmatch(r"v\d+\.0", version):
            raise PublicationError("Facebook destination or API version is invalid")
        self.token, self.page_id = token, page_id
        self.base = f"https://graph.facebook.com/{version}"

    def identity(self):
        return request_json("Facebook", "GET", self.base + "/me?fields=id,name", self.token)

    def find_message(self, message, since):
        expected = message_digest(message)
        expected_day = daily_identity(message)
        params = {"fields": "id,message,permalink_url,created_time", "limit": "100", "since": str(since)}
        matches = []
        seen = set()
        for _ in range(10):
            url = f"{self.base}/{self.page_id}/published_posts?" + urllib.parse.urlencode(params)
            response = request_json("Facebook", "GET", url, self.token)
            if not isinstance(response.get("data"), list):
                raise PublicationError("Facebook post history is unavailable")
            for post in response["data"]:
                if isinstance(post, dict) and isinstance(post.get("message"), str):
                    if message_digest(post["message"]) == expected:
                        matches.append(post)
                    elif expected_day is not None and daily_identity(post["message"]) == expected_day:
                        raise PublicationError("A QPIX daily post for this date already exists with different text; posting held for reconciliation")
            paging = response.get("paging", {})
            if not paging.get("next"):
                if len(matches) > 1:
                    raise PublicationError("Multiple matching posts require reconciliation")
                return matches[0] if matches else None
            # Rebuild the URL from a cursor. Never follow/log a token-bearing paging URL.
            cursor = paging.get("cursors", {}).get("after")
            if not isinstance(cursor, str) or cursor in seen:
                raise PublicationError("Facebook post history could not be fully inspected")
            seen.add(cursor)
            params["after"] = cursor
        raise PublicationError("Facebook post history exceeded the bounded lookup; posting held")

    def publish(self, message):
        return request_json("Facebook", "POST", f"{self.base}/{self.page_id}/feed", self.token,
                            {"message": message, "link": DASHBOARD_URL})


class GitHubLedger:
    def __init__(self, token, repository=REPOSITORY):
        if repository.lower() != REPOSITORY.lower():
            raise PublicationError("Publication receipts must be stored in the QPIX repository")
        self.token = token
        self.base = f"https://api.github.com/repos/{REPOSITORY}/contents/"

    def read(self, key):
        try:
            result = request_json("GitHub receipt", "GET", self.base + key + "?ref=main", self.token)
        except ApiError as exc:
            if exc.status == 404:
                return None, None
            raise
        try:
            return json.loads(base64.b64decode(result["content"])), result["sha"]
        except (KeyError, ValueError, TypeError):
            raise PublicationError("Existing Facebook receipt is invalid") from None

    def write(self, key, receipt, expected_sha):
        payload = {"message": f"Record QPIX Facebook {receipt['status']} for {receipt['date_et']}",
                   "branch": "main", "content": base64.b64encode(
                       (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8")).decode("ascii")}
        if expected_sha is not None:
            payload["sha"] = expected_sha
        result = request_json("GitHub receipt", "PUT", self.base + key, self.token, payload)
        sha = result.get("content", {}).get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise PublicationError("Durable Facebook receipt write was not confirmed")
        return sha


def validate_post_id(post_id):
    if not isinstance(post_id, str) or not re.fullmatch(PAGE_ID + r"_\d+", post_id):
        raise PublicationError("Facebook did not confirm a post ID for the QPIX Page")
    return post_id


def publish_once(message, manifest, facebook, ledger, now=None, allow_new=True):
    """Reserve before sending; recover uncertain outcomes without another POST."""
    now = now or datetime.now(timezone.utc)
    date_et = parse_date(manifest["date_et"])
    key = f"data/social/facebook/{PAGE_ID}/{date_et}.json"
    receipt, sha = ledger.read(key)
    if receipt is None and not allow_new:
        raise PublicationError("No existing receipt for this date; reconciliation never creates posts")
    if receipt is not None:
        if (receipt.get("page_id") != PAGE_ID or receipt.get("date_et") != date_et
                or receipt.get("kind") != "daily" or receipt.get("status") not in {"pending", "published"}
                or not isinstance(receipt.get("message"), str)
                or message_digest(receipt["message"]) != receipt.get("message_sha256")):
            raise PublicationError("Conflicting Facebook receipt; posting held")
        if receipt["status"] == "published":
            validate_post_id(receipt.get("post_id"))
            return {**receipt, "action": "already_published"}
        original = receipt["message"]
        try:
            since = int(datetime.fromisoformat(receipt["attempted_at_utc"]).timestamp()) - 86400
        except (KeyError, ValueError, TypeError):
            raise PublicationError("Pending receipt has no valid attempt time") from None
    else:
        original = message
        since = int((now - timedelta(days=14)).timestamp())
    identity = facebook.identity()
    if identity.get("id") != PAGE_ID:
        raise PublicationError("The Facebook token does not belong to the QPIX Page")
    matched = facebook.find_message(original, since)
    if matched is not None:
        post_id = validate_post_id(matched.get("id"))
        recovered = dict(receipt or {"page_id": PAGE_ID, "date_et": date_et, "kind": "daily",
                                    "message": original, "message_sha256": message_digest(original),
                                    "report_sha256": manifest["report_sha256"]})
        recovered.update(status="published", post_id=post_id, recovered_at_utc=now.isoformat())
        ledger.write(key, recovered, sha)
        return {**recovered, "action": "recovered"}
    if receipt is not None:
        raise PublicationError("An earlier Facebook send may have succeeded. No exact post was found; posting held for reconciliation")
    pending = {"schema_version": 1, "page_id": PAGE_ID, "date_et": date_et, "kind": "daily",
               "status": "pending", "message": message, "message_sha256": message_digest(message),
               "report_sha256": manifest["report_sha256"], "source_commit": manifest["source_commit"],
               "deployment_run_id": manifest["run_id"], "deployment_run_attempt": manifest["run_attempt"],
               "attempted_at_utc": now.isoformat(), "attempt_nonce": str(uuid.uuid4())}
    # Conditional create must return successfully before any Facebook mutation.
    sha = ledger.write(key, pending, None)
    response = facebook.publish(message)  # Deliberately exactly one HTTP attempt.
    post_id = validate_post_id(response.get("id"))
    published = {**pending, "status": "published", "post_id": post_id, "published_at_utc": now.isoformat()}
    try:
        ledger.write(key, published, sha)
    except PublicationError:
        raise PublicationError(f"Facebook confirmed post {post_id}, but its final receipt was not saved. The pending receipt remains; use reconciliation, not a new send") from None
    return {**published, "action": "published"}


def create_bundle(root, destination, run_id, run_attempt):
    import render_qpix_dashboard as dashboard
    if not str(run_id).isdigit() or not str(run_attempt).isdigit():
        raise PublicationError("A deployment run and attempt are required")
    dashboard.DATA = root / "data" / "daily"
    report_path, report = dashboard.find_report()
    date_et = parse_date(report["date_et"])
    relative = report_path.relative_to(root).as_posix()
    html = (root / "dashboard" / "index.html").read_bytes()
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    manifest = {"schema_version": 1, "run_id": str(run_id), "run_attempt": str(run_attempt),
                "source_commit": source_commit, "date_et": date_et, "report_path": relative,
                "report_sha256": digest(report_path.read_bytes()), "html_sha256": digest(html),
                "dashboard_url": DASHBOARD_URL, "status": report.get("status"),
                "publishable": report.get("status") == "VERIFIED" and relative == f"data/daily/{date_et}.json"}
    destination.mkdir(parents=True, exist_ok=True)
    if manifest["publishable"]:
        load_verified_report(root, date_et)
        archive_relative = report["source_archive"]["path"]
        archive_path = safe_path(root, archive_relative)
        manifest.update(archive_path=archive_relative, archive_sha256=digest(archive_path.read_bytes()))
        for relative_path in (relative, archive_relative):
            target = safe_path(destination, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_path(root, relative_path), target)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_bundle(bundle, expected_run=None, expected_attempt=None):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise PublicationError("Unsupported Facebook publication bundle")
    for field, expected in (("run_id", expected_run), ("run_attempt", expected_attempt)):
        if not str(manifest.get(field, "")).isdigit() or (expected is not None and str(manifest[field]) != str(expected)):
            raise PublicationError("Publication bundle does not match the completed deployment attempt")
    date_et = parse_date(manifest["date_et"])
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")):
        raise PublicationError("Publication bundle has no source revision")
    if manifest.get("dashboard_url") != DASHBOARD_URL:
        raise PublicationError("Unexpected dashboard destination")
    if not manifest.get("publishable"):
        return manifest, None
    if manifest.get("status") != "VERIFIED" or manifest.get("report_path") != f"data/daily/{date_et}.json":
        raise PublicationError("Only canonical verified reports can be posted")
    for kind in ("report", "archive"):
        if digest(safe_path(bundle, manifest[f"{kind}_path"]).read_bytes()) != manifest.get(f"{kind}_sha256"):
            raise PublicationError("Publication source digest does not match its deployment")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest.get("html_sha256", "")):
        raise PublicationError("Publication bundle has no HTML digest")
    report = load_verified_report(bundle, date_et)
    if report["source_archive"]["path"] != manifest.get("archive_path"):
        raise PublicationError("Publication bundle uses a different input archive")
    return manifest, report


def verify_live_html(expected_digest):
    try:
        request = urllib.request.Request(DASHBOARD_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=30) as response:
            actual = digest(response.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        raise PublicationError("The live dashboard could not be verified; posting held") from None
    if actual != expected_digest:
        raise PublicationError("The live dashboard differs from this deployment; posting held")


def summarize(message):
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(message + "\n\n")


def output(name, value):
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bundle", "preview", "publish", "check", "reconcile"))
    parser.add_argument("--bundle", type=Path, default=ROOT / ".qpix-publication")
    parser.add_argument("--date")
    args = parser.parse_args(argv)
    if args.command == "bundle":
        manifest = create_bundle(ROOT, args.bundle, os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", ""))
        summarize(f"Frozen dashboard source for {manifest['date_et']}; Facebook eligible: {manifest['publishable']}")
        return 0
    if args.command in {"check", "reconcile"}:
        token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
        if not token:
            raise PublicationError("Add FACEBOOK_PAGE_ACCESS_TOKEN to Actions secrets first")
        facebook = Facebook(token, os.environ.get("FACEBOOK_PAGE_ID", PAGE_ID), os.environ.get("FACEBOOK_GRAPH_VERSION", "v27.0"))
        if args.command == "check":
            identity = facebook.identity()
            if identity.get("id") != PAGE_ID:
                raise PublicationError("The Facebook token does not belong to the QPIX Page")
            facebook.find_message("", int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()))
            summarize(f"QPIX Page {PAGE_ID} identity and post-history access confirmed. No post created; write permission is not tested by this read-only check.")
            return 0
        if not args.date or not os.environ.get("GITHUB_TOKEN"):
            raise PublicationError("Reconciliation requires --date and the workflow GitHub token")
        date_et = parse_date(args.date)
        ledger = GitHubLedger(os.environ["GITHUB_TOKEN"], os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
        result = publish_once("", {"date_et": date_et}, facebook, ledger, allow_new=False)
        summarize(f"Facebook {result['action']} for {date_et}: https://www.facebook.com/{result['post_id']}. No new post sent.")
        return 0
    if args.date:
        if args.command != "preview":
            raise PublicationError("A date-only invocation is preview-only; publishing requires a successful deployment bundle")
        date_et = parse_date(args.date)
        report = load_verified_report(ROOT, date_et)
        manifest = {"date_et": date_et}
        eligible = False
    else:
        run_id, attempt = os.environ.get("QPIX_DEPLOY_RUN_ID"), os.environ.get("QPIX_DEPLOY_RUN_ATTEMPT")
        if args.command == "publish" and (not run_id or not attempt):
            raise PublicationError("Publishing requires a confirmed deployment run and attempt")
        manifest, report = load_bundle(args.bundle, run_id, attempt)
        date_et = manifest["date_et"]
        eligible = report is not None and date_et == previous_date()
        if report is None:
            output("eligible", "false")
            summarize(f"Facebook skipped: deployed report for {date_et} is not VERIFIED")
            return 0
    message = render_social_post(report, date_et)
    target = ROOT / "docs" / "social" / f"{date_et}.facebook.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(message, encoding="utf-8")
    output("date_et", date_et)
    output("eligible", "true" if eligible else "false")
    if args.command == "preview":
        summarize(f"Facebook preview prepared for {date_et}: {len(message)} characters. No post sent.")
        if not eligible and not args.date:
            summarize("Automatic publishing skipped: deployment is not the previous Eastern game date.")
        return 0
    if not eligible:
        raise PublicationError("Automatic Facebook posting is limited to the previous Eastern game date")
    if os.environ.get("QPIX_FACEBOOK_ENABLED", "false").lower() != "true":
        summarize("Facebook publishing is disabled; preview preserved")
        return 0
    token, github_token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN"), os.environ.get("GITHUB_TOKEN")
    if not token or not github_token:
        raise PublicationError("Facebook publishing needs FACEBOOK_PAGE_ACCESS_TOKEN and the workflow GitHub token")
    verify_live_html(manifest["html_sha256"])
    facebook = Facebook(token, os.environ.get("FACEBOOK_PAGE_ID", PAGE_ID), os.environ.get("FACEBOOK_GRAPH_VERSION", "v27.0"))
    ledger = GitHubLedger(github_token, os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    result = publish_once(message, manifest, facebook, ledger)
    summarize(f"Facebook {result['action']} for {date_et}: https://www.facebook.com/{result['post_id']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PublicationError, ValueError, KeyError, OSError) as exc:
        # Only our bounded operational messages are printed; raw API bodies never are.
        message = str(exc) if isinstance(exc, PublicationError) else "Publication input validation failed"
        print(f"Facebook publishing stopped: {message}", file=sys.stderr)
        raise SystemExit(1)
