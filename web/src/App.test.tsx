import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import { ArenaApi } from './api';
import { startFixture } from './test/fixture';

let fixture: Awaited<ReturnType<typeof startFixture>>;
beforeAll(async () => {
  fixture = await startFixture();
});
afterAll(() => fixture.close());
beforeEach(() => {
  localStorage.clear();
});
async function connect(id: string) {
  const user = userEvent.setup();
  render(<App api={new ArenaApi(fixture.baseUrl)} initialMatch={id} pollInterval={60000} />);
  await user.type(screen.getByLabelText('Operator token'), 'fixture-operator');
  await user.click(screen.getByRole('button', { name: 'Connect / refresh' }));
  await screen.findByRole('heading', { name: 'Contender A' });
  await user.type(
    screen.getByLabelText('Decision / action reason'),
    'The recorded evidence supports this explicit operator decision.',
  );
  return user;
}

describe('dashboard decisions through the actual HTTP API client', () => {
  it('keeps pending review separate from final selection and exposes executable evidence', async () => {
    await connect('fixture-pending');
    expect(screen.queryByRole('button', { name: 'Select contender A' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept requirement violation' })).toBeEnabled();
    expect(screen.getByText(/^FIXTURE REPLAY$/)).toBeInTheDocument();
    expect(screen.getAllByText(/Unknown provider/)).toHaveLength(2);
    expect(screen.getByText(/Target failed twice: yes/)).toBeInTheDocument();
  });
  it('selects a current eligible snapshot and shows server-issued outcome downloads', async () => {
    const user = await connect('fixture-decision');
    expect(screen.getByRole('button', { name: 'Select contender A' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Select contender A' }));
    await screen.findByRole('heading', { name: 'Contender A selected' });
    expect(screen.getByRole('button', { name: 'Open selected patch ↗' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Select contender B' })).not.toBeInTheDocument();
  });
  it('keeps both ineligible submissions disabled and allows an honest neither outcome', async () => {
    const user = await connect('fixture-neither');
    expect(screen.getByRole('button', { name: 'Select contender A' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Select contender B' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Select neither' }));
    await screen.findByRole('heading', { name: 'Neither selected' });
    expect(screen.queryByRole('button', { name: 'Open selected patch ↗' })).not.toBeInTheDocument();
  });
  it('refreshes after a real stale-selection 409, preserves the error, and disables stale code', async () => {
    const user = await connect('fixture-stale');
    await user.click(screen.getByRole('button', { name: 'Select contender A' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Select contender A' })).toBeDisabled(),
    );
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('STALE_SNAPSHOT'));
    expect(
      screen.queryByText('Action recorded. Refreshing measured evidence.'),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText('The suite changed. Full verification must run again.'),
    ).toHaveLength(2);
  });
  it('shows infrastructure failure as unknown eligibility and distinguishes job types', async () => {
    await connect('fixture-error');
    expect(screen.getByRole('button', { name: 'Select contender A' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Select contender B' })).toBeDisabled();
    expect(screen.getAllByText('Runner error. Eligibility remains unknown.')).toHaveLength(2);
    const comparison = screen.getByRole('region', { name: 'Contender comparison' });
    expect(within(comparison).getAllByText('unknown')).toHaveLength(2);
  });
});
