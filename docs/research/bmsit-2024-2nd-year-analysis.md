# BMSIT 2024 Batch Second-Year Scheme Notes

Source set:
- `3aiml_2024batch.pdf`
- `4aiml_2024batch.pdf`
- `3cbcs_2024batch.pdf`
- `4csbs_2024batch.pdf`
- `3cse_2024batch.pdf`
- `4cse_2024batch.pdf`
- `3cv_2024batch.pdf`
- `4cv_2024batch.pdf`
- `3ece_2024batch.pdf`
- `4ece_2024batch.pdf`
- `3eee_2024batch.pdf`
- `4eee_2024batch.pdf`

Notes:
- The files are under the `2024-batch` folder, but the semester tables mostly say effective from AY `2025-26` because this batch reaches III and IV semester in that academic year.
- `4cse_2024batch.pdf` is image-based; its IV semester scheme was read by rendering the scheme page to PNG.

## Common scheduling patterns

- Most branches use `IPCC` courses: theory integrated with practical.
- Most branches also have `ESC/ETC/PLC` option groups.
- Most branches have `AEC/SEC` option groups where the chosen course may be theory or lab.
- `UHV`, `NSS/PE/Yoga/Music/NCC`, and lateral-entry `BENGDIP1/BENGDIP2` appear as shared institutional requirements.
- IV semester often adds `Biology for Engineers` or `Biology for Information Technology`.

## Computing branches

### AIML III semester
- `BCS301` Mathematics for Computer Science
- `BCS302` Digital Design and Computer Organization
- `BCS303` Operating Systems
- `BCS304` Data Structures and Application
- `BCSL305` Data Structures Lab
- `BCS306x` ESC/ETC/PLC
- `BCSK307` Social Connect and Responsibility
- `BCS358x` AEC/SEC
- MC activity block
- Total: `21` credits

### CSE III semester
- Same structure as AIML III semester
- Total: `21` credits

### CSBS III semester
- Same core structure as CSE/AIML III semester
- Total: `21` credits

### AIML IV semester
- `BCS401` Analysis and Design of Algorithms
- `BAI402` Artificial Intelligence
- `BCS403` Database Management Systems
- `BCSL404` Analysis and Design of Algorithms Lab
- `BXX405x` ESC/ETC/PLC
- `BAI456x` AEC/SEC
- `BBOC407` Biology for Information Technology
- `BUHK408` Universal Human Values
- MC activity block
- Total: `19` credits

### CSE IV semester
- `BCS401` Analysis and Design of Algorithms
- `BCS402` Microcontrollers
- `BCS403` Database Management Systems
- `BCSL404` Analysis and Design of Algorithms Lab
- `BCS405x` ESC/ETC/PLC
- `BCS456x` AEC/SEC
- `BBOC407` Biology for Information Technology
- `BUHK408` Universal Human Values
- MC activity block
- Total: `19` credits

### CSBS IV semester
- `BCS401` Analysis and Design of Algorithms
- `BCB402` Financial Management
- `BCS403` Database Management Systems
- `BCSL404` Analysis and Design of Algorithms Lab
- `BCX405x` ESC/ETC/PLC
- `BXX456x` AEC/SEC
- `BBOC407` Biology for Information Technology
- `BUHK408` Universal Human Values
- MC activity block
- Total: `19` credits

## Civil branch

### Civil III semester
- `BCV301` Strength of Materials
- `BCV302` Engineering Survey
- `BCV303` Engineering Geology
- `BCV304` Water Supply and Waste Water Engineering
- `BCV305` Computer Aided Building Planning and Drawing
- `BCV306x` ESC/ETC/PLC
- `BSCK307` Social Connect and Responsibility
- `BCV358x` AEC/SEC
- MC activity block
- Lateral-entry `BENGDIP1`

### Civil IV semester
- `BCV401` Analysis of Structures
- `BCV402` Fluid Mechanics and Hydraulics
- `BCV403` Transportation Engineering
- `BCVL404` Building Materials Testing Lab
- `BCV405x` ESC/ETC/PLC
- `BCV456x` AEC/SEC
- `BBOK407` Biology for Engineers
- `BUHK408` Universal Human Values
- MC activity block
- Lateral-entry `BENGDIP2`

## ECE branch

### ECE III semester
- `BMATEC301` Mathematics III for EC Engineering
- `BEC302` Digital System Design using Verilog
- `BEC303` Electronic Principles and Circuits
- `BEC304` Network Analysis
- `BECL305` Analog and Digital Systems Design Lab
- `BXX306x` ESC/ETC/PLC
- `BSCK307` Social Connect and Responsibility
- `BXX358x` AEC/SEC
- MC activity block

### ECE IV semester
- `BEC401` Engineering Electromagnetics
- `BEC402` Basic Signal Processing
- `BEC403` Principles of Communication Systems
- `BECL404` Communication Laboratory
- `BEC405x` ESC/ETC/PLC
- `BXX456x` AEC/SEC
- `BBOK407` Biology for Engineers
- `BUHK408` Universal Human Values
- MC activity block

## EEE branch

### EEE III semester
- `BMATE301` Mathematics III for EE Engineering
- `BEE302` Electric Circuit Analysis
- `BEE303` Analog Electronic Circuits
- `BEE304` Transformers and Generators
- `BEEL305` Transformers and Generators Lab
- `BEE306x` ESC/ETC/PLC
- `BSCK307` Social Connect and Responsibility
- `BEE358x` AEC/SEC
- `BCUK359` Cultural
- Lateral-entry `BENGDIP1`

### EEE IV semester
- `BEE401` Electric Motors
- `BEE402` Transmission and Distribution
- `BEE403` Microcontrollers
- `BEEL404` Electric Motors Lab
- `BEE405x` ESC/ETC/PLC
- `BEEL456x` AEC/SEC
- `BBOK407` Biology for Engineers
- `BUHK408` Universal Human Values
- MC activity block

## What this means for the scheduler

- We need a first-class `IPCC` model, not just plain theory vs lab.
- We need option-group modeling for `ESC/ETC/PLC` and `AEC/SEC`.
- We need cross-branch faculty pools:
  - Maths teaches multiple branches.
  - CS teaches CSE, AIML, and CSBS common core.
  - BT/CHE handles biology in IV semester across branches.
  - Humanities / common institutional courses cut across all branches.
- We need resource types, not just room names:
  - CS lab
  - CAD / drawing lab
  - ECE hardware lab
  - EEE machine lab
  - Civil drawing / testing / survey support
- We need separate handling for:
  - regular timetable courses
  - MC activity blocks
  - lateral-entry bridge courses
  - fixed or semi-fixed common institutional slots

## Practical product direction

- Model input at college level, not one department at a time.
- Solve III and IV semester sections together if faculty are shared.
- Store teacher ownership per course component, not only per subject name.
- Allow one syllabus course to generate linked lecture + practical tasks.
- Keep validation strict: impossible faculty load, lab overbooking, and teacher clashes must fail early with clear errors.
