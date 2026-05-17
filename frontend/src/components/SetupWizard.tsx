import { useMemo, useState } from 'react'
import { GenerateResponse, TimetableRequest } from '../lib/api'
import CoursesFacultyPanel from './CoursesFacultyPanel'

const API = '/api'

const DEFAULT_TIMINGS = [
  ['08:30', '09:25'],
  ['09:25', '10:20'],
  ['10:40', '11:35'],
  ['11:35', '12:30'],
  ['13:25', '14:20'],
  ['14:20', '15:15'],
  ['15:15', '16:10'],
]

const DEMO_PASTE = `# CODE, NAME, CREDITS, TYPE, FACULTY1; FACULTY2; ...
# TYPE: theory | lab | lab pair=CODE | activity | activity locked=DAY:slots
# Faculty: list one per section in order, or 'auto', 'xN', or 'same-as=CODE'

BCS401, Analysis & Design of Algorithms, 3, theory, Dr Sampath K; Dr Rajesh I S; Prof Soumya V L; Prof Shobith T; Prof Balaraju G; Dr Manoj H M
BAI402, Artificial Intelligence, 3, theory, Prof Kavitha D; Prof Salma Itagi; Dr Srivani P; Prof Shilpa Patil; Dr Vani Krishnaswamy; Prof Bhavika Rajora
BAI402_LAB, AI Lab, 1, lab pair=BCSL404, same-as=BAI402
BCSL404, ADA Lab, 1, lab pair=BAI402_LAB, same-as=BCS401
BCS403, Database Management Systems, 3, theory, Dr Archana Bhat; Prof Amitha S K; Prof Indumati; Dr Chidananda K; Prof Ashwini S; Prof Megha S
BCS403_LAB, DBMS Lab, 1, lab, same-as=BCS403
BAIL456B, MongoDB Lab, 1, lab pair=BAIL456C, auto
BAIL456C, MERN Lab, 1, lab pair=BAIL456B, auto
BBOK407, Biology for Engineers, 2, theory, Prof Nagi Teja Reddy
BUHK408, Universal Human Values, 1, theory, Dr Rajesh I S; Dr Chidananda K; Dr Hemamalini B H; Dr Kantharaju V; Dr Niranjanamurthy M; Dr Vani Krishnaswamy

# Elective option courses — referenced by the elective block below
BCS405A, Discrete Mathematical Structures, 3, theory
BCS405C, Optimization Techniques, 3, theory
BAI405D, Algorithmic Game Theory, 3, theory

# Activities — flex placement
CRC, CRC, 0, activity, CRC Coord
PROCTORING, Proctoring, 0, activity, Proctoring Coord
TUTORIAL, Tutorial Class, 0, activity, Tutorial Coord
REMEDIAL, Remedial Class, 0, activity, Remedial Coord
NCMC, NCMC - Cultural, 0, activity, Dr Soumya (NCMC)

# Activities — locked
DEPT_ACT, Dept Activity, 0, activity locked=FRI:5-7, Dept Activity Coord`

interface Props {
  onCancel: () => void
  onGenerated: (resp: GenerateResponse, req: TimetableRequest) => void
}

interface ElectiveOption {
  course_code: string
  course_name: string
  faculty: string  // comma-separated names
}
interface ElectiveBlockDraft {
  id: string
  name: string
  weekly_slot_count: number
  locked_slots_text: string  // "MON-2, TUE-3, THU-3, FRI-3"
  options: ElectiveOption[]
}

