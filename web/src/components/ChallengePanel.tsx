import type { Challenge } from '../types';

export function ChallengePanel({
  challenge,
  disabled,
  onDecision,
  onArtifact,
}: {
  challenge: Challenge;
  disabled: boolean;
  onDecision: (id: string, disposition: 'accepted' | 'rejected') => void;
  onArtifact: (id: string) => void;
}) {
  const reproduction = challenge.reproduction;
  const terminal = !['queued', 'running'].includes(reproduction.status);
  const acceptable =
    reproduction.status === 'reproduced' &&
    reproduction.reference_passed === true &&
    reproduction.target_failed_twice === true;
  return (
    <article className="challenge">
      <header>
        <div>
          <span className="eyebrow">
            {challenge.requirement_ids.join(' · ')} / FROM {challenge.submitted_by.toUpperCase()}
          </span>
          <h3>{challenge.title}</h3>
          <p>
            Exact target: <code>{challenge.target_candidate_id}</code>
          </p>
        </div>
        <span
          className={`badge ${challenge.disposition === 'pending' ? 'pending' : challenge.disposition}`}
        >
          {challenge.disposition}
        </span>
      </header>
      <div className="proof-grid">
        <div>
          <span className="eyebrow">EXPECTED</span>
          <p>Capacity {challenge.scenario.capacity}; exact return values below.</p>
        </div>
        <div>
          <span className="eyebrow">OBSERVED · {reproduction.status.toUpperCase()}</span>
          <p>{reproduction.actual_summary || 'No conclusive result is available yet.'}</p>
        </div>
      </div>
      <details>
        <summary>
          Inspect JSON reproduction <span>{challenge.scenario.steps.length} operations</span>
        </summary>
        <pre>{JSON.stringify(challenge.scenario, null, 2)}</pre>
      </details>
      <div className="proof-notes">
        <span>
          Reference:{' '}
          {reproduction.reference_passed === null
            ? 'unknown'
            : reproduction.reference_passed
              ? 'passed'
              : 'failed'}
        </span>
        <span>
          Target failed twice:{' '}
          {reproduction.target_failed_twice === null
            ? 'unknown'
            : reproduction.target_failed_twice
              ? 'yes'
              : 'no'}
        </span>
      </div>
      {challenge.decision_reason && (
        <p className="decision-reason">Decision: {challenge.decision_reason}</p>
      )}
      <footer>
        {reproduction.log_artifact_id ? (
          <button className="text-button" onClick={() => onArtifact(reproduction.log_artifact_id!)}>
            Inspect reproduction log ↗
          </button>
        ) : (
          <span>Evidence pending</span>
        )}
        {challenge.disposition === 'pending' && (
          <div className="button-row">
            <button
              disabled={disabled || !terminal}
              onClick={() => onDecision(challenge.challenge_id, 'rejected')}
            >
              Reject claim
            </button>
            <button
              className="primary"
              disabled={disabled || !acceptable}
              onClick={() => onDecision(challenge.challenge_id, 'accepted')}
            >
              Accept requirement violation
            </button>
          </div>
        )}
      </footer>
    </article>
  );
}
