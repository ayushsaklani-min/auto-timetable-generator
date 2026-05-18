import { useEffect, useMemo, useState } from 'react'
import { api, Faculty, GenerateResponse, ScheduledClass, TimetableRequest, Violation } from './lib/api'
import TimetableGrid from './components/TimetableGrid'
import ChatPanel from './components/ChatPanel'
import SetupWizard from './components/SetupWizard'
import LandingPage from './components/LandingPage'

function buildStatusMessage(resp: GenerateResponse) {
  if (!resp.timetable) return `Preflight failed: ${resp.preflight.errors.length} errors`
  const tt = resp.timetable
  const base = `${tt.status} · ${tt.classes.length} placements · ${tt.solve_time_sec.toFixed(2)}s · soft ${
    resp.verification?.soft_score ?? 0
  }/100`
  const note = tt.notes?.[0]?.trim()
  if (!note) return base
  return `${base} · ${note}`
}

function baseFacultyName(name: string) {
  return name.replace(/\s*\([^)]*\)\s*$/, '').trim() || name
}

function inferClassesForFaculty(
  req: TimetableRequest,
  classes: ScheduledClass[],
  facultyIds: string[],
): ScheduledClass[] {
  const idSet = new Set(facultyIds)
  const byId = new Map<string, Faculty>(req.faculty.map((f) => [f.id, f]))
  const selected = facultyIds.map((id) => byId.get(id)).filter((f): f is Faculty => !!f)
  const out: ScheduledClass[] = []
  const seen = new Set<string>()

  const pushUnique = (c: ScheduledClass) => {
    const key = `${c.section_id}|${c.day}|${c.slot}|${c.course_code}|${c.label ?? ''}|${c.batch_id ?? ''}`
    if (seen.has(key)) return
    seen.add(key)
    out.push(c)
  }

  for (const c of classes) {
    if (c.faculty_id && idSet.has(c.faculty_id)) pushUnique(c)
  }

  for (const fac of selected) {
    for (const a of fac.assignments ?? []) {
      for (const c of classes) {
        if (c.course_code === a.course_code && c.section_id === a.section_id) pushUnique(c)
      }
    }
  }

  for (const block of req.elective_blocks ?? []) {
    if (!block?.id || !Array.isArray(block.options)) continue
    for (const opt of block.options) {
      const pool = Array.isArray(opt?.faculty_pool) ? (opt.faculty_pool as string[]) : []
      if (!pool.some((id) => idSet.has(id))) continue
      for (const c of classes) {
        if (c.course_code !== block.id) continue
        if (Array.isArray(block.applies_to_sections) && !block.applies_to_sections.includes(c.section_id))
          continue
        pushUnique({
          ...c,
          course_code: opt.course_code || c.course_code,
          label: opt.course_name || c.label || c.course_code,
        })
      }
    }
  }

  const lowerNames = selected.map((f) => f.name.toLowerCase())
  const wantsIIC = lowerNames.some((n) => n.includes('iic'))
  const wantsBeng = lowerNames.some((n) => n.includes('bengdip2'))
  if (wantsIIC || wantsBeng) {
    for (const c of classes) {
      const code = (c.course_code || '').toLowerCase()
      const label = (c.label || '').toLowerCase()
      if ((wantsIIC && (code.includes('iic') || label.includes('iic'))) || (wantsBeng && (code.includes('bengdip2') || label.includes('bengdip2')))) {
        pushUnique(c)
      }
    }
  }

  return out
}

