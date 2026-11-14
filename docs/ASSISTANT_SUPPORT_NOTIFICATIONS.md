# Assistant, Support and personal notifications

The header adds AI Assistant, Support and a notification bell. The responsive assistant modal also has a floating launcher, history, new chat, suggestions, read-only summary actions, page-local hiding, optional browser dictation and speech synthesis. No saved transcript is kept in browser storage. Read-only summaries never alter school data.

## Explicit assistant modes

- **Guide** retrieves reviewed instructions from the actual How To catalogue and returns links to those articles. This is deterministic retrieval, not an LLM.
- **Live summary** reads permitted saved student/employee status counts, today's recorded student attendance or current bill-month fee balances. No record names are returned. Fees are displayed from integer paisa. More than 2,000 monthly bills are referred to the complete fee report.
- **AI** is available only to private schools after the central software owner enables an available model in `/vendor/assistant`. The backend reads `NEON_AI_GATEWAY_BASE_URL` and `NEON_AI_GATEWAY_TOKEN` from environment variables. An unfunded or unavailable model cannot be enabled. No credit purchase or billing change is performed by this release.

AI requests contain the user's question, up to four previous AI turns, and three authorised static guides. Live summaries, database records, passwords and provider credentials are never included automatically. Questions themselves can contain information supplied by the user; the UI asks them not to send unnecessary private details. No model tool can write records or execute SQL. Daily attempted AI request caps are 10 per actor, 20 per school, and 100 globally; failed provider attempts still consume the cap. Guide fallback is explicit. The provider is disabled by default; all 65 models returned by the connected gateway were marked `paid_plan_required` during implementation.

Assistant history belongs to the signed-in actor and school tenant. Staff permission changes invalidate the history access stamp. Exact request retries reuse the saved answer and cannot cause another provider call. Pending requests interrupted for over 90 seconds can be acknowledged without issuing a duplicate model request. The normal school session gates, CSRF, hourly request limits and scoped campus filters apply.

Browser dictation depends on browser support and microphone permission and may use the browser vendor's speech service. It inserts text for review and never sends a question automatically. The existing Android portal APK does not support microphone capture. Unsupported devices can type or use their keyboard dictation. AI attachment analysis and autonomous database edits are not implemented; the plus attachment link opens Support.

## Human Support

`/workspace/support` is a real school-to-software-owner ticket desk. Signed-in private school users see only their own tickets; staff also require matching campus grants. Each ticket has subject, category, priority, status, replies, read cursor and optional photos/PDF files. Up to five files are allowed, each up to 5 MB, subject to the overall upload limit. Files are authenticated downloads with verified content. Demo previews the form but cannot create tickets or contact the central owner.

The separate central login at `/vendor/login` accesses `/vendor/support`. It can view private school cases and send replies labelled **Human Support · Software owner**. A school owner login does not confer software-owner access. No external email, SMS, WhatsApp delivery or guaranteed response time is implied. Chat transcripts are never attached automatically. File downloads verify both the ticket and reply boundary. Create/reply tokens bind to exact payloads; updates use optimistic versions. Read acknowledgements do not change the reply form version. Central audit records contain action metadata, not message bodies or attachments.

Tickets/provider policy/budgets live in the identity control database; chat history and notice state live in the school tenant database. Production requires durable `IDENTITY_DATABASE_URL` storage and existing school routing. Default development/demo SQLite storage remains ephemeral on Render. No new databases or paid services are provisioned by this release.

## Personal notification bell

The in-app bell derives up to 40 recent events from current permitted records: unread participant conversations, human Support replies, waiting admissions for approvers and pending staff payment approvals. Unread counts concern this recent event window, not the complete source history. Blocked messages, disabled Messaging accounts, inactive/moved child conversations and unauthorised campuses are excluded. Empty lists contain no fictional events.

A read mark is actor-specific and binds to the displayed source revision. Mark displayed as read sends the actual displayed revisions; a newer message arriving meanwhile remains unread. Opening the source conversation or marking Support replies read clears that source's pending event as appropriate. The list refreshes on opening or explicit Refresh, with an initial badge fetch. No native push, browser push, SMS, external notification delivery or background polling is claimed.

## Verification

`tests/test_workspace_tools.py` covers private-school/actor isolation, central privilege and session expiry, real support replies and files, idempotency/CSRF, demo restrictions, read cursors without stale versions, notification revision races, staff campus scopes, absent permissions, fee units, actual model activation checks, mock-provider input boundaries, single-call retries, explicit fallback and spending caps. The PostgreSQL workflow runs these against a separate identity control database. Mobile/desktop browser checks cover the Guide reply, live action, history, modal layout, bell and demo Support boundary alongside the existing Messages/How To/Diary/PTM checks. No paid model invocation is needed by tests.

## Release verification — 14 November 2026

- 735 local backend tests passed in 108.836 seconds. The 15 workspace-tool tests passed again after the fee-summary label refinement.
- PostgreSQL, control/tenant isolation, process persistence, and Chromium at 390/1440px passed in run `43592455351` on `3e0d5dac01a980e642a25bb8c633282285ead42b`.
- PR #5 merged as `b7fa8eafa6e89e1828706e8df7e423dc8be6905d`. Original Render service `schoolflow-phase1` deploy `dep-dbs4rfu7bikc73el5su0` became live at 12:03:23 UTC. No new site was created.
- 20 hosted checks passed: anonymous school/vendor gates, demo entry, header/modal, Guide disclosure, Support preview and rejected demo submission, notification schema, 103 demo How To guides and three readers, existing Messages, saved Guide reply/history and exact retry. `/healthz` returned 200. No error-level runtime logs were returned for the release window. Real school records were not modified by hosted verification.
- **AI activation remains incomplete:** automatic approval review rejected persisting the AI gateway credential to this existing Render service because explicit permission to send the secret to that external destination is required. No Render environment variables were changed. A funded provider model is also required; Guide mode remains active. The software owner can verify/activate a model only after credential setup is authorised and credits are available. No paid plan, credits or model inference was purchased.
