# SchoolFlow How To

The shared header now links to **How To**, immediately beside Configuration.
The authenticated route is `/workspace/how-to`.

The category column stays in place while the article list scrolls independently.
Category selection shows only matching articles; All articles restores the full
list. Search is case-insensitive and includes the title, summary, menu path,
instructions and key form fields. It works without JavaScript. A title opens
a separate, printable article with steps, relevant limitations, a workspace
link and related guides. Empty searches offer a reset.

Content covers all 82 current module-menu entries, 17 Configuration entries and
the Dashboard: 100 guides for a private institute owner. Demo/staff sessions
exclude the three owner-only General Library/Leaves/Feedback articles, matching
the current menu: 97 guides. Front Desk, Student 360, AI Assistant, Canteen,
Shop, Transport and other absent modules are not invented as help categories.
The existing top navigation remains intact; the help category column is inside
the documentation page only.

The content describes SchoolFlow's actual workflows rather than copying vendor
articles. It preserves net-fee increments, working-calendar payroll, disabled
Sandwich Leave, immutable parent result publication and the limits of queued
communications, bank integrations, physical devices and asynchronous APK builds.
Reference-only layout switchers, vendor staff and unavailable delivery/read
receipts are not presented as working SchoolFlow features.

Help is read-only and uses no student, employee, fee or accounting queries.
Institute authentication still applies. Authenticated staff may read static
guides without receiving permission to open or mutate the linked workspace.
Those destination routes retain all existing access checks. There is no article
editor, record creation, external model call or outbound message in this change.
No schema, secret or storage configuration changes are required.

Tests check menu coverage, real destination routes, all 97 demo-visible article
pages, category/search behavior, escaped queries, unknown/private article IDs,
authentication, and staff destination permission boundaries. The existing
isolated Chromium CI adds mobile/desktop guide navigation and independent-scroll
checks. Local Chromium cannot run because its required process socket is denied;
browser CI results must be checked separately before claiming visual validation.