export default function App() {
  const [req, setReq] = useState<TimetableRequest | null>(null)
  const [resp, setResp] = useState<GenerateResponse | null>(null)
  const [sectionId, setSectionId] = useState<string>('A')
  const [busy, setBusy] = useState(false)
  const [statusMsg, setStatusMsg] = useState<string>('')
  const [highlightCourse, setHighlightCourse] = useState<string | null>(null)
  const [view, setView] = useState<'section' | 'faculty'>('section')
  const [facultyKey, setFacultyKey] = useState<string>('')
  const [facultyCourse, setFacultyCourse] = useState<string>('ALL')
  const [wizardOpen, setWizardOpen] = useState(false)
  const [landing, setLanding] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true
    return window.sessionStorage.getItem('skipLanding') !== '1'
  })

  useEffect(() => {
    api
      .bmsitReference()
      .then((r) => {
        setReq(r)
        setSectionId(r.sections[0]?.id ?? 'A')
      })
      .catch((e) => setStatusMsg(`Load failed: ${e.message}`))
  }, [])

  async function runGenerate(over?: TimetableRequest) {
    const r = over ?? req
    if (!r) return
    setBusy(true)
    setStatusMsg('Solving…')
    try {
      const out = await api.generate(r)
      setResp(out)
      setStatusMsg(buildStatusMessage(out))
    } catch (e: any) {
      setStatusMsg(`Error: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const courseNameByCode = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of req?.courses ?? []) m.set(c.code, c.name)
    return m
  }, [req])

  const facultyGroups = useMemo(() => {
    if (!req) return []
    const grouped = new Map<string, { key: string; name: string; ids: string[] }>()
    for (const f of req.faculty) {
      const key = baseFacultyName(f.name)
      const existing = grouped.get(key)
      if (existing) existing.ids.push(f.id)
      else grouped.set(key, { key, name: key, ids: [f.id] })
    }
    const all = [...grouped.values()].sort((a, b) => a.name.localeCompare(b.name))
    if (!resp?.timetable) return all
    return all.filter((g) => inferClassesForFaculty(req, resp.timetable!.classes, g.ids).length > 0)
  }, [req, resp])

  useEffect(() => {
    if (facultyGroups.length === 0) {
      if (facultyKey) setFacultyKey('')
      return
    }
    if (!facultyGroups.some((f) => f.key === facultyKey)) setFacultyKey(facultyGroups[0].key)
  }, [facultyGroups, facultyKey])

  const selectedFaculty = useMemo(
    () => facultyGroups.find((f) => f.key === facultyKey) ?? null,
    [facultyGroups, facultyKey],
  )

  const facultyRawClasses = useMemo(() => {
    if (!req || !resp?.timetable || !selectedFaculty) return []
    return inferClassesForFaculty(req, resp.timetable.classes, selectedFaculty.ids)
  }, [req, resp, selectedFaculty])

  const facultyCourseOptions = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of facultyRawClasses) {
      m.set(c.course_code, c.label || courseNameByCode.get(c.course_code) || c.course_code)
    }
    return [...m.entries()]
      .map(([code, name]) => ({ code, name }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [facultyRawClasses, courseNameByCode])

  useEffect(() => {
    if (facultyCourse === 'ALL') return
    if (!facultyCourseOptions.some((c) => c.code === facultyCourse)) setFacultyCourse('ALL')
  }, [facultyCourse, facultyCourseOptions])

  const facultyClasses = useMemo(() => {
    const filtered =
      facultyCourse === 'ALL'
        ? facultyRawClasses
        : facultyRawClasses.filter((c) => c.course_code === facultyCourse)
    return filtered.map((c) => ({
      ...c,
      section_id: '_FAC',
      label: c.label || courseNameByCode.get(c.course_code) || c.course_code,
      faculty_id: c.section_id,
    }))
  }, [facultyRawClasses, facultyCourse, courseNameByCode])

  const status = resp?.timetable?.status
  const statusColor =
    status === 'OPTIMAL'
      ? 'bg-emerald-500'
      : status === 'FEASIBLE'
        ? 'bg-sky-500'
        : status === 'INFEASIBLE'
          ? 'bg-rose-500'
          : 'bg-slate-400'

  if (landing) {
    return (
      <LandingPage
        onEnter={() => {
          window.sessionStorage.setItem('skipLanding', '1')
          setLanding(false)
        }}
      />
    )
  }

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-slate-50 to-slate-100 text-slate-900">
      {/* Header */}
      <header className="px-5 py-3 bg-slate-900 text-white flex items-center justify-between shadow-md">
        <div
          className="flex items-center gap-3 cursor-pointer"
          onClick={() => {
            window.sessionStorage.removeItem('skipLanding')
            setLanding(true)
          }}
          title="Back to home"
        >
          <img
            src="/bmsitm-logo.png"
            alt="BMSITM"
            className="h-9 w-9 rounded-md bg-white p-0.5 object-contain"
          />
          <div>
            <div className="font-bold tracking-tight text-base">Timetable Generator</div>
            <div className="text-[11px] text-slate-300">
              BMSITM · Department of AI &amp; Machine Learning
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <button
            onClick={() => setWizardOpen(true)}
            className="bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded-md font-medium border border-white/20"
          >
            New from inputs
          </button>
          {status && (
            <span
              className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full ${statusColor} text-white font-medium`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-white" />
              {status}
            </span>
          )}
          {resp?.verification && (
            <span
              className={`px-2 py-1 rounded-full font-medium ${
                resp.verification.ok ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
              }`}
            >
              Verifier: {resp.verification.ok ? 'clean' : `${resp.verification.violations.length} issues`}
            </span>
          )}
          {resp?.verification && (
            <span className="px-2 py-1 rounded-full bg-slate-800 text-slate-200 font-medium">
              Soft {resp.verification.soft_score}/100
            </span>
          )}
          <button
            onClick={() => runGenerate()}
            disabled={!req || busy}
            className="bg-indigo-500 hover:bg-indigo-400 disabled:bg-indigo-900 disabled:cursor-not-allowed px-4 py-1.5 rounded-md font-medium shadow"
          >
            {busy ? 'Solving…' : 'Generate'}
          </button>
        </div>
      </header>

      {/* Status banner */}
      <div className="px-5 py-1.5 text-xs bg-white border-b border-slate-200 flex items-center justify-between">
        <div className="text-slate-600">{statusMsg || 'Loaded BMSIT AIML 4th sem reference. Click Generate to solve.'}</div>
        {resp?.preflight && !resp.preflight.ok && (
          <div className="text-red-700 font-medium">
            Preflight: {resp.preflight.errors[0]}
            {resp.preflight.errors.length > 1 ? ` (+${resp.preflight.errors.length - 1} more)` : ''}
          </div>
        )}
      </div>

      {wizardOpen && (
        <SetupWizard
          onCancel={() => setWizardOpen(false)}
          onGenerated={(newResp, newReq) => {
            setReq(newReq)
            setResp(newResp)
            setSectionId(newReq.sections[0]?.id ?? 'A')
            setStatusMsg(buildStatusMessage(newResp))
            setWizardOpen(false)
          }}
        />
      )}

      <main className="flex-1 grid grid-cols-12 gap-3 p-3 min-h-0">
        {/* Chat panel */}
        <section className="col-span-3 bg-white border border-slate-200 rounded-lg shadow-sm flex flex-col min-h-0 overflow-hidden">
          <ChatPanel
            prior={req}
            onApplied={(newResp, newReq) => {
              setReq(newReq)
              setResp(newResp)
              setStatusMsg(buildStatusMessage(newResp))
            }}
            onExplain={async () => {
              if (!resp?.job_id) return 'No timetable yet — click Generate first.'
              try {
                const x = await api.llmExplain(resp.job_id)
                return x.explanation
              } catch (e: any) {
                return `LLM unavailable: ${e.message}`
              }
            }}
          />
        </section>

        {/* Timetable view */}
        <section className="col-span-9 bg-white border border-slate-200 rounded-lg shadow-sm flex flex-col min-h-0 overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-200 flex items-center gap-2 text-sm bg-slate-50">
            <div className="flex bg-white border border-slate-200 rounded-md p-0.5 shadow-sm">
              <button
                className={[
                  'px-3 py-1 rounded-md text-xs font-medium transition',
                  view === 'section' ? 'bg-indigo-500 text-white shadow' : 'text-slate-600 hover:bg-slate-100',
                ].join(' ')}
                onClick={() => setView('section')}
              >
                Section
              </button>
              <button
                className={[
                  'px-3 py-1 rounded-md text-xs font-medium transition',
                  view === 'faculty' ? 'bg-indigo-500 text-white shadow' : 'text-slate-600 hover:bg-slate-100',
                ].join(' ')}
                onClick={() => setView('faculty')}
              >
                Faculty
              </button>
            </div>
            {view === 'section' && req && (
              <select
                value={sectionId}
                onChange={(e) => setSectionId(e.target.value)}
                className="border border-slate-200 rounded-md px-2 py-1 bg-white text-xs"
              >
                {req.sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} — {s.classroom}
                  </option>
                ))}
              </select>
            )}
            {view === 'faculty' && req && (
              <>
                <select
                  value={facultyKey}
                  onChange={(e) => {
                    setFacultyKey(e.target.value)
                    setFacultyCourse('ALL')
                  }}
                  className="border border-slate-200 rounded-md px-2 py-1 bg-white text-xs"
                >
                  {facultyGroups.map((f) => (
                    <option key={f.key} value={f.key}>
                      {f.name}
                    </option>
                  ))}
                </select>
                <select
                  value={facultyCourse}
                  onChange={(e) => setFacultyCourse(e.target.value)}
                  className="border border-slate-200 rounded-md px-2 py-1 bg-white text-xs"
                  disabled={facultyCourseOptions.length === 0}
                >
                  <option value="ALL">All courses</option>
                  {facultyCourseOptions.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </>
            )}
            <input
              type="text"
              placeholder="Highlight course code or name…"
              value={highlightCourse ?? ''}
              onChange={(e) => setHighlightCourse(e.target.value || null)}
              className="border border-slate-200 rounded-md px-2 py-1 ml-1 text-xs flex-1 max-w-xs bg-white"
            />
            <div className="flex-1" />
            {resp?.job_id && resp?.timetable && (
              <div className="flex gap-1">
                <a
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300"
                  href={api.exportUrl(resp.job_id, 'pdf')}
                  target="_blank"
                  rel="noreferrer"
                >
                  PDF
                </a>
                <a
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300"
                  href={api.exportUrl(resp.job_id, 'xlsx')}
                  target="_blank"
                  rel="noreferrer"
                >
                  Excel
                </a>
                <a
                  className="px-2.5 py-1 text-xs rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300"
                  href={api.exportUrl(resp.job_id, 'json')}
                  target="_blank"
                  rel="noreferrer"
                >
                  JSON
                </a>
              </div>
            )}
          </div>

          {/* Title bar */}
          {view === 'section' && req && (
            <div className="px-4 py-2 border-b border-slate-200 bg-white">
              <div className="font-semibold text-slate-800">
                {req.sections.find((s) => s.id === sectionId)?.name} —{' '}
                <span className="text-slate-500 font-normal">
                  {req.sections.find((s) => s.id === sectionId)?.classroom}
                </span>
              </div>
              <div className="text-[11px] text-slate-500">
                Active days: {req.time_config.days.join(' · ')} · {req.time_config.slots_per_day} slots/day
              </div>
            </div>
          )}
          {view === 'faculty' && req && (
            <div className="px-4 py-2 border-b border-slate-200 bg-white">
              <div className="font-semibold text-slate-800">
                {selectedFaculty?.name || 'Faculty view'}
                {facultyCourse !== 'ALL' && (
                  <span className="text-slate-500 font-normal">
                    {' '}
                    · {facultyCourseOptions.find((c) => c.code === facultyCourse)?.name ?? facultyCourse}
                  </span>
                )}
              </div>
              <div className="text-[11px] text-slate-500">
                Slots shown: {facultyClasses.length} · Cells display section-wise teaching
              </div>
            </div>
          )}

          <div className="flex-1 overflow-auto p-4">
            {req && resp?.timetable ? (
              view === 'section' ? (
                <TimetableGrid
                  req={req}
                  classes={resp.timetable.classes}
                  sectionId={sectionId}
                  highlightCourse={highlightCourse}
                />
              ) : (
                <TimetableGrid
                  req={req}
                  classes={facultyClasses}
                  sectionId="_FAC"
                  highlightCourse={highlightCourse}
                />
              )
            ) : (
              <Empty req={req} />
            )}
            {resp?.verification?.violations && resp.verification.violations.length > 0 && (
              <ViolationsPanel violations={resp.verification.violations} />
            )}
            {resp?.preflight && !resp.preflight.ok && (
              <PreflightPanel errors={resp.preflight.errors} warnings={resp.preflight.warnings} />
            )}
            {resp?.timetable?.notes && resp.timetable.notes.length > 0 && (
              <SolverNotesPanel notes={resp.timetable.notes} />
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

function Empty({ req }: { req: TimetableRequest | null }) {
  if (!req) return <div className="text-slate-400 text-sm">Loading reference data…</div>
  return (
    <div className="grid place-items-center h-full">
      <div className="max-w-md text-center">
        <div className="h-14 w-14 mx-auto rounded-xl bg-indigo-500 text-white grid place-items-center text-2xl shadow-lg mb-3">
          ⏱
        </div>
        <h2 className="text-lg font-semibold text-slate-800">Ready to solve</h2>
        <p className="text-sm text-slate-500 mt-1">
          Loaded BMSIT AIML 4th sem reference: {req.sections.length} sections,{' '}
          {req.courses.length} courses, {req.faculty.length} faculty,{' '}
          {req.elective_blocks.length} elective block.
        </p>
        <p className="text-sm text-slate-500 mt-2">
          Click <span className="font-semibold text-indigo-600">Generate</span> to produce a
          conflict-free timetable, or describe a change in the chat.
        </p>
      </div>
    </div>
  )
}

function ViolationsPanel({ violations }: { violations: Violation[] }) {
  return (
    <div className="mt-4 border border-red-200 bg-red-50 rounded-lg p-3 text-xs">
      <div className="font-semibold text-red-800 mb-1">
        {violations.length} verifier violation(s)
      </div>
      <ul className="list-disc pl-4 space-y-0.5 max-h-48 overflow-auto">
        {violations.slice(0, 30).map((v, i) => (
          <li key={i}>
            <span className="font-mono text-red-700">{v.code}</span> · {v.message}
          </li>
        ))}
      </ul>
    </div>
  )
}

function PreflightPanel({ errors, warnings }: { errors: string[]; warnings: string[] }) {
  return (
    <div className="mt-4 border border-amber-200 bg-amber-50 rounded-lg p-3 text-xs">
      <div className="font-semibold text-amber-800 mb-1">Pre-flight issues</div>
      {errors.length > 0 && (
        <>
          <div className="text-red-700 font-semibold mt-1">Errors</div>
          <ul className="list-disc pl-4 space-y-0.5">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </>
      )}
      {warnings.length > 0 && (
        <>
          <div className="text-amber-700 font-semibold mt-1">Warnings</div>
          <ul className="list-disc pl-4 space-y-0.5">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function SolverNotesPanel({ notes }: { notes: string[] }) {
  return (
    <div className="mt-4 border border-indigo-200 bg-indigo-50 rounded-lg p-3 text-xs">
      <div className="font-semibold text-indigo-800 mb-1">Solver notes</div>
      <ul className="list-disc pl-4 space-y-0.5">
        {notes.map((n, i) => (
          <li key={i}>{n}</li>
        ))}
      </ul>
    </div>
  )
}
