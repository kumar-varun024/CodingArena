import type { Candidate, Match, Slot } from '../types';

export function CandidatePanel({ match, slot, onArtifact }: { match: Match; slot: Slot; onArtifact: (id: string) => void }) {
  const candidate: Candidate | null = match.slots[slot].candidate;
  const checks = candidate?.verification;
  return <article className={`candidate candidate-${slot}`} aria-labelledby={`candidate-${slot}`}>
    <div className="candidate-heading"><span className="slot-mark">{slot.toUpperCase()}</span><div><span className="eyebrow">INDEPENDENT SUBMISSION</span><h3 id={`candidate-${slot}`}>Contender {slot.toUpperCase()}</h3></div><span className={`badge ${candidate?.eligibility || 'pending'}`}>{candidate?.eligibility || 'Awaiting submission'}</span></div>
    <p className="provider">{match.provider_labels[slot] || 'Unknown provider / model'}<span>{match.provider_labels[slot] ? 'Operator-recorded configuration' : 'Configuration has not been recorded'}</span></p>
    {candidate && checks ? <>
      <div className="check-summary"><strong>{checks.passed_count}<span> / {checks.check_count}</span></strong><div><b>recorded checks passed</b><span>Full verification · {checks.status}</span></div></div>
      <div className={`check-track ${checks.status}`} aria-label={`${checks.passed_count} of ${checks.check_count} checks passed`}><span style={{ width: `${checks.check_count ? Math.min(100, checks.passed_count / checks.check_count * 100) : 0}%` }} /></div>
      <dl className="snapshot"><div><dt>Candidate</dt><dd>{candidate.candidate_id}</dd></div><div><dt>Commit</dt><dd title={candidate.commit_sha}>{candidate.commit_sha.slice(0, 12)} · revision {candidate.revision}</dd></div><div><dt>Snapshot</dt><dd title={candidate.tree_digest}>{candidate.tree_digest.slice(0, 16)}…</dd></div></dl>
      {!!checks.failed_check_ids.length && <p className="failure-text">Failed: {checks.failed_check_ids.join(', ')}</p>}
      {checks.status === 'stale' && <p className="warning-text">The suite changed. Full verification must run again.</p>}
      {checks.status === 'error' && <p className="failure-text">Runner error. Eligibility remains unknown.</p>}
      <footer><span>{match.slots[slot].review_complete ? '✓ Review complete' : '○ Review pending'}</span>{checks.log_artifact_id && <button className="text-button" onClick={() => onArtifact(checks.log_artifact_id!)}>Inspect log ↗</button>}</footer>
    </> : <div className="empty-candidate"><span>⌘</span><p>No frozen snapshot yet.</p><small>The agent submits its own committed code.</small></div>}
  </article>;
}
