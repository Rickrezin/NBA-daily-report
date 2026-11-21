# QPIX Facebook Page publishing

Destination: [QPIX NBA player performance index](https://www.facebook.com/people/QPIX-NBA-player-performance-index/61583650594496/), Page ID `61583650594496`.

Publishing is disabled until the Page is authorized and the repository variable `QPIX_FACEBOOK_ENABLED` is exactly `true`. Previewing never sends a Facebook post.

## Authorize the Page

1. Sign in at [Meta for Developers](https://developers.facebook.com/apps/) with the Facebook account that can create content on the QPIX Page. Create or select a Meta app for managing that Page. App setup screens vary by app type and use case.
2. Grant the app `pages_manage_posts`, `pages_read_engagement`, and `pages_show_list`, selecting the QPIX Page. Use [Graph API Explorer](https://developers.facebook.com/tools/explorer/) or the app's Facebook Login flow. Do not request unrelated advertising, messaging, or moderation access for this publisher.
3. Obtain the QPIX **Page** access token. Meta's `/me/accounts` response lists each authorized Page's name, ID, tasks, and Page token. Confirm the returned ID is `61583650594496` and content creation is permitted. The daily publisher also checks `/me` before its first posting attempt.
4. For unattended operation, use Meta's documented [long-lived Page-token procedure](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/). A normal user token is not the Page credential; a short-lived test token is not a durable daily connection. Long-lived Page tokens have no scheduled expiration but can still be invalidated when access or account security changes.
5. Open [repository Actions secrets](https://github.com/Rickrezin/NBA-daily-report/settings/secrets/actions). Add `FACEBOOK_PAGE_ACCESS_TOKEN` with the Page token as its secret value. Keep tokens and app secrets out of chat, code, screenshots, and logs.
6. Run **QPIX Facebook Page Publication** manually with `operation=check_connection`. This confirms Page identity and access to its post history without creating a post; it does not prove that a write will succeed. Review the generated social preview, then open [repository Actions variables](https://github.com/Rickrezin/NBA-daily-report/settings/variables/actions) and set `QPIX_FACEBOOK_ENABLED` to `true`. The next successful eligible dashboard deployment can publish. Set it to `false` to pause posting. `FACEBOOK_GRAPH_VERSION` optionally selects the app's supported API version; the default is `v27.0`.

For an app used only by its own app-role users, Meta documents a route that can avoid public App Review. Whether that applies depends on the app's actual type, mode, roles, and access settings. Do not enable broad/public app access just to connect this one Page. See [Meta's Pages API overview](https://developers.facebook.com/docs/pages-api/overview/) and [App Review introduction](https://developers.facebook.com/docs/resp-plat-initiatives/app-review/introduction).

## What gets posted

The Facebook text comes from the exact verified report that was deployed, with full final scores before the authoritative Top 10, player statistics, performance notes, Bottom 10, short metric explanations, and the live dashboard link. The generator does not recalculate QPIX or expose formulas and source-audit dumps. It omits emojis and player tags.

Q-OffR/Q-DefR are displayed only when explicitly identified proprietary values exist in that report. Missing values are `N/A`. Basketball Reference ORtg/DRtg and engine impact contributions are not relabeled as QCore ratings.

Local preview:

```bash
python scripts/qpix_facebook.py preview --date 2026-11-19
```

The output is `docs/social/2026-11-19.facebook.txt`. In GitHub, manually run **QPIX Facebook Page Publication** with `operation=preview` and a date to obtain a preview artifact. Manual operations never create a post, even while automatic publishing is enabled.

## Daily execution

The normal 9 a.m. Eastern report workflow publishes the dashboard. After a successful **QPIX HTML Dashboard Deploy** run, its exact source snapshot is retained as `qpix-facebook-source-RUN_ID-RUN_ATTEMPT`. The Facebook workflow downloads only that run attempt's bundle. It checks the report date, VERIFIED status, report and source digests, source coverage, authoritative leaderboard IDs, and live HTML before sending. An automatic post must concern the previous Eastern calendar date. Provisional reports and stale redeployments are not posted.

This uses the existing report-completion event, rather than a second posting clock. Manual previews and shadow collectors do not post. The Facebook token is passed only to the publishing step.

## Receipts and uncertain outcomes

`data/social/facebook/61583650594496/YYYY-MM-DD.json` is a durable receipt keyed by Page and game date. It contains only public post content and provenance, never credentials.

Before a Facebook POST, the workflow conditionally saves a `pending` receipt to `main` through GitHub's Contents API. If that write fails or is uncertain, it sends nothing. After Facebook confirms a post ID, it updates the receipt to `published`. A rerun with a published receipt does not send another post, including when the report or social wording has changed.

Before the first send for a date, it also looks for an existing daily QPIX post on the Page. An exact original-message match can be recorded without another send. A recognized daily QPIX title/date with different text is held for review, including a manually published version.

If a POST times out, a response is unclear, or the final receipt write fails, the original pending receipt remains. A later run can recover by finding the exact original message on the Page. If it cannot establish the outcome, it stops for reconciliation; absence from a recent-post lookup does not prove the earlier send failed. No POST is automatically retried. This prioritizes avoiding duplicate posts and can leave a held post after an ambiguous failure.

To resolve a held receipt, run **QPIX Facebook Page Publication** manually with `operation=reconcile` and the original game date. This can recover an exact original-message match even after midnight or a newer dashboard deployment, and cannot send a new post. If no exact match is found, inspect the Page and that run's result before correcting the receipt. Only reset a pending receipt for a fresh attempt after explicitly establishing that no post was accepted; never delete it merely to make a failed run green. A token/permission failure should be corrected through Meta and the Actions secret.

GitHub Actions needs `contents: write` for receipt commits and `actions: read` for the exact deployment artifact. Branch protections that prohibit these receipt writes will hold posting; do not weaken them without review. The integration does not change Facebook permissions or repository branch protections itself.

## References

- [Meta Page Feed publishing endpoint and required permissions](https://developers.facebook.com/docs/graph-api/reference/page/feed/)
- [Meta long-lived user and Page tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/)
- [GitHub Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
- [GitHub conditional file creation and updates](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)
