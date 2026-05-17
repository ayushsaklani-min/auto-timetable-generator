export type CourseKind = 'theory' | 'lab' | 'activity'

export type FacultyInputMode = 'sections' | 'auto' | 'count' | 'same-as'

export interface CourseDraft {
  code: string
  name: string
  credits: number
  kind: CourseKind
  pairCourse: string
  lockedDay: string
  lockedSlotsText: string
  combined: boolean
  extraTypeText: string
  facultyMode: FacultyInputMode
  facultyNames: string[]
  facultyCount: number
  sameAsCode: string
}

const COURSE_HEADER_LINES = [
  '# CODE, NAME, CREDITS, TYPE, FACULTY1; FACULTY2; ...',
  '# TYPE: theory | lab | lab pair=CODE | activity | activity locked=DAY:slots | combined',
  "# Faculty: list one per section in order, or 'auto', 'xN', or 'same-as=CODE'",
  '',
]

const TYPE_RE = /^(theory|lab|activity)\b\s*(.*)$/i
const PAIR_RE = /\bpair\s*=\s*([A-Za-z0-9_]+)\b/i
const LOCKED_RE = /\blocked\s*=\s*([A-Za-z]+)\s*:\s*([\d,\-\s]+)/i
const COMBINED_RE = /\bcombined\b/i

function splitByFirstCommas(line: string, fieldsBeforeRemainder: number): string[] {
  const parts: string[] = []
  let remaining = line

  for (let i = 0; i < fieldsBeforeRemainder; i += 1) {
    const commaIndex = remaining.indexOf(',')
    if (commaIndex === -1) break
    parts.push(remaining.slice(0, commaIndex).trim())
    remaining = remaining.slice(commaIndex + 1)
  }

  parts.push(remaining.trim())
  return parts
}

function splitFacultySpec(spec: string): string[] {
  if (!spec.trim()) return []
  return spec
    .split(/\s*[;|/]\s*/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function parseFacultySpec(spec: string): Pick<CourseDraft, 'facultyMode' | 'facultyNames' | 'facultyCount' | 'sameAsCode'> {
  const trimmed = spec.trim()
  if (!trimmed) {
    return {
      facultyMode: 'sections',
      facultyNames: [],
      facultyCount: 1,
      sameAsCode: '',
    }
  }

  if (/^auto$/i.test(trimmed)) {
    return {
      facultyMode: 'auto',
      facultyNames: [],
      facultyCount: 1,
      sameAsCode: '',
    }
  }

  const countMatch = trimmed.match(/^x(\d+)$/i)
  if (countMatch) {
    return {
      facultyMode: 'count',
      facultyNames: [],
      facultyCount: Math.max(1, Number.parseInt(countMatch[1], 10) || 1),
      sameAsCode: '',
    }
  }

  const sameAsMatch = trimmed.match(/^same-as=(.+)$/i)
  if (sameAsMatch) {
    return {
      facultyMode: 'same-as',
      facultyNames: [],
      facultyCount: 1,
      sameAsCode: sameAsMatch[1].trim(),
    }
  }

  return {
    facultyMode: 'sections',
    facultyNames: splitFacultySpec(trimmed),
    facultyCount: 1,
    sameAsCode: '',
  }
}

function stripDirective(source: string, pattern: RegExp): string {
  return source.replace(pattern, ' ')
}

function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function normaliseDay(day: string): string {
  return day.trim().toUpperCase().slice(0, 3)
}

function parseTypeField(typeField: string) {
  const match = typeField.trim().match(TYPE_RE)
  if (!match) {
    throw new Error(`Bad type in "${typeField}". Expected theory, lab, or activity.`)
  }

  const kind = match[1].toLowerCase() as CourseKind
  const suffix = match[2]?.trim() ?? ''
  const pairCourse = kind === 'lab' ? suffix.match(PAIR_RE)?.[1] ?? '' : ''
  const lockedMatch = kind === 'activity' ? suffix.match(LOCKED_RE) : null
  const lockedDay = lockedMatch ? normaliseDay(lockedMatch[1]) : ''
  const lockedSlotsText = lockedMatch ? lockedMatch[2].trim() : ''
  const combined = COMBINED_RE.test(suffix)

  let extraTypeText = suffix
  extraTypeText = stripDirective(extraTypeText, PAIR_RE)
  extraTypeText = stripDirective(extraTypeText, LOCKED_RE)
  extraTypeText = stripDirective(extraTypeText, COMBINED_RE)

  return {
    kind,
    pairCourse,
    lockedDay,
    lockedSlotsText,
    combined,
    extraTypeText: collapseWhitespace(extraTypeText),
  }
}

export function parseCoursesText(text: string): CourseDraft[] {
  const rows: CourseDraft[] = []

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue

    const parts = splitByFirstCommas(line, 4)
    if (parts.length < 4) {
      throw new Error(`Course row needs at least 4 comma-separated fields: "${line}"`)
    }

    const [code, name, creditsText, typeField, facultySpec = ''] = parts
    const credits = Number.parseInt(creditsText, 10)
    if (!Number.isFinite(credits)) {
      throw new Error(`Invalid credits in "${line}"`)
    }

    const typeMeta = parseTypeField(typeField)
    const facultyMeta = parseFacultySpec(facultySpec)

    rows.push({
      code,
      name,
      credits,
      ...typeMeta,
      ...facultyMeta,
    })
  }

  return rows
}

export function buildFacultySpec(row: CourseDraft): string {
  switch (row.facultyMode) {
    case 'auto':
      return 'auto'
    case 'count':
      return `x${Math.max(1, Math.trunc(row.facultyCount || 1))}`
    case 'same-as':
      return row.sameAsCode.trim() ? `same-as=${row.sameAsCode.trim()}` : ''
    case 'sections':
    default:
      return row.facultyNames.map((name) => name.trim()).filter(Boolean).join('; ')
  }
}

export function buildTypeField(row: CourseDraft): string {
  const parts = [row.kind]

  if (row.kind === 'lab' && row.pairCourse.trim()) {
    parts.push(`pair=${row.pairCourse.trim()}`)
  }

  if (row.kind === 'activity' && row.lockedDay.trim() && row.lockedSlotsText.trim()) {
    parts.push(`locked=${normaliseDay(row.lockedDay)}:${row.lockedSlotsText.trim()}`)
  }

  if (row.combined) {
    parts.push('combined')
  }

  if (row.extraTypeText.trim()) {
    parts.push(row.extraTypeText.trim())
  }

  return parts.join(' ')
}

export function serializeCourseRow(row: CourseDraft): string {
  const base = `${row.code.trim()}, ${row.name.trim()}, ${Math.trunc(row.credits)}, ${buildTypeField(row)}`
  const facultySpec = buildFacultySpec(row)
  return facultySpec ? `${base}, ${facultySpec}` : base
}

export function serializeCoursesText(rows: CourseDraft[]): string {
  return [...COURSE_HEADER_LINES, ...rows.map(serializeCourseRow)].join('\n')
}
