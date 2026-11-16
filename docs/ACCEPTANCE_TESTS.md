# Acceptance tests (activity L)

Two layers of checks:

1. **Automated API checks**: run before every demo; they need no browser.
2. **Manual scenarios**: run in the browser against the live portal; this is the demo checklist.

## 1. Automated checks

Run from the project root, on your own copy of the database (the scripts change data and restore it):

```powershell
C:\Users\ilash\anaconda3\python.exe backend\tests\test_api.py        # access rights, grades, audit, attendance, feedback
C:\Users\ilash\anaconda3\python.exe backend\tests\test_syllabus.py   # grading scheme, syllabus, materials
C:\Users\ilash\anaconda3\python.exe backend\tests\test_features.py   # CSV import, reports, advising queue, announcements, daily scoring
```

Each script prints `ok` or `FAIL` per check and ends with `ALL PASSED` or the list of failed checks.
`test_features.py` contains 70 checks:

| Area | Checks | What is verified |
|---|---|---|
| G. CSV grade import | 23 | template download; access rights; empty file and wrong header rejected; dry run writes nothing; every row error named (unknown ID, not enrolled, duplicate, out of range, not a number, empty); all-or-nothing on errors; semicolon and decimal comma; drafts only; reason required to change a grade; audit log keeps reason and both scores; `skip_invalid`; file upload |
| E. Reports | 12 | four reports as CSV with one row per student; column per assessment; high risk first; attendance counts add up; access rights; unknown report; admin access |
| D. Curator queue and log | 13 | queue statistics; students who need attention first; add entry; overdue re-check raises the student; outcome closes the entry; only the author edits; teacher without access sees nothing |
| B. Announcements | 12 | teacher posts to own course only; enrolled students see it, others do not; university-wide only by admin; validation; delete by author only |
| F. Daily scoring and health | 10 | time parsing; next run today or tomorrow; off without the setting; second run skipped while one is in progress; run recomputes predictions; `/healthz` and `/readyz`; status is admin only |

Cross-student access (risk R7) is covered in `test_api.py` and, for the new endpoints, by the
"other teacher", "student" and "stranger" checks above.

## 2. Manual scenarios (demo checklist)

Accounts: student `2400003`, teacher and advisor `T001`, teacher `T002`, administrator `A001`.
Mark each scenario **Pass** or **Fail** and write the date and the tester's name at the bottom.

### Student

| ID | Scenario | Steps | Expected result | Result |
|---|---|---|---|---|
| S1 | Sign in | Open the portal, enter `2400003` and the password | Home page with the student's name and courses | |
| S2 | Wrong password | Enter a wrong password | Message "Wrong ID or password", no access | |
| S3 | Grades | Open **Grades**, expand a course | Only published grades are shown | |
| S4 | Risk | Open **Performance** | Risk level, weekly history and factors for a course; forecast starts at week 4 | |
| S5 | What-if | Move the What-if controls | The risk estimate changes; real data stays the same after reload | |
| S6 | Syllabus | **My Curriculum** → **View syllabus** | Grading scheme adds up to 100%, weekly plan is shown, no edit controls | |
| S7 | Attendance | Open **Attendance** | Counts per course and the absence percent | |
| S8 | Announcements | Open **Announcements** | Announcements of the student's courses and university-wide ones; no **New announcement** button | |
| S9 | Privacy | Sign in as another student and open **Grades** | Only that student's own data | |

### Teacher

| ID | Scenario | Steps | Expected result | Result |
|---|---|---|---|---|
| T1 | Sign in | Sign in as `T001` | Teacher menu with own courses only | |
| T2 | Grading scheme | **Syllabus** → add a category with weight 10 | Banner shows the total is not 100% and publishing is blocked | |
| T3 | Fix the scheme | Reduce another category by 10 | Banner "Scheme is complete: 100% / 100%" | |
| T4 | Enter a grade | **Gradebook** → type a score in an empty cell | "Saved"; grade status is draft | |
| T5 | Change a grade | Change an existing score | The portal asks for a reason; without it the change is cancelled | |
| T6 | Publish | Press **Publish grades**, then check as the student | The student now sees the grade | |
| T7 | Import: template | **Gradebook** → **Import CSV** → **Download template** | A CSV file with all enrolled students | |
| T8 | Import: errors | Put a wrong ID, a score above the maximum and a text score in the file → **Check file** | Three rows marked Error with the reason; **Import** is disabled; nothing is saved | |
| T9 | Import: clean file | Fix the file → **Check file** → **Import N grades** | "Imported N grades as drafts"; the scores appear in the gradebook as drafts | |
| T10 | Import: change | Change one score in the file and import again | A reason is required; after import the audit log has the old and the new score | |
| T11 | Reports | **More** → **Reports** → each of the four types → **Preview**, **Download CSV** | A table on the page and a CSV file that opens in Excel with one row per student | |
| T12 | Announcement | **More** → **Announcements** → **New announcement** → publish | It appears in the list; a student of that course sees it; a student of another course does not | |
| T13 | Class Insights | Open **Class Insights** | Students ordered by risk with the main factor and last contact | |
| T14 | Attendance | **Attendance** → mark a lesson → **Save attendance** | Marks are saved and shown to the students | |
| T15 | Foreign course | Sign in as `T002` and try to open a report of a `T001` course by its address | Access denied (403) | |

### Advisor

| ID | Scenario | Steps | Expected result | Result |
|---|---|---|---|---|
| A1 | Queue | Sign in as `T001` → **Advising** | Four numbers at the top match the table; students who need attention are first | |
| A2 | Log entry | Open a student → fill in the entry with a re-check date in the past → **Add entry** | Entry appears in the log; follow-up shows "Re-check due" | |
| A3 | Outcome | Type the outcome → **Record outcome** | Entry is closed; "Re-check due" disappears | |
| A4 | Not an advisor | Sign in as a teacher without advisees → **Advising** | "No advisees" | |

### Administrator and operations

| ID | Scenario | Steps | Expected result | Result |
|---|---|---|---|---|
| O1 | University-wide announcement | Sign in as `A001` → publish with "University-wide" | Every user sees it | |
| O2 | Daily scoring | Open `/api/admin/scoring-status` | Time of the last run and of the next scheduled run | |
| O3 | Health | Open `/healthz` and `/readyz` | `{"ok":true}` and `{"db":true,"ok":true}` | |
| O4 | Cold start (risk R2) | Open the deployed portal after 30 minutes of no use | First page loads in under 30 seconds | |
| O5 | Model check (risk R4) | Run `python -m backend.validate_model` | Table per week; the line about R4 says recall is not below 0.60 | |

Tested by: ____________  Date: ____________  Portal address: ____________
