import { useMemo, useRef, useState } from 'react'
import {
  type CourseDraft,
  type CourseKind,
  type FacultyInputMode,
  buildFacultySpec,
  parseCoursesText,
  serializeCoursesText,
} from '../lib/coursesText'

interface PreviewSummary {
  sections: number
  courses: number
  faculty: number
  elective_blocks: number
}

interface ImportDocumentInfo {
  filename: string
  format: string
  course_rows: number
  faculty_rows: number
  warnings: string[]
}

interface ImportResponse {
  raw_text: string
  summary: {
    documents: number
    courses: number
    imported_courses: number
    faculty_mappings: number
  }
  documents_info: ImportDocumentInfo[]
  warnings: string[]
}

interface Props {
  rawText: string
  onChange: (rawText: string) => void
  sectionIds: string[]
  onPreview: () => void
  preview: PreviewSummary | null
  error: string | null
  preflightErrors: string[]
  busy?: boolean
}

type EditorMode = 'guided' | 'raw'

function createStarterCourse(kind: CourseKind, index: number): CourseDraft {
  if (kind === 'lab') {
    return {
      code: `LAB_${index}`,
      name: 'New Lab',
      credits: 1,
      kind,
      pairCourse: '',
      lockedDay: '',
      lockedSlotsText: '',
      combined: false,
      extraTypeText: '',
      facultyMode: 'auto',
      facultyNames: [],
      facultyCount: 1,
      sameAsCode: '',
    }
  }

  if (kind === 'activity') {
    return {
      code: `ACT_${index}`,
      name: 'New Activity',
      credits: 0,
      kind,
      pairCourse: '',
      lockedDay: '',
      lockedSlotsText: '',
      combined: false,
      extraTypeText: '',
      facultyMode: 'auto',
      facultyNames: [],
      facultyCount: 1,
      sameAsCode: '',
    }
  }

  return {
    code: `COURSE_${index}`,
    name: 'New Course',
    credits: 3,
    kind,
    pairCourse: '',
    lockedDay: '',
    lockedSlotsText: '',
    combined: false,
    extraTypeText: '',
    facultyMode: 'auto',
    facultyNames: [],
    facultyCount: 1,
    sameAsCode: '',
  }
}

