# SDU Smart Education Portal — User Guide

This guide explains how students, teachers and advisors use the portal. It describes the live
version (the portal connected to the database). In demo mode the same screens show sample data.

## 1. Signing in

1. Open the portal address in a browser.
2. Enter your portal ID and password and press **Sign in**. Accounts are created by the administrator;
   there is no self-registration.
3. The menu you see depends on your role: student, teacher or administrator. An advisor is a teacher
   who has students assigned to them.

Demo accounts of the test database: student `2400003`, teachers `T001` (also an advisor) and `T002`,
administrator `A001`. Their passwords are printed by the data generator.

If you see "Wrong ID or password", check the keyboard layout. Passwords can be reset only by the administrator.

## 2. For students

| Section | What you can do |
|---|---|
| **Home** | See today's classes, upcoming deadlines and a summary of your courses. |
| **Courses** | Open a course to see its syllabus, materials, assignments and announcements. |
| **My Curriculum** | See the full SDU course catalogue with your status in each course. **View syllabus** opens the grading scheme and weekly plan of a course that runs this semester. |
| **Grades** | See your grades per course. Only grades that the teacher has published are shown; a grade still in draft is not visible. |
| **Performance** | See your risk level for each course, how it changed week by week, and the main factors behind it. |
| **Attendance** | See your attendance in each course and how close you are to the absence limit. |
| **Messages** | Write to your teachers and read their replies. |
| **Feedback** | Answer course surveys. Answers are anonymous: the portal stores the fact that you answered separately from the answer itself. |
| **Announcements** | Read announcements of your courses and university-wide announcements. |

### How to read the risk level

- The forecast appears from **week 4** of the semester; before that there is too little data.
- The level is **Low**, **Medium** or **High**. It is an early warning, not a final grade.
- The factors explain what raised or lowered the level, for example missed assignments or a low average score.
- The forecast uses your submissions, published grades and activity in the course. It does not use
  personal attributes such as gender, age or region.
- The **What-if** controls on the Performance page show how the risk would change if, for example,
  you submitted the missing work. They do not change your real data.

If you think a grade or an attendance mark is wrong, write to the teacher in **Messages**.

## 3. For teachers

| Section | What you can do |
|---|---|
| **My courses** | See your courses with the number of students and the share at risk. |
| **Syllabus** | Set the grading scheme and the weekly plan of a course. |
| **Gradebook** | Enter grades, import them from a CSV file and publish them. |
| **Class Insights** | See which students are at risk in a course, how the picture changed this week and why. |
| **Attendance** | Mark attendance for a lesson and review excuse documents. |
| **Advising** | For advisors: the queue of your advisees and the intervention log. |
| **Messages** | Write to students. |
| **Course Feedback** | See survey results once at least 5 students have answered. |
| **Reports** | Download course reports as CSV files. |
| **Announcements** | Publish announcements for your courses. |

You see only your own courses and their students. Risk across all of a student's courses is visible
only to that student's advisor.

### 3.1 Syllabus and grading scheme

1. Open **Syllabus** and choose the course.
2. Add categories (for example Quizzes, Midterm, Final) and set the weight of each. The weights must add up to **100%**.
3. In each category press **Add assessment** and set the title, type, date, maximum points and weight.
4. Publish each assessment with **Draft · publish**. Students do not see an assessment until it is published,
   and nothing can be published while the weights do not add up to 100%.
5. Fill in **Weekly topics** and press **Save plan**.

Once an assessment has grades, its maximum score cannot be changed and it cannot be deleted.
After the scheme changes, the risk of the course is recalculated automatically.

### 3.2 Entering and publishing grades

1. Open **Gradebook**, choose the course and the assessment.
2. Type a score in the student's row; it is saved when you leave the cell.
3. Changing a grade that already exists asks for a **reason**. The reason, the old score and the new score
   are stored in the audit log.
4. Press **Publish grades** to make all draft grades of this assessment visible to students.

### 3.3 Importing grades from a CSV file

Use this when grades were kept in Excel or exported from another system.

1. In **Gradebook** choose the course and the assessment and press **Import CSV**.
2. Press **Download template**. The file lists every enrolled student with the columns
   `student_id`, `last_name`, `first_name`, `score`, `comment`.
3. Fill in the `score` column and save the file as CSV. The `student_id` column must stay as it is:
   it is the student's portal ID.
