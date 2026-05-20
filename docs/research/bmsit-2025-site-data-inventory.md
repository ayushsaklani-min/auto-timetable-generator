# BMSIT 2025 Site Data Inventory

Date of analysis: 2026-05-20
Primary page: `https://bmsit.ac.in/autonomous.php#2025`

## What the 2025 page contains

The `2025 Batch` section on the autonomous page currently links to:

1. `2025 Batch CIE and SEE pattern for UG Students`
2. `2025 Batch First Year Scheme`
3. `2025 Scheme & Syllabus`
4. `2025 Scheme & Syllabus - M.Tech ECE VLSI System Design`
5. `2025 Batch` for `M.Tech CSE`
6. `2025 Batch` for `MBA`
7. `2025 Batch` for `MCA`

Resolved official document URLs:

- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/2025%20Batch%20CIE%20and%20SEE%20pattern%20for%20UG%20Students.pdf`
- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/2025%20Batch_First%20Year%20Scheme_%20AY%202025-2026.pdf`
- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/2025%20Scheme%20%26%20Syllabus.pdf`
- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/mtechece_2025batch.pdf`
- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/Signed%20M.Tech%202024%20Scheme%20Syllabus%20-%202025-26.pdf`
- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/MBA_2025.pdf`
- `https://bmsit.ac.in/img/pdf/autonomous/2025-batch/MCA_2025.pdf`

Local copies were saved under this folder.

## Program coverage from the 2025 section

### UG

- Only first-year B.E. curriculum is present in the `2025` section.
- There are no branch-wise `III+ semester` UG links under `2025` because those students are only in first year.
- The detailed first-year syllabus PDF covers I and II semesters for multiple streams.

### PG

- `M.Tech VLSI System Design` has a 2025-scheme document.
- `M.Tech CSE` is linked from the 2025 page, but the linked document itself is labeled as `2024 Scheme` for AY `2025-26`.
- `MBA` is linked from the 2025 page, but the PDF itself is labeled as `2024 Scheme`.
- `MCA` is linked from the 2025 page, but the PDF itself is labeled as `2024 Scheme`.

Important modeling note:

- `batch year` and `scheme year` are not always the same.
- The scheduler data model should store both:
  - `admission_batch`
  - `scheme_version`

## What each source gives us

### 1. 2025 Batch CIE and SEE pattern for UG Students

Useful data:

- CIE weightage `50%`
- SEE weightage `50%`
- minimum CIE passing threshold
- minimum SEE passing threshold
- combined passing threshold
- separate assessment patterns for:
  - `IPCC` courses
  - `PCC/ESC/PEC/OEC` style theory courses
  - practical-heavy structures

Scheduler relevance:

- Low for slot generation
- Medium for course typing
- Helps distinguish:
  - theory-only courses
  - integrated theory+practical courses
  - pure practical courses

Use in our model:

- store `assessment_pattern_type`
- store `course_component_type`
- keep `IPCC` as a first-class course structure

### 2. 2025 Batch First Year Scheme

Useful data:

- semester-level template for first-year UG
- I semester and II semester structure
- course categories:
  - `BSC`
  - `BSC (IC)`
  - `ESC`
  - `ETC`
  - `PSC`
  - `PSCL`
  - `PLC (IC)`
  - `AEC`
  - `HSMC`
  - `NCMC`
- credit/contact-hour patterns
- stream-specific course codes for:
  - Mathematics
  - Physics
  - Chemistry
  - Computer Aided Engineering Drawing
  - ESC-I and ESC-II
  - PSC / PSCL
  - Programming Language Course
- first-year rule notes:
  - integrated courses combine theory and practical
  - Maths / Physics / Chemistry should be taught by a single faculty per session
  - ESC-I and ESC-II should not duplicate the student's own stream
  - interdisciplinary project is cross-discipline
  - activity points are mandatory

Scheduler relevance:

- High
- Gives the first-year structural template before faculty mapping

Use in our model:

- `course_category`
- `course_code`
- `stream_group`
- `lecture/tutorial/practical split`
- `same-faculty-delivery flag`
- `cross-stream eligibility rules`

### 3. 2025 Scheme & Syllabus

Useful data:

- detailed first-year syllabus
- full list of subject names, codes, hours, credits, and course descriptions
- stream groupings such as:
  - `CSE, AIML, CSBS` common clusters
  - `ECE, EEE` common clusters
  - separate `ME` and `CV` tracks
- detailed subject-level structure for:
  - math
  - physics / chemistry
  - AI intro
  - programming
  - foundational engineering courses
  - laboratories
  - communication / design / project courses

Scheduler relevance:

- High
- Best official source for first-year course templates and stream-level variants

Use in our model:

