export type Slot = 'a' | 'b';
export type Mode = 'live' | 'fixture';
export type Phase = 'building' | 'reviewing' | 'repairing' | 'verifying' | 'decision' | 'complete' | 'cancelled';
export interface Source { kind: 'operator_recorded' | 'fixture' | 'switch_context' | 'unverified_context'; room_id: string | null; message_id: string | null; note: string | null }
export interface EvidenceKey { candidate_digest: string; runner_digest: string; spec_digest: string; suite_digest: string }
export interface Verification { check_count: number; passed_count: number; failed_check_ids: string[]; status: 'queued' | 'running' | 'passed' | 'failed' | 'error' | 'stale'; evidence_key: EvidenceKey | null; job_id: string | null; log_artifact_id: string | null }
export interface Candidate { candidate_id: string; commit_sha: string; tree_digest: string; revision: number; slot: Slot; eligibility: 'pending' | 'eligible' | 'ineligible' | 'unknown'; verification: Verification }
export interface Scenario { capacity: number; steps: { op: 'book' | 'cancel' | 'available' | 'reservations'; args: unknown[]; expected: boolean | number | Record<string, number> }[] }
export interface Challenge { challenge_id: string; title: string; requirement_ids: string[]; target_candidate_id: string; submitted_by: Slot; scenario: Scenario; disposition: 'pending' | 'accepted' | 'rejected'; decision_reason: string | null; regression_digest: string | null; reproduction: { actual_summary: string | null; job_id: string; log_artifact_id: string | null; reference_passed: boolean | null; target_failed_twice: boolean | null; status: 'queued' | 'running' | 'reproduced' | 'not_reproduced' | 'invalid' | 'inconclusive' } }
export interface Job { job_id: string; match_id: string; kind: 'practice' | 'verification' | 'challenge'; candidate_id: string | null; challenge_id: string | null; status: 'queued' | 'running' | 'completed' | 'error'; result: Verification | Challenge['reproduction'] | null; error: { code: string; message: string; details?: Record<string, unknown> } | null }
export interface Match { match_id: string; task_id: string; phase: Phase; mode: Mode; provider_labels: Record<Slot, string | null>; spec_digest: string; suite_digest: string; repair_round: number; max_repair_rounds: number; created_at: string; updated_at: string; slots: Record<Slot, { candidate: Candidate | null; review_complete: boolean }>; jobs: Job[]; challenges: Challenge[]; outcome: { selection: Slot | 'neither'; reason: string; selected_candidate_id: string | null; patch_artifact_id: string | null; evidence_artifact_id: string } | null }
export interface Assignment { match_id: string; phase: Phase; slot: Slot; workspace_path: string; review_path: string | null; allowed_files: string[]; base_commit: string; spec_digest: string; suite_digest: string; task_id: string; task_text: string; task_spec: { requirements: Record<string, string>; methods: string[] }; public_checks: string[]; public_check_descriptions: string[]; accepted_challenges: Challenge[]; repair_round: number; candidate_budget_minutes: number; target_candidate_id: string | null; provider_labels: Record<Slot, string | null> }
export interface ArenaEvent { seq: number; at: string; actor: string; type: string; data: Record<string, unknown> }
export interface Health { status: string; api_version: string; mode: Mode; runner_available: boolean }

// These are UI guards around server-owned eligibility, never a scoring or winner algorithm.
export function canSelect(match: Match, slot: Slot): boolean {
  const candidate = match.slots[slot].candidate;
  const key = candidate?.verification.evidence_key;
  return match.phase === 'decision' && candidate?.eligibility === 'eligible'
    && candidate.verification.status === 'passed' && !!key
    && key.candidate_digest === candidate.tree_digest && key.spec_digest === match.spec_digest
    && key.suite_digest === match.suite_digest && !hasPending(match);
}
export function hasPending(match: Match): boolean {
  return match.jobs.some(job => job.status === 'queued' || job.status === 'running')
    || match.challenges.some(challenge => challenge.disposition === 'pending');
}
