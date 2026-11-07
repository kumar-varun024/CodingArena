import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, ArenaApi, CONTRACT_HASH, CONTRACT_VERSION, readJournal } from './api';
import type { Operation } from './api';
import { canSelect, hasPending } from './types';
import type { ArenaEvent, Assignment, Health, Job, Match, Slot } from './types';
import { CandidatePanel } from './components/CandidatePanel';
import { ChallengePanel } from './components/ChallengePanel';
import { ArtifactDialog } from './components/ArtifactDialog';

const phases = ['building', 'reviewing', 'repairing', 'verifying', 'decision', 'complete'];
const fixtures = [
  ['fixture-building', 'Independent build'],
  ['fixture-pending', 'Claim awaiting decision'],
  ['fixture-repair', 'Repair round'],
  ['fixture-decision', 'Eligible selection'],
  ['fixture-neither', 'Neither eligible'],
  ['fixture-stale', 'Stale evidence / 409'],
  ['fixture-error', 'Runner error'],
];
const defaultApi = new ArenaApi(import.meta.env.VITE_ARENA_API_BASE || '/api/v1');
function journal(): Operation[] {
  try {
    return readJournal();
  } catch {
    return [];
  }
}
function label(value: string) {
  return value.replaceAll('_', ' ');
}
function saveFile(text: string, filename: string, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function App({
  api = defaultApi,
  initialMatch = '',
  pollInterval = 2000,
}: {
  api?: ArenaApi;
  initialMatch?: string;
  pollInterval?: number;
}) {
  const [matchId, setMatchId] = useState(initialMatch);
  const [draftId, setDraftId] = useState(initialMatch);
  const [token, setToken] = useState('');
  const [session, setSession] = useState(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [match, setMatch] = useState<Match | null>(null);
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [events, setEvents] = useState<ArenaEvent[]>([]);
  const [fresh, setFresh] = useState(false);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('');
  const [operations, setOperations] = useState(journal);
  const [artifact, setArtifact] = useState<{ id: string; text: string; type: string } | null>(null);
  const [labels, setLabels] = useState({ a: '', b: '' });
  const [budget, setBudget] = useState(10);
  const [repairs, setRepairs] = useState(2);
  const serial = useRef(0);

  useEffect(() => {
    let active = true;
    setHealth(null);
    api
      .get<Health>('/health')
      .then((value) => {
        if (!active) return;
        if (value.api_version !== CONTRACT_VERSION)
          throw new Error(
            `Interface ${value.api_version} is incompatible with this dashboard (${CONTRACT_VERSION}).`,
          );
        setHealth(value);
        if (!initialMatch && value.mode === 'fixture') {
          setMatchId((current) => current || 'fixture-decision');
          setDraftId((current) => current || 'fixture-decision');
        }
      })
      .catch((value) => {
        if (active) setError(value instanceof Error ? value.message : 'Health check failed.');
      });
    return () => {
      active = false;
    };
  }, [api, initialMatch, session]);

  const refresh = useCallback(async () => {
    if (!matchId) return;
    const request = ++serial.current;
    try {
      const [next, task, timeline] = await Promise.all([
        api.get<Match>(`/matches/${encodeURIComponent(matchId)}`),
        api.get<Assignment>(`/matches/${encodeURIComponent(matchId)}/assignments/a`),
        api.get<{ events: ArenaEvent[]; next_after: number }>(
          `/matches/${encodeURIComponent(matchId)}/events?after=0`,
        ),
      ]);
      if (request !== serial.current) return;
      setMatch(next);
      setAssignment(task);
      setEvents(timeline.events);
      setFresh(true);
      setError('');
    } catch (value) {
      if (request !== serial.current) return;
      setFresh(false);
      setError(value instanceof Error ? value.message : 'Refresh failed.');
    }
  }, [api, matchId]);
  useEffect(() => {
    setMatch(null);
    setActionError('');
    setNotice('');
    setReason('');
    setAssignment(null);
    setEvents([]);
    setFresh(false);
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, pollInterval);
    return () => {
      clearInterval(timer);
      serial.current++;
    };
  }, [refresh, session, pollInterval]);

  async function record(path: string, payload: Record<string, unknown>, operation?: Operation) {
    setBusy(true);
    setFresh(false);
    setActionError('');
    setNotice('');
    try {
      const result = operation
        ? await api.retry<Match>(operation)
        : await api.mutate<Match>(path, payload);
      setNotice('Action recorded. Refreshing measured evidence.');
      if (result.match_id && result.match_id !== matchId) {
        setMatchId(result.match_id);
        setDraftId(result.match_id);
      }
    } catch (value) {
      setActionError(
        `${value instanceof ApiError ? `${value.code}: ` : ''}${value instanceof Error ? value.message : 'Request failed.'}${value instanceof ApiError && value.requestId ? ` Request ID: ${value.requestId}` : ''}`,
      );
    } finally {
      setOperations(journal());
      // In particular, a 409 refreshes server state and never becomes optimistic success.
      await refresh();
      setBusy(false);
    }
  }
  async function inspect(id: string) {
    setActionError('');
    try {
      const result = await api.artifact(id);
      setArtifact({ id, ...result });
    } catch (value) {
      setActionError(value instanceof Error ? value.message : 'Artifact unavailable.');
    }
  }
  async function inspectJob(job: Job) {
    try {
      const current = await api.get<Job>(`/jobs/${encodeURIComponent(job.job_id)}`);
      setArtifact({
        id: current.job_id,
        text: JSON.stringify(current, null, 2),
        type: 'application/json',
      });
    } catch (value) {
      setActionError(value instanceof Error ? value.message : 'Job unavailable.');
    }
  }
  const mode = api.mode;
  const canRecord =
    !!token.trim() && fresh && !busy && !!mode && health?.api_version === CONTRACT_VERSION;
  const canAct = canRecord && !!reason.trim();
  const reviewsDone =
    match && Object.values(match.slots).every((slot) => slot.review_complete) && !hasPending(match);
  function action(name: string) {
    if (match)
      void record(`/matches/${encodeURIComponent(match.match_id)}/actions`, {
        action: name,
        reason: reason.trim(),
      });
  }
  function select(slot: Slot | 'neither') {
    if (!match) return;
    const candidate = slot === 'neither' ? null : match.slots[slot].candidate;
    void record(`/matches/${encodeURIComponent(match.match_id)}/selection`, {
      selection: slot,
      candidate_id: candidate?.candidate_id || null,
      expected_evidence_key: candidate?.verification.evidence_key || null,
      reason: reason.trim(),
    });
  }
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#main">
          <span className="brand-icon">〈〉</span>coding<span>arena</span>
        </a>
        <nav aria-label="Primary">
          <a href="#main" className="active">
            Match workspace
          </a>
          <a href="#evidence">Evidence</a>
          <a href="#activity">Activity</a>
        </nav>
        <span className="local-mark">
          <i /> LOCAL WORKSPACE
        </span>
      </header>
      <div className={`mode-banner ${mode || 'unknown'}`} role="status">
        <span>
          <b>
            {mode === 'fixture'
              ? 'FIXTURE REPLAY'
              : mode === 'live'
                ? 'LIVE ENGINE'
                : 'CONNECTION UNVERIFIED'}
          </b>{' '}
          ·{' '}
          {mode === 'fixture'
            ? 'Synthetic candidates and deterministic evidence. No live agent discovery.'
            : mode === 'live'
              ? 'Results come from the connected engine’s recorded checks.'
              : 'Connect to an API with a valid mode header to inspect evidence.'}
        </span>
        <span>
          Interface {CONTRACT_VERSION}
          {mode === 'live'
            ? ` · Runner ${health ? (health.runner_available ? 'available' : 'unavailable') : 'unknown'}`
            : ''}
        </span>
      </div>
      <main id="main">
        <div className="workspace-heading">
          <div>
            <p className="eyebrow">HUMAN-LED CODE REVIEW</p>
            <h1>
              Let the evidence decide<span>.</span>
            </h1>
            <p>Two independent solutions. A shared test suite. Your call.</p>
          </div>
          <div className="workspace-id">
            <span className="eyebrow">ACTIVE MATCH</span>
            <code>{match?.match_id || 'Not connected'}</code>
            <span>
              {match ? `booking-v1 · ${label(match.phase)}` : 'One match · two contenders'}
            </span>
          </div>
        </div>
        <details className="connection" open={!match}>
          <summary>
            <span>↗ Connection & match controls</span>
            <span>
              {mode || 'unknown'} · {api.baseUrl}
            </span>
          </summary>
          <div className="connection-body">
            <form
              className="connection-form"
              onSubmit={(event) => {
                event.preventDefault();
                api.setToken(token);
                setMatchId(draftId.trim());
                setSession((value) => value + 1);
              }}
            >
              <label>
                Operator token
                <input
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(event) => {
                    setToken(event.target.value);
                    api.setToken(event.target.value);
                    setFresh(false);
                  }}
                  placeholder="Kept in memory for this session"
                />
              </label>
              <label>
                Match ID
                <input
                  value={draftId}
                  onChange={(event) => setDraftId(event.target.value)}
                  placeholder="Paste the engine’s match ID"
                />
              </label>
              <button type="submit" className="primary">
                Connect / refresh
              </button>
            </form>
            {mode === 'fixture' && (
              <label className="fixture-picker">
                Explore a fixture
                <select
                  aria-label="Fixture scenario"
                  value={fixtures.some(([id]) => id === matchId) ? matchId : ''}
                  onChange={(event) => {
                    setMatchId(event.target.value);
                    setDraftId(event.target.value);
                  }}
                >
                  <option value="" disabled>
                    Choose a labelled replay
                  </option>
                  {fixtures.map(([id, title]) => (
                    <option key={id} value={id}>
                      {title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <details className="create-match">
              <summary>Create a new booking-v1 match</summary>
              <div className="create-grid">
                <label>
                  Contender A provider / model
                  <input
                    value={labels.a}
                    onChange={(event) => setLabels({ ...labels, a: event.target.value })}
                    placeholder="Unknown if left blank"
                  />
                </label>
                <label>
                  Contender B provider / model
                  <input
                    value={labels.b}
                    onChange={(event) => setLabels({ ...labels, b: event.target.value })}
                    placeholder="Unknown if left blank"
                  />
                </label>
                <label>
                  Build budget (minutes)
                  <input
                    type="number"
                    min="1"
                    value={budget}
                    onChange={(event) => setBudget(Number(event.target.value))}
                  />
                </label>
                <label>
                  Repair round cap
                  <select
                    value={repairs}
                    onChange={(event) => setRepairs(Number(event.target.value))}
                  >
                    <option>0</option>
                    <option>1</option>
                    <option>2</option>
                  </select>
                </label>
              </div>
              <p className="muted">
                Labels are operator-recorded. The budget is advisory; it is not a provider token
                quota.
              </p>
              <button
                disabled={
                  busy ||
                  !token.trim() ||
                  !mode ||
                  health?.api_version !== CONTRACT_VERSION ||
                  !Number.isInteger(budget) ||
                  budget < 1
                }
                onClick={() =>
                  void record('/matches', {
                    task_id: 'booking-v1',
                    candidate_budget_minutes: budget,
                    max_repair_rounds: repairs,
                    provider_labels: { a: labels.a.trim() || null, b: labels.b.trim() || null },
                  })
                }
              >
                Create match
              </button>
            </details>
          </div>
        </details>
        {error && (
          <div className="alert error" role="alert">
            {error}
          </div>
        )}
        {actionError && (
          <div className="alert error" role="alert">
            {actionError}
          </div>
        )}
        {notice && (
          <div className="alert success" role="status">
            {notice}
          </div>
        )}
        {match ? (
          <>
            <ol className="phase-strip" aria-label="Match progress">
              {phases.map((phase, index) => (
                <li
                  key={phase}
                  className={`${phase === match.phase ? 'current' : ''} ${phases.indexOf(match.phase) > index ? 'done' : ''}`}
                  aria-current={phase === match.phase ? 'step' : undefined}
                >
                  <span>{phases.indexOf(match.phase) > index ? '✓' : `0${index + 1}`}</span>
                  {phase}
                </li>
              ))}
            </ol>
            {match.phase === 'cancelled' && (
              <div className="alert error">
                This match was cancelled. Interrupted work is not a successful result.
              </div>
            )}
            <section className="task-card">
              <div className="task-symbol">⌘</div>
              <div>
                <span className="eyebrow">THE FROZEN TASK · {match.task_id.toUpperCase()}</span>
                <h2>Build a reliable booking system.</h2>
                <p>
                  {assignment?.task_text ||
                    'Implement src/booking.py against the frozen booking-v1 requirements.'}
                </p>
                <div className="task-tags">
                  <span>Python module</span>
                  <span>src/booking.py</span>
                  <span>
                    Repair {match.repair_round} / {match.max_repair_rounds}
                  </span>
                </div>
              </div>
              <details>
                <summary>Read task requirements ↗</summary>
                <div className="requirements">
                  {Object.entries(assignment?.task_spec.requirements || {}).map(([id, text]) => (
                    <p key={id}>
                      <b>{id}</b> {text}
                    </p>
                  ))}
                  <p className="muted">
                    Multi-instance isolation is covered by trusted full-suite checks; JSON
                    challenges use one instance.
                  </p>
                  <code>Spec: {match.spec_digest}</code>
                </div>
              </details>
            </section>
            <div className="section-heading">
              <h2>
                Frozen submissions{' '}
                <span>
                  {String(
                    Object.values(match.slots).filter((slot) => slot.candidate).length,
                  ).padStart(2, '0')}
                </span>
              </h2>
              <span className="muted">Engine-owned status · exact snapshots</span>
            </div>
            <section className="candidate-grid" aria-label="Contender comparison">
              {(['a', 'b'] as Slot[]).map((slot) => (
                <CandidatePanel
                  key={slot}
                  match={match}
                  slot={slot}
                  onArtifact={(id) => void inspect(id)}
                />
              ))}
            </section>
            <div className="review-grid">
              <section id="evidence">
                <div className="section-heading">
                  <h2>
                    Cross-review evidence{' '}
                    <span>{String(match.challenges.length).padStart(2, '0')}</span>
                  </h2>
                </div>
                {match.challenges.length ? (
                  match.challenges.map((challenge) => (
                    <ChallengePanel
                      key={challenge.challenge_id}
                      challenge={challenge}
                      disabled={!canAct || match.phase !== 'reviewing'}
                      onDecision={(id, disposition) =>
                        void record(
                          `/matches/${encodeURIComponent(match.match_id)}/challenges/${encodeURIComponent(id)}/decision`,
                          { disposition, reason: reason.trim() },
                        )
                      }
                      onArtifact={(id) => void inspect(id)}
                    />
                  ))
                ) : (
                  <div className="empty-state">
                    <span>◎</span>
                    <h3>No claims submitted</h3>
                    <p>A review can finish with no findings. A bug is never required.</p>
                  </div>
                )}
                <section className="jobs">
                  <h3>
                    Recorded jobs <span>{match.jobs.length}</span>
                  </h3>
                  {match.jobs.length ? (
                    match.jobs.slice(-8).map((job) => (
                      <button
                        className="job-row"
                        key={job.job_id}
                        onClick={() => void inspectJob(job)}
                      >
                        <span className="job-icon">{job.kind === 'practice' ? '○' : '↗'}</span>
                        <span>
                          <b>
                            {job.kind === 'practice'
                              ? 'Public practice · does not establish eligibility'
                              : label(job.kind)}
                          </b>
                          <code>{job.job_id}</code>
                        </span>
                        <span className={`badge ${job.status}`}>{job.status}</span>
                      </button>
                    ))
                  ) : (
                    <p className="muted">No execution jobs recorded.</p>
                  )}
                </section>
              </section>
              <aside className="decision-panel">
                <span className="eyebrow">THE HUMAN DECISION</span>
                <h2>
                  Your judgment.
                  <br />
                  Recorded with evidence.
                </h2>
                <p>Discuss semantics in Switch. Record the formal action here.</p>
                <label>
                  Decision / action reason
                  <textarea
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Explain the requirement, evidence, or tradeoff behind this action."
                    rows={4}
                  />
                </label>
                {match.phase === 'decision' && (
                  <>
                    <div className="selection-options">
                      <button
                        className="primary"
                        disabled={!canAct || !canSelect(match, 'a')}
                        onClick={() => select('a')}
                      >
                        Select contender A <span aria-hidden="true">↗</span>
                      </button>
                      <button
                        className="primary"
                        disabled={!canAct || !canSelect(match, 'b')}
                        onClick={() => select('b')}
                      >
                        Select contender B <span aria-hidden="true">↗</span>
                      </button>
                      <button disabled={!canAct} onClick={() => select('neither')}>
                        Select neither
                      </button>
                    </div>
                    <p className="muted">
                      Selection requires fresh, eligible evidence. Neither is a valid outcome.
                    </p>
                  </>
                )}
                {match.phase === 'building' && (
                  <button
                    className="primary"
                    disabled={
                      !canAct ||
                      !match.slots.a.candidate ||
                      !match.slots.b.candidate ||
                      match.jobs.some((job) => ['queued', 'running'].includes(job.status))
                    }
                    onClick={() => action('reveal')}
                  >
                    Reveal both submissions
                  </button>
                )}
                {match.phase === 'reviewing' && (
                  <div className="selection-options">
                    <button
                      className="primary"
                      disabled={!canAct || !reviewsDone}
                      onClick={() => action('finalize')}
                    >
                      Run full verification
                    </button>
                    <button
                      disabled={
                        !canAct || !reviewsDone || match.repair_round >= match.max_repair_rounds
                      }
                      onClick={() => action('start_repair')}
                    >
                      Start repair round
                    </button>
                  </div>
                )}
                {match.phase === 'decision' && (
                  <details className="more-actions">
                    <summary>Repair or rerun verification</summary>
                    <button
                      disabled={!canAct || match.repair_round >= match.max_repair_rounds}
                      onClick={() => action('start_repair')}
                    >
                      Start repair round
                    </button>
                    <button disabled={!canAct} onClick={() => action('finalize')}>
                      Rerun full suite
                    </button>
                  </details>
                )}
                {['repairing', 'verifying'].includes(match.phase) && (
                  <p className="waiting-note">
                    {match.phase === 'repairing'
                      ? 'Waiting for both agents to submit their own repair commits.'
                      : 'Waiting for both full verification jobs to finish.'}
                  </p>
                )}
                {match.outcome && (
                  <div className="outcome">
                    <span className="badge accepted">Match complete</span>
                    <h3>
                      {match.outcome.selection === 'neither'
                        ? 'Neither selected'
                        : `Contender ${match.outcome.selection.toUpperCase()} selected`}
                    </h3>
                    <p>{match.outcome.reason}</p>
                    {match.outcome.patch_artifact_id && (
                      <button onClick={() => void inspect(match.outcome!.patch_artifact_id!)}>
                        Open selected patch ↗
                      </button>
                    )}
                    <button onClick={() => void inspect(match.outcome!.evidence_artifact_id)}>
                      Open evidence pack ↗
                    </button>
                  </div>
                )}
                {!['complete', 'cancelled'].includes(match.phase) && (
                  <button
                    className="cancel-button"
                    disabled={!canAct}
                    onClick={() => action('cancel')}
                  >
                    Cancel match
                  </button>
                )}
                {!fresh && (
                  <p className="warning-text">
                    Evidence is not current. Refresh before recording an action.
                  </p>
                )}
                <div className="measured-note">
                  <span>✓</span>
                  <p>
                    Passing recorded checks is evidence of coverage. It is not proof of bug-free
                    code.
                  </p>
                </div>
              </aside>
            </div>
            <section id="activity" className="activity">
              <div className="section-heading">
                <h2>Match activity</h2>
                <span className="muted">
                  {fresh ? 'Polling every 2 seconds' : 'Refresh required'}
                </span>
              </div>
              {events.length ? (
                <ol>
                  {events.map((event) => (
                    <li key={event.seq}>
                      <span className="event-dot" />
                      <time dateTime={event.at}>
                        {new Date(event.at).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </time>
                      <div>
                        <b>{label(event.type)}</b>
                        <span>
                          {event.actor} · event {event.seq}
                        </span>
                        <details>
                          <summary>Event details</summary>
                          <pre>{JSON.stringify(event.data, null, 2)}</pre>
                        </details>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="muted">No visible events yet.</p>
              )}
            </section>
          </>
        ) : (
          <section className="welcome">
            <span className="eyebrow">READY WHEN YOU ARE</span>
            <h2>Bring two solutions to the same table.</h2>
            <p>
              Enter your runtime operator token and match ID above, or create a booking-v1 match.
              The dashboard will show the engine’s recorded evidence.
            </p>
            <div>
              <span>01 Independent build</span>
              <span>02 Executable review</span>
              <span>03 Human selection</span>
            </div>
          </section>
        )}
        <section className="journal">
          <details>
            <summary>
              Operation recovery journal{' '}
              <span>
                {
                  operations.filter((operation) =>
                    ['pending', 'ambiguous'].includes(operation.state),
                  ).length
                }{' '}
                unresolved
              </span>
            </summary>
            <p>
              Saved request bodies and IDs support exact retry after a timeout. Tokens stay in
              memory.
            </p>
            {operations
              .slice()
              .reverse()
              .slice(0, 20)
              .map((operation) => (
                <div className="journal-row" key={`${operation.base_url}-${operation.request_id}`}>
                  <div>
                    <b>{operation.state}</b>
                    <code>{operation.request_id}</code>
                    <small>
                      {operation.base_url}
                      {operation.path}
                    </small>
                  </div>
                  {['pending', 'ambiguous'].includes(operation.state) && (
                    <button
                      disabled={
                        busy ||
                        !token.trim() ||
                        operation.base_url !== api.baseUrl ||
                        operation.mode !== mode
                      }
                      onClick={() => void record(operation.path, {}, operation)}
                    >
                      Retry same request
                    </button>
                  )}
                </div>
              ))}
            {!!operations.length && (
              <button
                onClick={() =>
                  saveFile(
                    JSON.stringify(operations, null, 2),
                    'arena-operation-journal.json',
                    'application/json',
                  )
                }
              >
                Download journal
              </button>
            )}
          </details>
        </section>
        <footer className="page-footer">
          <span className="brand">
            coding<span>arena</span>
          </span>
          <span>Built for independent work. Decided by people.</span>
          <details>
            <summary>Interface {CONTRACT_VERSION} · provenance</summary>
            <p>
              Canonical SHA-256: <code>{CONTRACT_HASH}</code>
            </p>
            <p>
              Live dashboard actions use operator_recorded; fixture actions use fixture. Switch room
              approval is not automatically verified.
            </p>
          </details>
        </footer>
      </main>
      {artifact && (
        <ArtifactDialog
          artifact={artifact}
          fixture={mode === 'fixture'}
          onClose={() => setArtifact(null)}
          onDownload={() =>
            saveFile(
              artifact.text,
              `${artifact.id}.${artifact.type === 'application/json' ? 'json' : 'txt'}`,
              artifact.type,
            )
          }
        />
      )}
    </>
  );
}