- create master `course templates`
- identify `hybrid` courses
- generate linked lecture/lab components

### 4. M.Tech ECE VLSI System Design

Useful data:

- full `I-IV` semester scheme
- semester-wise credits and course lists
- `IPCC`, `PCC`, `PCCL`, `PEC`, `AEC`, `INT`, `PW`
- elective baskets
- internship and project phase structure

Examples:

- I semester includes `ASIC Design`, `Digital System Design`, `Digital IC Design`, electives, and `Digital IC Design lab`
- II semester includes `Physical Design`, `Analog IC Design`, `VLSI Testing`, `System Verilog for Verification`, electives, and labs
- III semester moves heavily into `NPTEL online courses`, internship phase-I, and project phase-I
- IV semester is internship phase-II plus project phase-II

Scheduler relevance:

- High for semesters I and II
- Medium for semesters III and IV because they are dominated by internship/project components

Use in our model:

- course mode:
  - `classroom`
  - `lab`
  - `online`
  - `internship`
  - `project`
- semester-specific intensity and project load

### 5. M.Tech CSE (linked under 2025 page)

Useful data:

- scheme document for AY `2025-26`
- document label says `2024 Scheme`
- `I-IV` semester structure visible in the scanned pages

Examples extracted from scheme pages:

- I semester:
  - `Applied Mathematics`
  - `Advanced Algorithms`
  - `Artificial Intelligence`
  - `Fundamentals of Data Science`
  - `Cryptography and Network Security`
  - `Artificial Intelligence Laboratory`
  - `No SQL Database Laboratory`
  - `Research Methodology and IPR`
- II semester:
  - `Machine Learning`
  - `Internet of Things`
  - `Specialization Course-I`
  - `Specialization Course-II`
  - `Specialization Course-III`
  - `Web Applications Development Laboratory`
  - `Ability/Skill Enhancement Course`
- III semester:
  - multiple `NPTEL` online courses
  - internship phase-I
  - project phase-I
- IV semester:
  - internship phase-II
  - project phase-II

Scheduler relevance:

- High for semesters I and II
- Medium for semesters III and IV

Use in our model:

- same as VLSI:
  - `online course`
  - `internship`
  - `project`
  - `specialization basket`

### 6. MBA 2025

Useful data:

- linked from 2025 page, but PDF is `2024 Scheme`
- `I-IV` semester structure
- core management courses in semesters I and II
- electives in semesters III and IV
- internship, project, experiential learning, audit courses
- specialization baskets:
  - Finance
  - Marketing
  - Human Resource
  - Business Analytics

Scheduler relevance:

- Medium to High
- MBA is more classroom-heavy in semesters I and II
- semesters III and IV mix electives, internship, and project

Use in our model:

- `program_type = MBA`
- `specialization`
- `audit / experiential` course types
- `internship/project` types

### 7. MCA 2025

Useful data:

- linked from 2025 page, but PDF is `2024 Scheme`
- `I-IV` semester structure
- core computing subjects in I and II sem
- electives / specializations in III sem
- online course + internship + project in IV sem
- non-credit communication / soft-skills and online RM/IPR components

Examples:

- I semester:
  - `Mathematical Foundation for Computer Applications`
  - `Java Programming`
  - `Data Structures and Algorithms`
  - `DBMS`
  - `Operating System with Unix`
  - multiple labs
- II semester:
  - `Full Stack Development`
  - `Machine Learning`
  - `Mobile Application Development`
  - `Cloud Computing`
  - `Computer Networks`
  - elective
- III semester:
  - three specialization electives
  - project phase-I
- IV semester:
  - online emerging technology / certification
  - internship
  - project phase-II

Scheduler relevance:

- High for semesters I and II
- Medium for semesters III and IV

Use in our model:

- `specialization basket`
- `lab-linked theory`
- `online course`
- `internship`
- `project`

## Additional official site sources we also need

The autonomous page alone is not enough for timetable generation.

### A. Circulars / Calendar of Events

Relevant page:

- `https://bmsit.ac.in/circular.php`

What it gives:

- batch-specific exam notices
- `Calendar of Events` PDFs for:
  - B.E. 1st semester
  - B.E. 3rd semester
  - B.E. 5th and 7th semester
  - B.E. 2nd / 4th / 6th / 8th semester
  - MCA / MBA / M.Tech semesters
- latest SEE timetable notices

Scheduler relevance:

- Very high

Use in our model:

- semester start/end dates
- CIE windows
- SEE blackout windows
- holidays
- odd/even semester boundaries

### B. Timetable PDFs

Relevant sources discovered from official search:

