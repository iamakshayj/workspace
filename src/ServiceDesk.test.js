import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ServiceDesk from './ServiceDesk';
import * as desk from './serviceDeskService';
import * as entity from './entityService';

jest.mock('./serviceDeskService');
jest.mock('./entityService');
jest.mock('./WorkspaceTopNav', () => ({ actions }) => <nav>{actions}</nav>);

const ticket = {
  id: 'ticket-1', title: 'Checkout is unavailable', description: 'Customers receive a 500 response',
  ticket_type: 'incident', status: 'open', severity: 'critical', priority: 'urgent', service: 'checkout',
  assignee: { id: 'user-2', display_name: 'Jordan Lee' }, response_due_at: '2026-10-15T12:00:00Z',
  resolution_due_at: '2026-10-15T16:00:00Z', response_breached: false, resolution_breached: false,
};

beforeEach(() => {
  desk.getServiceTickets.mockResolvedValue({ items: [ticket], summary: { total: 1, open: 1, sla_breached: 0 } });
  desk.getServiceTicketComments.mockResolvedValue([{ id: 'comment-1', body: 'Investigating logs', author: { display_name: 'Jordan Lee' }, created_at: '2026-10-15T11:00:00Z' }]);
  desk.getOnCallSchedules.mockResolvedValue([{ id: 'schedule-1', active: true }]);
  desk.getGuestGrants.mockResolvedValue([]);
  entity.getWorkspaceTeam.mockResolvedValue({ workspace_members: [{ id: 'user-2', display_name: 'Jordan Lee', email: 'jordan@example.com' }] });
});

afterEach(() => jest.clearAllMocks());

test('loads the service queue and opens ticket activity', async () => {
  render(<ServiceDesk user={{ id: 'admin-1', role: 'admin' }} onNavigate={jest.fn()} />);
  expect(await screen.findByText('Checkout is unavailable')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Checkout is unavailable/ }));
  expect(await screen.findByText('Investigating logs')).toBeInTheDocument();
  expect(screen.getByText('External collaboration')).toBeInTheDocument();
  expect(entity.getWorkspaceTeam).toHaveBeenCalledTimes(1);
});

test('creates a request from the service page', async () => {
  desk.createServiceTicket.mockResolvedValue({ ...ticket, id: 'ticket-2', title: 'New access' });
  render(<ServiceDesk user={{ id: 'admin-1', role: 'admin' }} onNavigate={jest.fn()} />);
  await screen.findByText('Checkout is unavailable');
  fireEvent.click(screen.getByRole('button', { name: '+ New request' }));
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'New access' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create request' }));
  await waitFor(() => expect(desk.createServiceTicket).toHaveBeenCalledWith(expect.objectContaining({ title: 'New access' })));
});
