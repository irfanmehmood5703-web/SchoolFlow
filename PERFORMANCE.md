# Navigation and admission form verification — 31 October 2026

Local benchmark: 500 fictional students, 250 families, 50 employees, 250 assigned plans and 1,000 numeric scores. Fresh in-memory SQLite per run; median of three warm test-client requests after one warmup. These measure backend work, not browser latency, network time or Render wake-up. Baseline is the prior local committed source; both runs use this runtime.

| Page | SQL before → after | Backend milliseconds before → after |
|---|---:|---:|
| `/workspace/dashboard` | 1014 → 13 | 114.77 → 13.75 |
| `/records/student` | 1004 → 8 | 184.58 → 5.05 |
| `/records/employee` | 154 → 7 | 32.44 → 4.51 |
| `/workspace/student-fee-plans?mode=update` | 2751 → 9 | 541.88 → 7.97 |
| `/workspace/certificates?campus=Demo+Campus` | 1035 → 8 | 173.04 → 19.42 |

Reproduce with `python scripts/benchmark_performance.py --students 500`. The script refuses a non-memory database and seeds only fictional data. Timings vary by machine.

Student/employee lists paginate in SQL and batch details/families; fee-plan lists paginate and batch latest plans; dashboard reads scalar aggregates and loads paper metadata together; certificate lists avoid per-pupil details/photo queries and defer image/issued-document payloads. Direct menu targets remove unnecessary redirects. Content-versioned public CSS/JS may be browser cached; school pages and private files stay no-store. No shared tenant data cache is introduced.

Admission form: standard gender, religion (including Other), blood groups, admission sources, disability, mother-tongue and guardian choices work without demo seeding. Every configurable dropdown can add an institute-owned option in place using a CSRF-protected endpoint; class options also appear for Class of Admission. Campuses/classes/sections/sessions/groups/houses/fee-plan names belong to the school, with no fictional values silently added to real institutes. Fee amounts still use fee schedule/plan workflows.

A selected photo gets a local preview. Saved photos display on edit, profile and list, with lazy list thumbnails; uploaded bytes remain private and uncached. Existing upload size/type checks still apply. A failed admission validation still requires reselecting a new file, as browsers do not repopulate file inputs.

Validation: `python -m unittest discover -s tests -q`. 125 tests cover record/photo round trips, replace/remove, previously empty setup, new options/duplicates/CSRF, school isolation, bounded SQL counts, complete CSV despite pagination, latest plans, direct menus, public asset caching/304, private no-store, variable paper totals and unchanged financial calculations, plus the existing suite.

Hosting limitation: Render free web services sleep after 15 minutes without incoming traffic; waking can take about one minute. Application query improvements cannot remove that platform delay. No paid hosting or keep-alive service was enabled. Reference: https://render.com/docs/free.

This remains a pre-test build. Persistent storage, full connected app permissions, mail/SMS providers and the other documented reference gaps are outstanding.
