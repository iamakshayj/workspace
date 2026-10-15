import { fireEvent, render, screen } from '@testing-library/react';
import HomeDashboard, { todayRange } from './HomeDashboard';
import { getCalendarEvents } from './calendarService';
import { getCommunicationOverview } from './communicationService';
import { getWorkOverview } from './workService';
import { getWorkIntelligenceBriefing } from './intelligenceService';

jest.mock('./calendarService', () => ({ getCalendarEvents: jest.fn() }));
jest.mock('./communicationService', () => ({ getCommunicationOverview: jest.fn() }));
jest.mock('./workService', () => ({ getWorkOverview: jest.fn() }));
jest.mock('./intelligenceService', () => ({ getWorkIntelligenceBriefing: jest.fn() }));

const user = {
  id: 'user-1', display_name: 'Avery Builder', entity_name: 'Northwind Operations',
};

beforeEach(() => {
  const now = new Date();
  const startsAt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 0).toISOString();
  const endsAt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 30).toISOString();
  getWorkOverview.mockResolvedValue({
    items: [{
      id: 'work-1', key: 'NW-14', summary: 'Review approval controls', item_type: 'story',
      status: 'in_progress', priority: 'high', assignee: { id: user.id }, due_date: null,
      sprint_id: 'sprint-1', updated_at: now.toISOString(),
    }, {
      id: 'work-2', key: 'NW-13', summary: 'Document current state', item_type: 'task',
      status: 'done', priority: 'medium', assignee: { id: 'user-2' }, due_date: null,
      sprint_id: 'sprint-1', updated_at: now.toISOString(),
    }],
    sprints: [{ id: 'sprint-1', name: 'Operations Sprint 8', goal: 'Reduce approval cycle time', status: 'active' }],
  });
  getCalendarEvents.mockResolvedValue([{
    id: 'event-1', title: 'Delivery sync', event_type: 'meeting', status: 'confirmed',
    starts_at: startsAt, ends_at: endsAt, all_day: false, attendees: [{}, {}],
  }]);
  getCommunicationOverview.mockResolvedValue({ notifications: [{
    id: 'notification-1', title: 'Taylor mentioned you', body: 'Please review the process note.',
    read: false, project_id: 'project-1', created_at: now.toISOString(),
    actor: { display_name: 'Taylor Morgan', color: '#258A71' },
  }] });
  getWorkIntelligenceBriefing.mockResolvedValue({
    summary: { overdue_assigned: 0, meetings_today: 1, unread_notifications: 1, at_risk_projects: 1 },
    project_health: [{ project_id: 'project-1', health: 'at_risk', score: 64 }],
    recommendations: [{
      id: 'meeting:1', kind: 'meeting_preparation', severity: 'low',
      title: 'Prepare an agenda for Delivery sync', explanation: 'The meeting has no agenda.',
      confidence: 0.9, freshness: { state: 'fresh' }, sources: [{ id: 'event-1' }],
      proposed_action: { label: 'Prepare meeting', url: '/calendar?event=event-1' },
    }],
  });
});

afterEach(() => jest.clearAllMocks());

test('shows only the four detailed dashboard previews', async () => {
  const onNavigate = jest.fn();
  const { container } = render(<HomeDashboard user={user} onNavigate={onNavigate}
    recentProjects={[{
      id: 'project-1', title: 'Request approvals', node_count: 12, plan_progress: 50,
      task_count: 2, deliverable_count: 1, approval_status: 'approved', updated_at: new Date().toISOString(),
    }]} projectTotalCount={7} projectsState="ready" />);

  expect(await screen.findByText('Review approval controls')).toBeInTheDocument();
  expect(screen.getByText('Delivery sync')).toBeInTheDocument();
  expect(screen.getByText('Taylor mentioned you')).toBeInTheDocument();
  expect(screen.getByText('Request approvals')).toBeInTheDocument();
  expect(screen.getByText('64/100')).toBeInTheDocument();
  expect(screen.getByText(/at risk/)).toBeInTheDocument();
  expect(container.querySelectorAll('.home-panel')).toHaveLength(4);
  expect(screen.queryByLabelText('Workspace summary')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Open work board' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Open calendar' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Create workflow' })).not.toBeInTheDocument();

  fireEvent.click(screen.getByText('Daily briefing'));
  expect(screen.getByText('Prepare an agenda for Delivery sync')).toBeInTheDocument();
  expect(screen.getByText(/90% confidence/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Prepare an agenda for Delivery sync').closest('button'));
  expect(onNavigate).toHaveBeenCalledWith('/calendar?event=event-1');

  fireEvent.click(screen.getByText('Review approval controls').closest('button'));
  expect(onNavigate).toHaveBeenCalledWith('/work?item=work-1');
  fireEvent.click(screen.getByRole('button', { name: /^all workflows/i }));
  expect(onNavigate).toHaveBeenCalledWith('/workflows');
});

test('builds a local calendar-day range', () => {
  const range = todayRange(new Date(2026, 7, 29, 15, 30));
  const start = new Date(range.startsAfter);
  const end = new Date(range.startsBefore);

  expect(start.getHours()).toBe(0);
  expect(end.getHours()).toBe(0);
  expect(end.getTime() - start.getTime()).toBe(24 * 60 * 60 * 1000);
});
