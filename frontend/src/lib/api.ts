// API client for the FastAPI backend.

export type Day = 'MON' | 'TUE' | 'WED' | 'THU' | 'FRI' | 'SAT'

export interface ScheduledClass {
  section_id: string
  course_code: string
  faculty_id?: string | null
  day: string
  slot: number
  is_lab?: boolean
  batch_id?: string | null
  room?: string | null
  label?: string | null
}

export interface Timetable {
  classes: ScheduledClass[]
  status: string
  cost: number | null
  solve_time_sec: number
  notes: string[]
}

export interface Violation {
  code: string
  message: string
  details: Record<string, unknown>
}

export interface VerificationReport {
  ok: boolean
  violations: Violation[]
  soft_score: number
}

export interface PreflightReport {
  ok: boolean
  errors: string[]
  warnings: string[]
}

export interface Section {
  id: string
  name: string
  semester: number
  classroom: string
  batches: { id: string; section_id: string }[]
}

export interface Faculty {
  id: string
  name: string
  assignments: { course_code: string; section_id: string; is_lab: boolean }[]
}

export interface Course {
  code: string
  name: string
  credits: number
}

export interface TimetableRequest {
  time_config: {
    days: string[]
    slots_per_day: number
    slot_timings: { start: string; end: string }[]
    tea_break: { after_slot: number; duration_min: number }
    lunch_break: { after_slot: number; duration_min: number }
    saturday_rules: {
      inactive_weeks: number[]
      locked_slots: { day: string; slot: number; label: string; applies_to_sections?: string[] }[]
    }
  }
  sections: Section[]
  courses: Course[]
  faculty: Faculty[]
  elective_blocks: any[]
  time_limit_sec: number
  seek_optimal: boolean
}

export interface GenerateResponse {
  job_id: string
  preflight: PreflightReport
  timetable: Timetable | null
  verification: VerificationReport | null
}

const API = '/api'

async function readErrorMessage(r: Response): Promise<string> {
  const txt = (await r.text()).trim()
  try {
    const parsed = JSON.parse(txt)
    if (typeof parsed?.detail === 'string' && parsed.detail.trim()) return parsed.detail
    if (typeof parsed?.error === 'string' && parsed.error.trim()) return parsed.error
    if (Array.isArray(parsed?.detail)) {
      const first = parsed.detail.find((x: any) => typeof x?.msg === 'string')
      if (first?.msg) return first.msg
    }
  } catch {
    // fall back to raw text below
  }
  return `${r.status} ${txt.slice(0, 300)}`
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(API + path)
  if (!r.ok) throw new Error(await readErrorMessage(r))
  return r.json()
}
async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await readErrorMessage(r))
  return r.json()
}

export const api = {
  health: () => jget<{ status: string }>('/health'),
  bmsitReference: () => jget<TimetableRequest>('/reference/bmsit_4th_sem'),
  preflight: (req: TimetableRequest) => jpost<PreflightReport>('/preflight', req),
  generate: (req: TimetableRequest) => jpost<GenerateResponse>('/generate', req),
  llmParse: (text: string, prior?: TimetableRequest) =>
    jpost<{
      action: string
      message: string
      applied?: string[]
      errors?: string[]
      request?: TimetableRequest
      timetable?: Timetable
      verification?: VerificationReport
      preflight?: PreflightReport
      job_id?: string
      active_model?: string
    }>('/llm/parse', {
      text,
      prior_request: prior,
      start_from_bmsit: !prior,
    }),
  llmExplain: (job_id: string) => jpost<{ explanation: string }>('/llm/explain', { job_id }),
  exportUrl: (job_id: string, fmt: 'pdf' | 'xlsx' | 'json', faculty_id?: string) => {
    const q = faculty_id ? `?faculty_id=${encodeURIComponent(faculty_id)}` : ''
    return `${API}/job/${job_id}/export/${fmt}${q}`
  },
}
