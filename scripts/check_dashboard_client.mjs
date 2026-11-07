import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const expectedVersion = '1.1';
const expectedHash = 'c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f';

function argsFrom(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    if (!['--api-url', '--state-dir', '--match'].includes(key) || !argv[i + 1]) {
      throw new Error('Usage: --api-url URL --state-dir PATH --match ID');
    }
    if (args[key]) throw new Error(`Duplicate argument: ${key}`);
    args[key] = argv[i + 1];
  }
  if (Object.keys(args).length !== 3) {
    throw new Error('Usage: --api-url URL --state-dir PATH --match ID');
  }
  return args;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const { '--api-url': apiUrl, '--state-dir': stateDir, '--match': matchId } =
  argsFrom(process.argv.slice(2));
const url = new URL(apiUrl);
assert(url.protocol === 'http:' || url.protocol === 'https:', '--api-url must be HTTP(S)');
const token = (await readFile(resolve(stateDir, 'auth/operator.token'), 'utf8')).trim();
assert(token.length > 0, 'Operator token file is empty');

const apiModuleUrl = pathToFileURL(resolve('web/src/api.ts')).href;
const { ArenaApi, ApiError, CONTRACT_VERSION, CONTRACT_HASH } = await import(apiModuleUrl);
assert(CONTRACT_VERSION === expectedVersion, 'Dashboard contract version constant mismatch');
assert(CONTRACT_HASH === expectedHash, 'Dashboard contract hash constant mismatch');

const api = new ArenaApi(apiUrl);
api.setToken(token);
const health = await api.get('/health');
assert(health.api_version === CONTRACT_VERSION, 'Health interface version mismatch');
assert(health.mode === 'live' && api.mode === 'live', 'Health response is not live mode');

const matchPath = `/matches/${encodeURIComponent(matchId)}`;
const match = await api.get(matchPath);
assert(match.match_id === matchId, 'Match ID mismatch');
const labels = match.provider_labels;
assert(labels && typeof labels === 'object', 'provider_labels is missing');
for (const slot of ['a', 'b']) {
  assert(Object.hasOwn(labels, slot), `provider_labels.${slot} is missing`);
  assert(labels[slot] === null || typeof labels[slot] === 'string',
    `provider_labels.${slot} must be string or null`);
}

const events = await api.get(`${matchPath}/events?after=0`);
assert(events && Array.isArray(events.events), 'Events response is malformed');
assert(Number.isInteger(events.next_after), 'Events next_after is malformed');

const unknownJob = new ArenaApi(apiUrl);
unknownJob.setToken(token);
let unknownJobError;
try {
  await unknownJob.get('/jobs/codex-dashboard-client-check-unknown-job');
} catch (error) {
  unknownJobError = error;
}
assert(unknownJobError instanceof ApiError, 'Unknown job did not return ApiError');
assert(unknownJobError.status === 404 && unknownJobError.code === 'NOT_FOUND',
  'Unknown job did not return 404 NOT_FOUND');
assert(unknownJob.mode === 'live', 'Unknown job response lost live mode');

const invalidTokenApi = new ArenaApi(apiUrl);
invalidTokenApi.setToken('codex-dashboard-client-check-invalid-token');
let invalidTokenError;
try {
  await invalidTokenApi.get(matchPath);
} catch (error) {
  invalidTokenError = error;
}
assert(invalidTokenError instanceof ApiError, 'Invalid token did not return ApiError');
assert(invalidTokenError.status === 401 && invalidTokenError.code === 'UNAUTHORIZED',
  'Invalid token did not return 401 UNAUTHORIZED');
assert(invalidTokenApi.mode === 'live', '401 response lost live mode');

const artifactChecks = [];
if (match.phase === 'complete' && match.outcome) {
  for (const [name, id] of [
    ['evidence', match.outcome.evidence_artifact_id],
    ['patch', match.outcome.patch_artifact_id],
  ]) {
    if (!id) continue;
    const artifact = await api.artifact(id);
    assert(artifact.type === 'application/json' || artifact.type === 'text/plain',
      `${name} artifact type is not safe text/JSON`);
    artifactChecks.push({ name, type: artifact.type });
  }
}

console.log(JSON.stringify({
  label: 'read-only dashboard client API check; no browser interaction/native agents',
  status: 'passed',
  api_version: health.api_version,
  contract_hash: CONTRACT_HASH,
  mode: api.mode,
  match_id: match.match_id,
  phase: match.phase,
  provider_labels: { a: labels.a, b: labels.b },
  event_count: events.events.length,
  next_after: events.next_after,
  checks: [
    'health_version_and_mode',
    'match_provider_labels',
    'events',
    'unknown_job_404',
    'invalid_token_match_401',
  ],
  artifacts: artifactChecks.length ? artifactChecks : 'skipped_no_artifacts',
}));
