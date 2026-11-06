import type { Mode, Source } from './types';

export const CONTRACT_VERSION = '1.1';
export const CONTRACT_HASH = 'c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f';
const JOURNAL_KEY = 'coding-arena.operations.1.1';
export interface Operation {
  request_id: string;
  base_url: string;
  origin: string;
  mode: Mode;
  path: string;
  body: Record<string, unknown>;
  created_at: string;
  state: 'pending' | 'completed' | 'ambiguous' | 'rejected';
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 0,
    public requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object')
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(',')}}`;
  return JSON.stringify(value);
}
export function readJournal(): Operation[] {
  const raw = localStorage.getItem(JOURNAL_KEY);
  if (!raw) return [];
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed))
    throw new Error('Operation journal is invalid. Export or recover it before sending changes.');
  return parsed as Operation[];
}
function writeOperation(operation: Operation) {
  const entries = readJournal();
  const index = entries.findIndex(
    (item) => item.base_url === operation.base_url && item.request_id === operation.request_id,
  );
  if (index >= 0) entries[index] = operation;
  else entries.push(operation);
  // Persist before dispatch. A storage failure must prevent sending the POST.
  localStorage.setItem(JOURNAL_KEY, JSON.stringify(entries));
}
function operationSource(mode: Mode): Source {
  return {
    kind: mode === 'fixture' ? 'fixture' : 'operator_recorded',
    room_id: null,
    message_id: null,
    note:
      mode === 'fixture'
        ? 'Synthetic fixture replay action; no live human or agent discovery is implied.'
        : 'Explicit action recorded in the local operator dashboard; Switch origin is not verified.',
  };
}

export class ArenaApi {
  private token = '';
  public mode: Mode | null = null;
  constructor(
    public readonly baseUrl = '/api/v1',
    private timeoutMs = 10000,
  ) {}
  setToken(token: string) {
    this.token = token.trim();
  }
  private async send<T>(
    method: 'GET' | 'POST',
    path: string,
    body?: Record<string, unknown>,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl.replace(/\/$/, '')}${path}`, {
        method,
        signal: controller.signal,
        cache: 'no-store',
        headers: {
          ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        ...(body ? { body: canonical(body) } : {}),
      });
      const mode = response.headers.get('X-Arena-Mode');
      if (mode !== 'live' && mode !== 'fixture') {
        this.mode = null;
        throw new ApiError(
          'PROTOCOL_ERROR',
          'Response mode is unknown. X-Arena-Mode is missing or invalid.',
          response.status,
        );
      }
      this.mode = mode;
      const contentType = response.headers.get('content-type') || '';
      const data: unknown = contentType.includes('application/json')
        ? await response.json()
        : await response.text();
      if (data && typeof data === 'object' && 'mode' in data && data.mode !== mode) {
        this.mode = null;
        throw new ApiError(
          'PROTOCOL_ERROR',
          'Response body and mode header disagree.',
          response.status,
        );
      }
      if (!response.ok) {
        const error =
          typeof data === 'object' && data !== null && 'error' in data
            ? (data.error as { code?: string; message?: string })
            : {};
        throw new ApiError(
          error.code || 'HTTP_ERROR',
          error.message || `Request failed (${response.status}).`,
          response.status,
          body?.request_id as string | undefined,
        );
      }
      if (
        path === '/health' &&
        (!data ||
          typeof data !== 'object' ||
          !('api_version' in data) ||
          data.api_version !== CONTRACT_VERSION)
      ) {
        this.mode = null;
        throw new ApiError(
          'PROTOCOL_ERROR',
          `This dashboard requires interface ${CONTRACT_VERSION}.`,
          response.status,
        );
      }
      return data as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        body ? 'AMBIGUOUS_REQUEST' : 'CONNECTION_ERROR',
        body
          ? 'No confirmed response. Retry the saved operation with the same request ID.'
          : 'Cannot reach the API. Check the server and connection.',
        0,
        body?.request_id as string | undefined,
      );
    } finally {
      clearTimeout(timer);
    }
  }
  get<T>(path: string) {
    return this.send<T>('GET', path);
  }
  async mutate<T>(
    path: string,
    payload: Record<string, unknown>,
    requestId: string = crypto.randomUUID(),
  ): Promise<T> {
    if (!this.token)
      throw new ApiError('UNAUTHORIZED', 'Enter an operator token before recording a decision.');
    if (!this.mode)
      throw new ApiError(
        'PROTOCOL_ERROR',
        'Confirm the API response mode before recording an operation.',
      );
    const origin = new URL(this.baseUrl, window.location.href).href;
    const body = { ...payload, source: operationSource(this.mode), request_id: requestId };
    if (
      canonical(body).includes(this.token) ||
      canonical(body).includes(JSON.stringify(this.token).slice(1, -1))
    )
      throw new ApiError(
        'INVALID_INPUT',
        'Do not include the operator credential in a reason, label, or saved request body.',
      );
    let existing: Operation | undefined;
    try {
      existing = readJournal().find(
        (item) => item.base_url === this.baseUrl && item.request_id === requestId,
      );
    } catch {
      throw new ApiError(
        'JOURNAL_ERROR',
        'Cannot read the operation journal. No request was sent.',
      );
    }
    if (
      existing &&
      (existing.path !== path ||
        existing.origin !== origin ||
        existing.mode !== this.mode ||
        canonical(existing.body) !== canonical(body))
    )
      throw new ApiError(
        'IDEMPOTENCY_CONFLICT',
        'This saved request ID belongs to a different operation.',
        409,
        requestId,
      );
    const operation: Operation = existing || {
      request_id: requestId,
      base_url: this.baseUrl,
      origin,
      mode: this.mode,
      path,
      body,
      created_at: new Date().toISOString(),
      state: 'pending',
    };
    try {
      writeOperation({ ...operation, state: 'pending' });
    } catch {
      throw new ApiError(
        'JOURNAL_ERROR',
        'Cannot persist the operation journal. No request was sent.',
        0,
        requestId,
      );
    }
    try {
      const data = await this.send<T>('POST', path, body);
      writeOperation({ ...operation, state: 'completed' });
      return data;
    } catch (error) {
      const ambiguous =
        !(error instanceof ApiError) ||
        error.status === 0 ||
        error.code === 'PROTOCOL_ERROR' ||
        error.status >= 500;
      try {
        writeOperation({ ...operation, state: ambiguous ? 'ambiguous' : 'rejected' });
      } catch {
        /* The pre-dispatch entry remains available for exact retry. */
      }
      throw error;
    }
  }
  retry<T>(operation: Operation): Promise<T> {
    if (
      !this.mode ||
      operation.mode !== this.mode ||
      operation.origin !== new URL(this.baseUrl, window.location.href).href ||
      operation.base_url !== this.baseUrl
    )
      throw new ApiError(
        'INVALID_INPUT',
        'Reconnect to the same saved API origin and fixture/live mode before retrying this operation.',
      );
    const { source: _source, request_id: _requestId, ...payload } = operation.body;
    return this.mutate<T>(operation.path, payload, operation.request_id);
  }
  async artifact(id: string): Promise<{ text: string; type: string }> {
    const text = await this.get<unknown>(`/artifacts/${encodeURIComponent(id)}`);
    return {
      text: typeof text === 'string' ? text : JSON.stringify(text, null, 2),
      type: typeof text === 'string' ? 'text/plain' : 'application/json',
    };
  }
}