export default function SetupWizard({ onCancel, onGenerated }: Props) {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{
    sections: number
    courses: number
    faculty: number
    elective_blocks: number
  } | null>(null)
  const [preflightErrors, setPreflightErrors] = useState<string[]>([])

  // Step 1 state
  const [nSections, setNSections] = useState(6)
  const [semester, setSemester] = useState(4)
  const [slotsPerDay, setSlotsPerDay] = useState(7)
  const [teaAfter, setTeaAfter] = useState(2)
  const [lunchAfter, setLunchAfter] = useState(4)
  const [days, setDays] = useState<string[]>(['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'])

  // Step 2 state
  const [coursesText, setCoursesText] = useState(DEMO_PASTE)

  // Step 3 state
  const [electives, setElectives] = useState<ElectiveBlockDraft[]>([
    {
      id: 'ELEC_DMS_OT_AGT',
      name: 'DMS/OT/AGT',
      weekly_slot_count: 4,
      locked_slots_text: 'MON-2, TUE-3, THU-3, FRI-3',
      options: [
        {
          course_code: 'BCS405A',
          course_name: 'Discrete Mathematical Structures',
          faculty: 'Dr Sreelakshmi T K, Dr Sumati Tareja, Dr Nikki Kedia, Dr Anitha Kiran',
        },
        {
          course_code: 'BCS405C',
          course_name: 'Optimization Techniques',
          faculty: 'Prof Sanjay M B, Prof Pragathi M',
        },
        {
          course_code: 'BAI405D',
          course_name: 'Algorithmic Game Theory',
          faculty: 'Prof Syed Owins Umair',
        },
      ],
    },
  ])
  const [includeSatLocks, setIncludeSatLocks] = useState(true)

  const sectionIds = useMemo(
    () => Array.from({ length: nSections }, (_, i) => String.fromCharCode(65 + i)),
    [nSections],
  )

  function handleCoursesTextChange(nextText: string) {
    setCoursesText(nextText)
    setPreview(null)
    setError(null)
    setPreflightErrors([])
  }

  function buildPayload() {
    const elective_blocks = electives.map((b) => ({
      id: b.id,
      name: b.name,
      weekly_slot_count: b.weekly_slot_count,
      applies_to_sections: sectionIds,
      locked_global_slots: b.locked_slots_text
        .split(/[,;\n]/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map((tok) => {
          const m = tok.match(/^([A-Za-z]+)\s*[-:\s]\s*(\d+)$/)
          if (!m) return null
          return [m[1].toUpperCase().slice(0, 3), parseInt(m[2], 10)]
        })
        .filter(Boolean),
      options: b.options.map((o) => ({
        course_code: o.course_code.trim(),
        course_name: o.course_name.trim(),
        faculty: o.faculty
          .split(/[,;]/)
          .map((x) => x.trim())
          .filter(Boolean),
      })),
    }))
    const sat_locks = includeSatLocks
      ? [
          { label: 'IIC-Activity', slots: [1, 2] },
          { label: 'BENGDIP2', slots: [3, 4] },
        ]
      : []
    return {
      skeleton: {
        days,
        slots_per_day: slotsPerDay,
        slot_timings: DEFAULT_TIMINGS.slice(0, slotsPerDay),
        tea_after_slot: teaAfter,
        tea_minutes: 20,
        lunch_after_slot: lunchAfter,
        lunch_minutes: 55,
        section_ids: sectionIds,
        batches_per_section: 2,
        classroom_by_section: {},
        inactive_sat_weeks: [1, 3],
        sat_locks,
        semester,
      },
      courses_text: coursesText,
      elective_blocks,
      // Keep wizard solves within the same budget as the reference flow.
      time_limit_sec: 20,
    }
  }

  async function refreshPreview() {
    setBusy(true)
    setError(null)
    setPreflightErrors([])
    try {
      const r = await fetch(API + '/draft/preview', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      })
      const j = await r.json()
      if (!j.ok) {
        setError(j.error || 'Parse failed')
        setPreview(null)
        return
      }
      setPreview(j.summary)
      setPreflightErrors(j.preflight?.errors || [])
    } catch (e: any) {
      setError(e.message)
      setPreview(null)
    } finally {
      setBusy(false)
    }
  }

  async function generate() {
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(API + '/draft/build', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      })
      if (!r.ok) {
        const txt = await r.text()
        throw new Error(`${r.status} ${txt.slice(0, 200)}`)
      }
      const resp: GenerateResponse = await r.json()
      // fetch the parsed request too so the app has the canonical TimetableRequest
      const previewResp = await fetch(API + '/draft/preview', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      })
      const previewJson = await previewResp.json()
      onGenerated(resp, previewJson.request as TimetableRequest)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-slate-900/50 grid place-items-center z-50 p-6">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-gradient-to-r from-indigo-500 to-indigo-600 text-white">
          <div>
            <div className="font-bold text-lg">New timetable</div>
            <div className="text-xs opacity-80">Step {step} of 3</div>
          </div>
          <button
            onClick={onCancel}
            className="text-white/80 hover:text-white text-sm bg-white/10 hover:bg-white/20 px-3 py-1 rounded-md"
          >
            Cancel
          </button>
        </div>

        {/* Stepper */}
        <div className="px-6 py-2 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center gap-2 text-xs">
            {(['Skeleton', 'Courses & Faculty', 'Electives & Activities'] as const).map(
              (label, i) => {
                const s = (i + 1) as 1 | 2 | 3
                const active = s === step
                const done = s < step
                return (
                  <button
                    key={s}
                    onClick={() => setStep(s)}
                    className={[
                      'px-3 py-1.5 rounded-md font-medium',
                      active
                        ? 'bg-indigo-500 text-white'
                        : done
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-white border border-slate-200 text-slate-500',
                    ].join(' ')}
                  >
                    {s}. {label}
                  </button>
                )
              },
            )}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto px-6 py-5 text-sm">
          {step === 1 && (
            <div className="space-y-4 max-w-xl">
              <h3 className="font-semibold text-slate-800">Time structure & sections</h3>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Semester">
                  <input
                    type="number"
                    value={semester}
                    onChange={(e) => setSemester(parseInt(e.target.value || '1', 10))}
                    className="w-full border border-slate-200 rounded-md px-2 py-1.5"
                  />
                </Field>
                <Field label="Number of sections">
                  <input
                    type="number"
                    value={nSections}
                    min={1}
                    max={20}
                    onChange={(e) => setNSections(parseInt(e.target.value || '1', 10))}
                    className="w-full border border-slate-200 rounded-md px-2 py-1.5"
                  />
                  <div className="text-[11px] text-slate-500 mt-1">
                    Section IDs: {sectionIds.join(', ')}
                  </div>
                </Field>
                <Field label="Slots per day">
                  <input
                    type="number"
                    value={slotsPerDay}
                    min={3}
                    max={10}
                    onChange={(e) => setSlotsPerDay(parseInt(e.target.value || '7', 10))}
                    className="w-full border border-slate-200 rounded-md px-2 py-1.5"
                  />
                </Field>
                <Field label="Active days">
                  <div className="flex gap-1 flex-wrap">
                    {['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'].map((d) => {
                      const on = days.includes(d)
                      return (
                        <button
                          key={d}
                          onClick={() =>
                            setDays((cur) =>
                              cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d],
                            )
                          }
                          className={[
                            'px-2 py-1 rounded-md text-xs border',
                            on
                              ? 'bg-indigo-500 text-white border-indigo-500'
                              : 'bg-white text-slate-600 border-slate-200',
                          ].join(' ')}
                        >
                          {d}
                        </button>
                      )
                    })}
                  </div>
                </Field>
                <Field label="Tea break after slot">
                  <input
                    type="number"
                    value={teaAfter}
                    min={1}
                    max={slotsPerDay - 1}
                    onChange={(e) => setTeaAfter(parseInt(e.target.value || '2', 10))}
                    className="w-full border border-slate-200 rounded-md px-2 py-1.5"
                  />
                </Field>
                <Field label="Lunch break after slot">
                  <input
                    type="number"
                    value={lunchAfter}
                    min={1}
                    max={slotsPerDay - 1}
                    onChange={(e) => setLunchAfter(parseInt(e.target.value || '4', 10))}
                    className="w-full border border-slate-200 rounded-md px-2 py-1.5"
                  />
                </Field>
              </div>
              <div className="text-xs text-slate-500">
                Slot timings default to BMSIT pattern (8:30 start, ends 16:10). You can fine-tune
                later from the chat (e.g.{' '}
                <span className="font-mono bg-slate-100 px-1 rounded">set slot 1 to 9:00</span>).
              </div>
            </div>
          )}

          {step === 2 && (
            <>
              <CoursesFacultyPanel
                rawText={coursesText}
                onChange={handleCoursesTextChange}
                sectionIds={sectionIds}
                onPreview={refreshPreview}
                preview={preview}
                error={error}
                preflightErrors={preflightErrors}
                busy={busy}
              />
              {false && (
                <div className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-800">Courses & faculty</h3>
                  <p className="text-xs text-slate-500 mt-1">
                    Paste one row per course. Format:{' '}
                    <span className="font-mono bg-slate-100 px-1 rounded">
                      CODE, NAME, CREDITS, TYPE, FACULTY1; FACULTY2; …
                    </span>{' '}
                    · Types:{' '}
                    <span className="font-mono">theory · lab · lab pair=CODE · activity</span> ·
                    Faculty: one per section in order, or{' '}
                    <span className="font-mono">auto · xN · same-as=CODE</span>.
                  </p>
                </div>
                <button
                  onClick={refreshPreview}
                  className="text-xs bg-slate-900 text-white px-2.5 py-1.5 rounded-md hover:bg-slate-800 whitespace-nowrap"
                >
                  Preview
                </button>
              </div>
              <textarea
                value={coursesText}
                onChange={(e) => setCoursesText(e.target.value)}
                rows={20}
                spellCheck={false}
                className="w-full border border-slate-200 rounded-md px-3 py-2 font-mono text-[11px] leading-relaxed"
              />
              {preview && (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 text-emerald-900 text-xs p-2">
                  Parsed: <b>{preview.courses}</b> courses · <b>{preview.faculty}</b> faculty ·{' '}
                  <b>{preview.sections}</b> sections · <b>{preview.elective_blocks}</b> elective
                  block(s).
                </div>
              )}
              {error && (
                <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-900 text-xs p-2">
                  {error}
                </div>
              )}
              {preflightErrors.length > 0 && (
                <div className="rounded-md border border-amber-200 bg-amber-50 text-amber-900 text-xs p-2">
                  <div className="font-semibold">Preflight issues:</div>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {preflightErrors.slice(0, 5).map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}
                </div>
              )}
            </>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <h3 className="font-semibold text-slate-800">Electives & Saturday locks</h3>
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={includeSatLocks}
                  onChange={(e) => setIncludeSatLocks(e.target.checked)}
                />
                Lock Saturday slots 1-2 to IIC-Activity and 3-4 to BENGDIP2 (English)
              </label>

              <div className="space-y-3">
                <div className="text-sm font-medium text-slate-700">Elective blocks</div>
                {electives.map((b, bi) => (
                  <div key={bi} className="rounded-md border border-slate-200 p-3 space-y-2">
                    <div className="grid grid-cols-3 gap-2 text-xs">
                      <Field label="Name">
                        <input
                          value={b.name}
                          onChange={(e) =>
                            setElectives((cur) =>
                              cur.map((x, i) => (i === bi ? { ...x, name: e.target.value } : x)),
                            )
                          }
                          className="w-full border border-slate-200 rounded-md px-2 py-1"
                        />
                      </Field>
                      <Field label="Weekly slots">
                        <input
                          type="number"
                          value={b.weekly_slot_count}
                          onChange={(e) =>
                            setElectives((cur) =>
                              cur.map((x, i) =>
                                i === bi
                                  ? { ...x, weekly_slot_count: parseInt(e.target.value || '1', 10) }
                                  : x,
                              ),
                            )
                          }
                          className="w-full border border-slate-200 rounded-md px-2 py-1"
                        />
                      </Field>
                      <Field label="Locked slots (DAY-SLOT, …)">
                        <input
                          value={b.locked_slots_text}
                          onChange={(e) =>
                            setElectives((cur) =>
                              cur.map((x, i) =>
                                i === bi ? { ...x, locked_slots_text: e.target.value } : x,
                              ),
                            )
                          }
                          className="w-full border border-slate-200 rounded-md px-2 py-1"
                        />
                      </Field>
                    </div>
                    <div className="text-xs text-slate-500">Options:</div>
                    <div className="space-y-1">
                      {b.options.map((o, oi) => (
                        <div key={oi} className="grid grid-cols-12 gap-2 text-xs">
                          <input
                            placeholder="Course code"
                            value={o.course_code}
                            onChange={(e) =>
                              setElectives((cur) =>
                                cur.map((x, i) =>
                                  i === bi
                                    ? {
                                        ...x,
                                        options: x.options.map((y, j) =>
                                          j === oi ? { ...y, course_code: e.target.value } : y,
                                        ),
                                      }
                                    : x,
                                ),
                              )
                            }
                            className="col-span-2 border border-slate-200 rounded-md px-2 py-1"
                          />
                          <input
                            placeholder="Course name"
                            value={o.course_name}
                            onChange={(e) =>
                              setElectives((cur) =>
                                cur.map((x, i) =>
                                  i === bi
                                    ? {
                                        ...x,
                                        options: x.options.map((y, j) =>
                                          j === oi ? { ...y, course_name: e.target.value } : y,
                                        ),
                                      }
                                    : x,
                                ),
                              )
                            }
                            className="col-span-4 border border-slate-200 rounded-md px-2 py-1"
                          />
                          <input
                            placeholder="Faculty pool (comma-separated)"
                            value={o.faculty}
                            onChange={(e) =>
                              setElectives((cur) =>
                                cur.map((x, i) =>
                                  i === bi
                                    ? {
                                        ...x,
                                        options: x.options.map((y, j) =>
                                          j === oi ? { ...y, faculty: e.target.value } : y,
                                        ),
                                      }
                                    : x,
                                ),
                              )
                            }
                            className="col-span-6 border border-slate-200 rounded-md px-2 py-1"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="text-[11px] text-slate-500">
                Faculty in elective pools work across sections; the solver auto-balances them.
                Dept-Activity stays locked from the course paste (FRI 5-7 by default).
              </div>
              {error && (
                <div className="rounded-md border border-rose-200 bg-rose-50 text-rose-900 text-xs p-2">
                  {error}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between">
          <button
            onClick={() => (step > 1 ? setStep(((step - 1) as 1 | 2 | 3)) : onCancel())}
            className="px-3 py-1.5 text-sm border border-slate-200 bg-white rounded-md hover:bg-slate-100"
          >
            {step > 1 ? 'Back' : 'Cancel'}
          </button>
          <div className="text-xs text-slate-500">
            {busy ? 'Working…' : 'Click Generate at step 3 to solve.'}
          </div>
          {step < 3 ? (
            <button
              onClick={() => setStep(((step + 1) as 1 | 2 | 3))}
              className="px-4 py-1.5 text-sm bg-indigo-500 hover:bg-indigo-600 text-white rounded-md"
            >
              Next
            </button>
          ) : (
            <button
              onClick={generate}
              disabled={busy}
              className="px-4 py-1.5 text-sm bg-indigo-500 hover:bg-indigo-600 disabled:bg-indigo-300 text-white rounded-md"
            >
              {busy ? 'Solving…' : 'Generate'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-wider text-slate-500 font-medium mb-1">
        {label}
      </div>
      {children}
    </label>
  )
}
