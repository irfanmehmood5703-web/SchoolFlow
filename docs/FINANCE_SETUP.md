# Finance setup — first reference batch

Implemented: Accounting Periods, GL Account Groups, GL Accounts and Chart of Accounts with print/PDF view. The top Management navigation now has a Finance section. Existing Admissions payments, payroll and Core Settings remain separate and unchanged.

Periods: real create/view/edit/delete with Begin, End and Is Closed, overlap rejection, audit actor/times and optimistic version checks. Changing closed-period dates requires reopening first. Delegated staff additionally need all-campus finance.approve to close/reopen.

Groups: five account classes, create/view/edit/delete, active/inactive status, filters and sort/pagination. An explicit Add standard GL groups action adds the eleven generic school-accounting groups; GET requests do not populate data. Groups with accounts cannot be deleted or moved to another class.

Accounts: server-assigned unique codes, editable name/group/inactive state, searchable grouped selector, live client code preview, case-insensitive duplicate-name checks. Codes 2000–2099 and 4000–4099 are reserved. New user accounts use the remaining class range; reserved/system account provisioning and fee-head mapping await ledger integration. Existing account codes survive renames and same-class group changes. No third-party school’s 57 saved accounts or historical timestamps are silently copied.

Chart: derives every group/account from the current school database and groups by Assets, Liabilities, Equity, Income and Expense. Uses SchoolFlow school branding/logo and a print stylesheet with repeated table headers. No invented balances.

Security: CSRF, institute routing, institute write lock, audit events, optimistic versions, FK constraints and separate default-deny Finance permissions. Every delegated Finance grant must cover every configured campus because these masters are school-wide. Chart print requests require finance.print. Existing schools require the additive `flask --app app institute-upgrade` CLI before using the new master tables. The isolated Gate trial launcher adds missing tables only in its own explicitly opted-in institute. No main deployment restart or schema update is performed.

Scope boundary: these are Finance masters/reporting. Journals, double-entry posting, account balances, opening balances, automatic fee/payroll reconciliation, requisitions and ledger reports are not implemented in this batch. Period Closed currently protects master editing; future journal posting must reject closed-period transactions and protect referenced period/account deletion. Public trial storage remains temporary; this change does not fix hosting data durability.

Verification covers period overlap/closure/version checks, CSRF, duplicate validation, server-owned codes, retired groups, references, filtered lists, chart/print route, audit history, tenant separation and all-campus staff permissions. Browser/PDF visual QA remains pending: the local browser runtime download was unavailable. No claim of rendered PDF/device verification is made.

Final backend suite: 514 tests passed in 162.055 seconds. Python compilation, JavaScript syntax check and git diff whitespace validation passed.