- `https://bmsit.ac.in/public/assets/pdf/timetable/1cse.pdf`
- `https://bmsit.ac.in/public/assets/pdf/timetable/5cse.pdf`
- `https://bmsit.ac.in/public/assets/pdf/timetable/7cse.pdf`
- `https://bmsit.ac.in/public/assets/pdf/timetable/1mtechvlsi2025.pdf`
- `https://bmsit.ac.in/public/assets/pdf/timetable/6ece.pdf`
- `https://bmsit.ac.in/img/pdf/timetable/4ece%28new%29.pdf`

What they give:

- actual slot timings
- short-break / lunch-break positions
- classroom names
- class teacher or PG coordinator
- section labels
- lab block durations
- proctoring, club activity, major project, mandatory-course blocks
- Saturday usage notes

Observed examples from current official timetable snippets:

- first-year CSE timetable shows a revised I-semester B.E. timetable for AY `2025-26`
- VLSI timetable shows exact day/slot layout and notes that first and third Saturdays are holidays
- ECE timetable shows real classroom names and parallel lab usage

Scheduler relevance:

- Very high

Use in our model:

- `time template`
- `slot labels`
- `fixed breaks`
- `day pattern`
- `section-room mapping`

### C. Department pages

Examples:

- `https://bmsit.ac.in/dep-cse.php`
- `https://bmsit.ac.in/dep-csbs.php`
- `https://bmsit.ac.in/dep-mca.php`
- `https://bmsit.ac.in/dep-mba.php`
- `https://bmsit.ac.in/dep-cse-mtech.php`

What they give:

- faculty names
- faculty emails
- employee IDs
- expertise areas
- sometimes department-level organizational data

Scheduler relevance:

- Medium

Use in our model:

- build faculty master list
- infer department ownership
- seed faculty pools by specialization

Important limitation:

- the site does **not** provide the actual `faculty -> section -> course` teaching assignment in a clean machine-readable form.

## Data we can collect automatically from the site

### Directly usable

- program list
- batch list
- scheme version
- semester list
- course codes
- course titles
- course categories
- credit distribution
- L/T/P split
- some common rules for integrated courses
- elective basket names
- online / internship / project markers
- activity / MC / audit / NCMC markers
- current timetable slot patterns
- academic calendar documents
- faculty directory entries

### Derivable with moderate processing

- stream clusters
- shared common-course groups
- lab-required vs theory-only classification
- semester load totals
- resource-type hints:
  - CS lab
  - VLSI lab
  - CAD / drawing
  - communication lab
- common institutional blocks:
  - NSS / Yoga / club activity / proctoring / projects

## Data still missing for actual timetable generation

The site does not provide enough to solve the timetable end to end.

We still need these from college admins or department coordinators:

1. Exact section list per semester and branch
2. Current student strength per section
3. Actual faculty-course-section mapping for the semester
4. Faculty co-teaching / lab-sharing patterns
5. Faculty unavailability and preferred days
6. Room inventory with capacities
7. Lab inventory with machine/equipment constraints
8. Which electives are actually running this semester
9. Which students/sections chose which electives
10. Cross-department shared faculty list
11. Fixed non-academic blocks:
    - mentoring
    - tutorials
    - placement training
    - club/IIC/activity windows
12. Department rules on parallel labs and batch splits
13. Saturday policy for the current semester
14. Allowed room substitutions
15. Institution-wide blocked dates from the calendar

## Recommended normalized scheduler schema

Minimum entities:

- `Institution`
- `AcademicYear`
- `Term`
- `Program`
- `Department`
- `SchemeVersion`
- `Semester`
- `Section`
- `CourseTemplate`
- `CourseOffering`
- `CourseComponent`
- `Faculty`
- `TeachingAssignment`
- `Room`
- `RoomType`
- `CalendarRule`
- `TimeTemplate`
- `ElectiveGroup`

Important fields:

- `batch_year`
- `scheme_year`
- `program_name`
- `semester_number`
- `section_name`
- `course_code`
- `course_title`
- `course_category`
- `component_type`
- `l_hours`
- `t_hours`
- `p_hours`
- `credits`
- `faculty_ids`
- `room_type_required`
- `fixed_slot`
- `shared_with_programs`
- `is_online`
- `is_project`
- `is_internship`

## Practical conclusion

From the official BMSIT site we can collect enough to build:

- curriculum master data
- semester templates
- slot structure templates
- faculty directory seeds
- calendar constraints

But we cannot generate a real college timetable from the site alone.

The site is missing the most operational inputs:

- actual teaching assignments
- section counts
- room inventory
- faculty availability
- running elective choices

That means the correct plan is:

1. ingest all curriculum and calendar data from the site
2. build a manual/admin input layer for operational semester data
3. solve all sections sharing faculty in one combined run