export default function CoursesFacultyPanel({
  rawText,
  onChange,
  sectionIds,
  onPreview,
  preview,
  error,
  preflightErrors,
  busy = false,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [mode, setMode] = useState<EditorMode>('guided')
  const [importBusy, setImportBusy] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<ImportResponse | null>(null)

  const parsed = useMemo(() => {
    try {
      return {
        rows: parseCoursesText(rawText),
        error: null as string | null,
      }
    } catch (err) {
      return {
        rows: [] as CourseDraft[],
        error: err instanceof Error ? err.message : 'Unable to parse the course text.',
      }
    }
  }, [rawText])

  const stats = useMemo(() => {
    return parsed.rows.reduce(
      (acc, row) => {
        acc.total += 1
        acc[row.kind] += 1
        return acc
      },
      { total: 0, theory: 0, lab: 0, activity: 0 },
    )
  }, [parsed.rows])

  const courseCodes = useMemo(
    () => parsed.rows.map((row) => row.code.trim()).filter(Boolean),
    [parsed.rows],
  )

  function commitRows(nextRows: CourseDraft[]) {
    onChange(serializeCoursesText(nextRows))
  }

  function updateRow(index: number, nextRow: CourseDraft) {
    commitRows(parsed.rows.map((row, rowIndex) => (rowIndex === index ? nextRow : row)))
  }

  function duplicateRow(index: number) {
    const source = parsed.rows[index]
    if (!source) return
    const nextRow = {
      ...source,
      code: source.code.trim() ? `${source.code.trim()}_COPY` : `COURSE_${parsed.rows.length + 1}`,
      facultyNames: [...source.facultyNames],
    }
    const nextRows = [...parsed.rows]
    nextRows.splice(index + 1, 0, nextRow)
    commitRows(nextRows)
  }

  function removeRow(index: number) {
    commitRows(parsed.rows.filter((_, rowIndex) => rowIndex !== index))
  }

  function addRow(kind: CourseKind) {
    commitRows([...parsed.rows, createStarterCourse(kind, parsed.rows.length + 1)])
  }

  async function handleFileSelection(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (files.length === 0) return

    setImportBusy(true)
    setImportError(null)

    try {
      const body = new FormData()
      for (const file of files) body.append('files', file)
      body.append('section_ids', sectionIds.join(','))
      body.append('existing_text', rawText)
      body.append('replace_existing', 'true')

      const response = await fetch('/api/draft/import-documents', {
        method: 'POST',
        body,
      })

      const payload = await response.json().catch(async () => {
        throw new Error(await response.text())
      })

      if (!response.ok || !payload?.ok) {
        throw new Error(payload?.detail || payload?.error || 'Document import failed.')
      }

      const result = payload as ImportResponse & { ok: true }
      onChange(result.raw_text)
      setImportResult(result)
      setMode('raw')
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Document import failed.')
    } finally {
      setImportBusy(false)
    }
  }

  const rawLineCount = rawText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean).length

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 className="font-semibold text-slate-800">Courses & faculty</h3>
              <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
                Guided mode builds the same serialized solver text as raw mode. Use guided mode for
                section-wise faculty entry and course metadata, or switch to raw mode for direct
                paste and comment editing.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1">
                <ModeButton active={mode === 'guided'} onClick={() => setMode('guided')}>
                  Guided
                </ModeButton>
                <ModeButton active={mode === 'raw'} onClick={() => setMode('raw')}>
                  Raw text
                </ModeButton>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.xlsx,.xlsm,.csv,.png,.jpg,.jpeg,.tif,.tiff,.gif,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv,image/png,image/jpeg,image/tiff,image/gif"
                onChange={handleFileSelection}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={busy || importBusy}
                className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
              >
                {importBusy ? 'Importing...' : 'Import file'}
              </button>
              <button
                type="button"
                onClick={onPreview}
                disabled={busy || importBusy}
                className="rounded-md bg-slate-900 px-3 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {busy ? 'Previewing...' : 'Preview'}
              </button>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
            <StatPill label={`${stats.total} rows`} tone="slate" />
            <StatPill label={`${stats.theory} theory`} tone="indigo" />
            <StatPill label={`${stats.lab} labs`} tone="sky" />
            <StatPill label={`${stats.activity} activities`} tone="amber" />
            <StatPill label={`${sectionIds.length} sections`} tone="emerald" />
            <StatPill label={`${rawLineCount} non-empty lines`} tone="slate" />
          </div>
          <div className="mt-3 text-[11px] leading-5 text-slate-500">
            Upload one or more subject/faculty documents. The importer reads PDF, DOCX, XLSX,
            and CSV directly, and uses Optiic OCR for scanned PDFs or image files when
            `OPTIIC_API_KEY` is configured.
          </div>
          {(importResult || importError) && (
            <div className="mt-3 space-y-2">
              {importResult && (
                <ImportSummary result={importResult} />
              )}
              {importError && (
                <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
                  {importError}
                </div>
              )}
              {importResult?.warnings?.length ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                  <div className="font-semibold">Import warnings</div>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {importResult.warnings.slice(0, 6).map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )}
        </div>

        <div className="px-4 py-4">
          {mode === 'guided' ? (
            parsed.error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
                <div className="font-semibold">Guided mode needs valid raw text first.</div>
                <div className="mt-1 text-xs leading-5">{parsed.error}</div>
                <button
                  type="button"
                  onClick={() => setMode('raw')}
                  className="mt-3 rounded-md border border-rose-300 bg-white px-3 py-1.5 text-xs font-medium text-rose-800 hover:bg-rose-100"
                >
                  Open raw editor
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => addRow('theory')}
                    className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Add theory
                  </button>
                  <button
                    type="button"
                    onClick={() => addRow('lab')}
                    className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Add lab
                  </button>
                  <button
                    type="button"
                    onClick={() => addRow('activity')}
                    className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Add activity
                  </button>
                </div>

                {parsed.rows.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
                    No course rows yet. Add a course above or switch to raw mode and paste data.
                  </div>
                ) : (
                  <div className="space-y-4">
                    {parsed.rows.map((row, index) => (
                      <CourseRowCard
                        key={`${row.code || 'course'}-${index}`}
                        row={row}
                        index={index}
                        sectionIds={sectionIds}
                        courseCodes={courseCodes}
                        onChange={(nextRow) => updateRow(index, nextRow)}
                        onDuplicate={() => duplicateRow(index)}
                        onRemove={() => removeRow(index)}
                      />
                    ))}
                  </div>
                )}
              </div>
            )
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">
                Raw mode keeps direct control of the serialized course text. Comments are preserved
                here; guided edits rewrite rows into a clean canonical format.
              </div>
              <textarea
                value={rawText}
                onChange={(event) => onChange(event.target.value)}
                rows={20}
                spellCheck={false}
                className="w-full rounded-lg border border-slate-200 px-3 py-3 font-mono text-[11px] leading-relaxed text-slate-800"
              />
              {parsed.error ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Parse check: {parsed.error}
                </div>
              ) : (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
                  Parse check passed. Switch back to guided mode any time.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {preview && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
          Parsed: <b>{preview.courses}</b> courses, <b>{preview.faculty}</b> faculty,{' '}
          <b>{preview.sections}</b> sections, <b>{preview.elective_blocks}</b> elective block(s).
        </div>
      )}

      {(error || preflightErrors.length > 0) && (
        <div className="space-y-3">
          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
              {error}
            </div>
          )}
          {preflightErrors.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
              <div className="font-semibold">Preflight issues</div>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {preflightErrors.slice(0, 5).map((issue, index) => (
                  <li key={index}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ImportSummary({ result }: { result: ImportResponse }) {
  return (
    <div className="rounded-md border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900">
      Imported <b>{result.summary.documents}</b> file(s) into <b>{result.summary.courses}</b>{' '}
      course row(s). New rows: <b>{result.summary.imported_courses}</b>. Faculty mappings:{' '}
      <b>{result.summary.faculty_mappings}</b>.
      {result.documents_info.length > 0 && (
        <div className="mt-2 space-y-1">
          {result.documents_info.map((doc) => (
            <div key={`${doc.filename}-${doc.format}`}>
              <span className="font-medium">{doc.filename}</span>: {doc.course_rows} recognised row(s),{' '}
              {doc.faculty_rows} faculty mapping row(s)
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

interface CourseRowCardProps {
  row: CourseDraft
  index: number
  sectionIds: string[]
  courseCodes: string[]
  onChange: (row: CourseDraft) => void
  onDuplicate: () => void
  onRemove: () => void
}

function CourseRowCard({
  row,
  index,
  sectionIds,
  courseCodes,
  onChange,
  onDuplicate,
  onRemove,
}: CourseRowCardProps) {
  const facultySlots = Math.max(sectionIds.length, row.facultyNames.length, 1)
  const referenceCodes = courseCodes.filter((code) => code !== row.code)
  const courseCodeListId = `course-codes-${index}`
  const facultyPreview =
    buildFacultySpec(row) ||
    (row.facultyMode === 'sections'
      ? '(blank section names currently fall back to backend auto placeholders)'
      : 'auto')

  function patch(next: Partial<CourseDraft>) {
    onChange({ ...row, ...next })
  }

  function setFacultyMode(nextMode: FacultyInputMode) {
    if (nextMode === row.facultyMode) return

    if (nextMode === 'same-as' && !row.sameAsCode.trim()) {
      patch({
        facultyMode: nextMode,
        sameAsCode: referenceCodes[0] ?? '',
      })
      return
    }

    if (nextMode === 'count' && !row.facultyCount) {
      patch({
        facultyMode: nextMode,
        facultyCount: Math.max(1, sectionIds.length || 1),
      })
      return
    }

    patch({ facultyMode: nextMode })
  }

  function updateFacultyName(slotIndex: number, value: string) {
    const nextNames = [...row.facultyNames]
    while (nextNames.length <= slotIndex) nextNames.push('')
    nextNames[slotIndex] = value
    patch({ facultyNames: nextNames })
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
      <datalist id={courseCodeListId}>
        {referenceCodes.map((code) => (
          <option key={code} value={code} />
        ))}
      </datalist>

      <div className="flex flex-col gap-3 border-b border-slate-200 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Row {index + 1}
          </div>
          <div className="mt-1 text-sm font-medium text-slate-800">
            {row.name.trim() || row.code.trim() || 'Untitled course'}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Serialized faculty: <span className="font-mono">{facultyPreview}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onDuplicate}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Duplicate
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded-md border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50"
          >
            Remove
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-12">
        <Field label="Code" className="md:col-span-2">
          <input
            value={row.code}
            onChange={(event) => patch({ code: event.target.value })}
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </Field>
        <Field label="Name" className="md:col-span-5">
          <input
            value={row.name}
            onChange={(event) => patch({ name: event.target.value })}
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </Field>
        <Field label="Credits" className="md:col-span-2">
          <input
            type="number"
            value={row.credits}
            onChange={(event) =>
              patch({ credits: Number.parseInt(event.target.value || '0', 10) || 0 })
            }
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </Field>
        <Field label="Type" className="md:col-span-3">
          <select
            value={row.kind}
            onChange={(event) => patch({ kind: event.target.value as CourseKind })}
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
          >
            <option value="theory">Theory</option>
            <option value="lab">Lab</option>
            <option value="activity">Activity</option>
          </select>
        </Field>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-12">
        {row.kind === 'lab' && (
          <Field label="Paired course" className="md:col-span-4">
            <input
              value={row.pairCourse}
              onChange={(event) => patch({ pairCourse: event.target.value })}
              list={courseCodeListId}
              placeholder="BCSL404"
              className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
            />
          </Field>
        )}

        {row.kind === 'activity' && (
          <>
            <Field label="Placement" className="md:col-span-3">
              <select
                value={row.lockedDay && row.lockedSlotsText ? 'locked' : 'flex'}
                onChange={(event) => {
                  if (event.target.value === 'locked') {
                    patch({ lockedDay: row.lockedDay || 'MON', lockedSlotsText: row.lockedSlotsText || '1' })
                    return
                  }
                  patch({ lockedDay: '', lockedSlotsText: '' })
                }}
                className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              >
                <option value="flex">Flexible</option>
                <option value="locked">Locked</option>
              </select>
            </Field>
            {row.lockedDay && row.lockedSlotsText && (
              <>
                <Field label="Locked day" className="md:col-span-2">
                  <select
                    value={row.lockedDay}
                    onChange={(event) => patch({ lockedDay: event.target.value })}
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                  >
                    {['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'].map((day) => (
                      <option key={day} value={day}>
                        {day}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Locked slots" className="md:col-span-3">
                  <input
                    value={row.lockedSlotsText}
                    onChange={(event) => patch({ lockedSlotsText: event.target.value })}
                    placeholder="5-7"
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                  />
                </Field>
              </>
            )}
          </>
        )}

        <Field
          label="Combined sections"
          className={row.kind === 'theory' ? 'md:col-span-3' : row.kind === 'lab' ? 'md:col-span-3' : 'md:col-span-2'}
        >
          <label className="inline-flex h-[42px] items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={row.combined}
              onChange={(event) => patch({ combined: event.target.checked })}
            />
            Single shared placement
          </label>
        </Field>

        <Field label="Extra type directives" className="md:col-span-4">
          <input
            value={row.extraTypeText}
            onChange={(event) => patch({ extraTypeText: event.target.value })}
            placeholder="Optional advanced suffix"
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
          />
        </Field>
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Faculty assignment
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Choose section-wise names, placeholder generation, or reuse another course mapping.
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <FacultyModeButton
              active={row.facultyMode === 'sections'}
              onClick={() => setFacultyMode('sections')}
            >
              By section
            </FacultyModeButton>
            <FacultyModeButton active={row.facultyMode === 'auto'} onClick={() => setFacultyMode('auto')}>
              Auto
            </FacultyModeButton>
            <FacultyModeButton active={row.facultyMode === 'count'} onClick={() => setFacultyMode('count')}>
              xN
            </FacultyModeButton>
            <FacultyModeButton
              active={row.facultyMode === 'same-as'}
              onClick={() => setFacultyMode('same-as')}
            >
              Same as
            </FacultyModeButton>
          </div>
        </div>

        {row.facultyMode === 'sections' && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: facultySlots }, (_, slotIndex) => {
              const label = sectionIds[slotIndex] ? `Section ${sectionIds[slotIndex]}` : `Faculty ${slotIndex + 1}`
              return (
                <Field key={slotIndex} label={label}>
                  <input
                    value={row.facultyNames[slotIndex] ?? ''}
                    onChange={(event) => updateFacultyName(slotIndex, event.target.value)}
                    placeholder="Faculty name"
                    className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
                  />
                </Field>
              )
            })}
          </div>
        )}

        {row.facultyMode === 'auto' && (
          <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            The backend will generate one placeholder faculty per section for this course.
          </div>
        )}

        {row.facultyMode === 'count' && (
          <div className="mt-3 max-w-xs">
            <Field label="Placeholder count">
              <input
                type="number"
                min={1}
                value={row.facultyCount}
                onChange={(event) =>
                  patch({ facultyCount: Math.max(1, Number.parseInt(event.target.value || '1', 10) || 1) })
                }
                className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </Field>
          </div>
        )}

        {row.facultyMode === 'same-as' && (
          <div className="mt-3 max-w-sm">
            <Field label="Reference course">
              <input
                value={row.sameAsCode}
                onChange={(event) => patch({ sameAsCode: event.target.value })}
                list={courseCodeListId}
                placeholder="BCS401"
                className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              />
            </Field>
          </div>
        )}
      </div>
    </div>
  )
}

function ModeButton({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'rounded-md px-3 py-1.5 text-xs font-medium transition',
        active ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

function FacultyModeButton({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'rounded-md border px-2.5 py-1.5 text-xs font-medium transition',
        active
          ? 'border-slate-900 bg-slate-900 text-white'
          : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

function StatPill({ label, tone }: { label: string; tone: 'slate' | 'indigo' | 'sky' | 'amber' | 'emerald' }) {
  const classes =
    {
      slate: 'bg-slate-100 text-slate-700',
      indigo: 'bg-indigo-100 text-indigo-700',
      sky: 'bg-sky-100 text-sky-700',
      amber: 'bg-amber-100 text-amber-700',
      emerald: 'bg-emerald-100 text-emerald-700',
    }[tone] ?? 'bg-slate-100 text-slate-700'

  return <span className={`rounded-full px-2.5 py-1 font-medium ${classes}`}>{label}</span>
}

function Field({
  label,
  children,
  className = '',
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <label className={`block ${className}`}>
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      {children}
    </label>
  )
}