4. Choose the file and press **Check file**. Nothing is saved at this step. The table shows every row:

   | Result | Meaning |
   |---|---|
   | New | The student has no grade yet; a draft grade will be created. |
   | Update | The student already has a different grade; it will be replaced. |
   | Unchanged | The score in the file is the same as in the gradebook. |
   | Error | The row cannot be imported; the reason is shown next to it. |

5. Fix the errors in the file and check it again. Typical errors: an ID that does not exist, a student
   who is not enrolled in this course, the same student twice, an empty score, a score that is not a
   number, a score below 0 or above the maximum.
6. If the file changes existing grades, type the **reason**.
7. Press **Import N grades**. If any row has an error, nothing is imported unless you tick
   **Skip the rows with errors and import the rest**.
8. Imported grades are **drafts**. Check them in the gradebook and press **Publish grades**.

The file may use a comma or a semicolon as the separator, and a comma or a point in decimal numbers
(`17,5` and `17.5` are both accepted). Limits: 1 MB and 2000 rows.

### 3.4 Reports

1. Open **Reports** (in the **More** menu), choose the course and the report type.
2. **Preview** shows the first rows on the page; **Download CSV** saves the whole report. The file opens in Excel.

| Report | Content |
|---|---|
| Course performance | Current percent, letter grade, absences and risk level for every student. |
| Attendance summary | Present, late, absent and excused lessons, and who is over the absence limit. |
| Gradebook export | One column per assessment with every score, including grades not yet published. |
| Student risk overview | Risk level, change since last week, expected score range, main factors, last contact; highest risk first. |

### 3.5 Announcements

1. Open **Announcements** (in the **More** menu) and press **New announcement**.
2. Choose the course, type the title and the text and press **Publish**.
3. Students enrolled in that course see the announcement immediately. You can delete your own announcements.

University-wide announcements can be published only by the administrator.

### 3.6 Attendance

1. Open **Attendance**, choose the course and the lesson.
2. Mark each student as present, late, absent or excused and press **Save attendance**.
3. Excuse documents sent by students appear for review; an approved document turns the absence into "excused".

## 4. For advisors

The **Advising** page is a work queue. Students who need attention are at the top.

A student **needs attention** when:

- the overall risk is **High** and there has been no contact for more than 14 days (or no contact at all), or
- the date of a planned re-check has come and the outcome of that intervention is not recorded yet.

How to work with the queue:

1. Open **Advising**. The cards at the top show how many advisees you have, how many need attention,
   how many have a high overall risk and how many have been contacted.
2. Press the arrow in a student's row to open the **intervention log** of that student.
3. After talking to the student, choose the type (meeting, message, referral, other), write what was done
   or agreed, optionally set a **Re-check on** date, and press **Add entry**.
4. When the result is known, type it in the **Outcome** field of that entry and press **Record outcome**.
   The entry is then closed and no longer puts the student back in the queue.

**Recent interventions** at the bottom shows the latest entries you are allowed to see: your own,
those about your advisees, and course-level entries of the courses you teach.

## 5. For the administrator

- Sees every course and can open every report.
- Can publish university-wide announcements.
- Risk recalculation runs every night. `GET /api/admin/scoring-status` shows the last and the next run;
  `POST /api/admin/scoring-run` starts it immediately.

## 6. Sections that show sample data

These sections are prepared in the interface but are not connected to the database yet:
**Study Planner, Transcript, Course Registration, Documents, Support, Library, Help / FAQ, Office hours**
and the **AI Assistant** (marked "demo"). What you enter there is not saved.

## 7. Privacy rules built into the portal

- A student sees only their own data and only published grades.
- A teacher sees only the students of the courses they teach.
- An advisor sees the overall risk only of their own advisees.
- Survey answers are anonymous and are shown only when at least 5 students have answered.
- Every grade change is recorded with the author, the time and the reason, and this record cannot be edited.
- The demo database contains generated data only; no real student records are used.

## 8. If something goes wrong

| What you see | What to do |
|---|---|
| The page does not open | Check the address and the internet connection. On the first visit after a long pause the server may need up to a minute to start. |
| "Wrong ID or password" | Check the ID and the keyboard layout, or ask the administrator to reset the password. |
| A section says it is available only with the live backend | The portal is running in demo mode; ask the team to switch it to the live database. |
| A grade is not visible to the student | The grade is still a draft: the teacher has to press **Publish grades**. |
| The risk level did not change after new grades | The risk is recalculated once a day, and immediately when the grading scheme changes. |
| "The file has rows with errors, nothing was saved" | Open the table under the message, fix those rows in the file and check it again. |
