import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import CalendarManagement from './CalendarManagement';
import {
  cancelCalendarEvent,
  createCalendarEvent,
  getCalendarAvailability,
  getCalendarEvent,
  getCalendarEvents,
  respondToCalendarEvent,
  setCalendarEventReminder,
} from './calendarService';
import { getCommunicationOverview } from './communicationService';

jest.mock('./AccountControls', () => () => <div>Account</div>);
jest.mock('./communicationService', () => ({
  CommunicationClient: class { connect() {} disconnect() {} },
  getCommunicationOverview: jest.fn(),
}));
jest.mock('./calendarService', () => ({
  cancelCalendarEvent: jest.fn(),
  createCalendarEvent: jest.fn(),
  getCalendarAvailability: jest.fn(),
  getCalendarEvent: jest.fn(),
  getCalendarEvents: jest.fn(),
  respondToCalendarEvent: jest.fn(),
  setCalendarEventReminder: jest.fn(),
  updateCalendarEvent: jest.fn(),
}));

const user = {
  id: 'user-1', display_name: 'Current User', email: 'current@example.com',
  role: 'admin', handle: 'current', color: '#555', entity_name: 'Northwind',
};
const contact = {
  id: 'user-2', display_name: 'Taylor Morgan', email: 'taylor@example.com',
  role: 'basic', handle: 'taylor', color: '#258A71',
};

function meeting(overrides = {}) {
  const start = new Date();
  start.setHours(14, 0, 0, 0);
  const end = new Date(start.getTime() + 30 * 60 * 1000);
  return {
    id: 'meeting-1', title: 'Design review', description: 'Review the proposal.',
    event_type: 'meeting', starts_at: start.toISOString(), ends_at: end.toISOString(),
    timezone: 'America/Chicago', all_day: false, location: '', meeting_url: '',
    status: 'scheduled', organizer: contact,
    attendees: [
      { user: contact, response: 'accepted', is_organizer: true },
      { user, response: 'pending', is_organizer: false },
    ],
    external_attendees: [],
    my_response: 'pending', reminder_minutes: 15, can_manage: false,
    created_at: start.toISOString(), updated_at: start.toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  window.history.replaceState({}, '', '/calendar');
  getCalendarEvents.mockResolvedValue([]);
  getCommunicationOverview.mockResolvedValue({ communication_contacts: [{ user: contact }] });
});

test('shows the selected-day agenda only after a calendar day is clicked', async () => {
  const { container } = render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'My calendar' })).toBeInTheDocument();
  const primaryNavigation = screen.getByRole('navigation', { name: 'Primary navigation' });
  expect(primaryNavigation).toBeInTheDocument();
  expect(within(primaryNavigation).getByRole('button', { name: 'Calendar' })).toHaveAttribute('aria-current', 'page');
  expect(within(primaryNavigation).queryByRole('button', { name: /schedule|find a time/i })).not.toBeInTheDocument();
  expect(within(container.querySelector('.calendar-toolbar')).getByRole('button', { name: /schedule meeting/i })).toBeInTheDocument();
  expect(screen.queryByRole('complementary', { name: 'Selected day agenda' })).not.toBeInTheDocument();

  fireEvent.click(container.querySelector('.personal-calendar-grid button.today'));
  expect(screen.getByRole('complementary', { name: 'Selected day agenda' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Close selected day' }));
  expect(screen.queryByRole('complementary', { name: 'Selected day agenda' })).not.toBeInTheDocument();
});

test('switches between agenda, daily, weekly, and monthly calendar views', async () => {
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByLabelText('Monthly calendar')).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'Monthly' })).toHaveAttribute('aria-selected', 'true');

  fireEvent.click(screen.getByRole('tab', { name: 'Agenda' }));
  expect(screen.getByLabelText('Calendar agenda')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('tab', { name: 'Weekly' }));
  expect(screen.getByLabelText('Weekly calendar')).toBeInTheDocument();
  expect(screen.queryByLabelText('Monthly calendar')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('tab', { name: 'Daily' }));
  expect(screen.getByLabelText('Daily calendar')).toBeInTheDocument();
  expect(screen.queryByLabelText('Weekly calendar')).not.toBeInTheDocument();
});

test('creates a private personal calendar event', async () => {
  const created = meeting({
    id: 'personal-1', title: 'Focus time', event_type: 'personal', organizer: user,
    attendees: [{ user, response: 'accepted', is_organizer: true }],
    my_response: 'accepted', can_manage: true,
  });
  createCalendarEvent.mockResolvedValue(created);
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'My calendar' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /schedule meeting/i }));
  fireEvent.click(screen.getByRole('button', { name: /personal time/i }));
  expect(screen.getByRole('radio', { name: /personal/i })).toBeChecked();
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Focus time' } });
  fireEvent.change(screen.getByLabelText('Reminder'), { target: { value: '30' } });
  fireEvent.click(screen.getByRole('button', { name: /add to calendar/i }));

  await waitFor(() => expect(createCalendarEvent).toHaveBeenCalledWith(expect.objectContaining({
    title: 'Focus time', eventType: 'personal', attendeeIds: [], reminderMinutes: 30,
  })));
  expect(await screen.findByRole('heading', { name: 'Focus time' })).toBeInTheDocument();
});

test('prefills an assistant-created meeting with its attendee and exact time', async () => {
  window.history.replaceState({}, '', '/calendar?create=1&source=assistant&date=2026-10-10&time=08%3A00&duration=30&attendee=Taylor+Morgan&title=Call+with+Taylor+Morgan');
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'Schedule an event' })).toBeInTheDocument();
  expect(screen.getByLabelText('Title')).toHaveValue('Call with Taylor Morgan');
  expect(screen.getByLabelText('Date')).toHaveValue('2026-10-10');
  expect(screen.getByLabelText('Starts')).toHaveValue('08:00');
  expect(screen.getByLabelText('Ends')).toHaveValue('08:30');
  expect(screen.getByRole('combobox', { name: 'Meeting attendees' })).toHaveTextContent('1 selected');
  expect(screen.getByRole('button', { name: 'Send invitation' })).toBeEnabled();
});

test('creates an alarm-style recurring meeting schedule', async () => {
  const created = meeting({
    id: 'series-1', title: 'Delivery review', organizer: user, can_manage: true,
    attendees: [{ user, response: 'accepted', is_organizer: true }, { user: contact, response: 'pending', is_organizer: false }],
    series_id: 'series-group-1', recurrence_frequency: 'weekly', recurrence_interval: 1,
    recurrence_count: 10, recurrence_ends_at: dateKeyForTest(new Date(Date.now() + 63 * 86400000)), occurrence_index: 0,
  });
  createCalendarEvent.mockResolvedValue(created);
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'My calendar' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /schedule meeting/i }));
  fireEvent.click(screen.getByRole('button', { name: /set a time manually/i }));
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Delivery review' } });
  fireEvent.click(screen.getByRole('combobox', { name: /meeting attendees/i }));
  fireEvent.click(await screen.findByRole('option', { name: /Taylor Morgan/i }));
  fireEvent.change(screen.getByLabelText('Repeat'), { target: { value: 'weekly' } });

  expect(screen.getByText(/Every week on .* · 10 occurrences/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }));

  await waitFor(() => expect(createCalendarEvent).toHaveBeenCalledWith(expect.objectContaining({
    title: 'Delivery review', recurrenceFrequency: 'weekly', recurrenceInterval: 1,
    recurrenceCount: 10, recurrenceEndsAt: null,
  })));
  expect(await screen.findByText(/Occurrence 1 of 10/i)).toBeInTheDocument();
});

test('lets an organizer cancel this and future meetings in a recurring series', async () => {
  const event = meeting({
    organizer: user, can_manage: true, my_response: 'accepted',
    attendees: [{ user, response: 'accepted', is_organizer: true }],
    series_id: 'series-group-1', recurrence_frequency: 'weekly', recurrence_interval: 1,
    recurrence_count: 8, recurrence_ends_at: dateKeyForTest(new Date(Date.now() + 49 * 86400000)), occurrence_index: 2,
  });
  const cancelled = { ...event, status: 'cancelled' };
  window.history.replaceState({}, '', '/calendar?event=meeting-1');
  getCalendarEvent.mockResolvedValue(event);
  getCalendarEvents.mockResolvedValue([event]);
  cancelCalendarEvent.mockResolvedValue(cancelled);
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByText(/Occurrence 3 of 8/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel event' }));
  fireEvent.change(screen.getByLabelText('Cancel recurring meeting'), { target: { value: 'future' } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel', exact: true }));

  await waitFor(() => expect(cancelCalendarEvent).toHaveBeenCalledWith('meeting-1', 'future'));
});

test('invites an external meeting guest by email without granting workspace access', async () => {
  const created = meeting({
    organizer: user, can_manage: true, my_response: 'accepted',
    attendees: [{ user, response: 'accepted', is_organizer: true }],
    external_attendees: [{ email: 'client@example.net', response: 'pending', delivery_status: 'queued' }],
  });
  createCalendarEvent.mockResolvedValue(created);
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'My calendar' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /schedule meeting/i }));
  fireEvent.click(screen.getByRole('button', { name: /set a time manually/i }));
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Client review' } });
  fireEvent.change(screen.getByLabelText('Guest email'), { target: { value: 'Client@Example.net' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add guest' }));

  expect(screen.getByText('client@example.net')).toBeInTheDocument();
  expect(screen.getByText(/no workspace access/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }));

  await waitFor(() => expect(createCalendarEvent).toHaveBeenCalledWith(expect.objectContaining({
    title: 'Client review', attendeeIds: [], externalAttendeeEmails: ['client@example.net'],
  })));
  expect(await screen.findByText('External guest · Email invitation')).toBeInTheDocument();
});

test('opens a meeting invitation and records an attendee response', async () => {
  const event = meeting();
  const accepted = meeting({ my_response: 'accepted', attendees: [
    { user: contact, response: 'accepted', is_organizer: true },
    { user, response: 'accepted', is_organizer: false },
  ] });
  window.history.replaceState({}, '', '/calendar?event=meeting-1');
  getCalendarEvent.mockResolvedValue(event);
  getCalendarEvents.mockResolvedValue([event]);
  respondToCalendarEvent.mockResolvedValue(accepted);

  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'Design review' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '✓ Accept', exact: true }));
  await waitFor(() => expect(respondToCalendarEvent).toHaveBeenCalledWith('meeting-1', 'accepted'));
  await waitFor(() => expect(screen.getByRole('button', { name: '✓ Accept', exact: true })).toHaveClass('accepted'));
});

test('lets each attendee change their own event reminder', async () => {
  const event = meeting();
  const updated = meeting({ reminder_minutes: 60 });
  window.history.replaceState({}, '', '/calendar?event=meeting-1');
  getCalendarEvent.mockResolvedValue(event);
  getCalendarEvents.mockResolvedValue([event]);
  setCalendarEventReminder.mockResolvedValue(updated);

  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'Design review' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Event reminder'), { target: { value: '60' } });
  await waitFor(() => expect(setCalendarEventReminder).toHaveBeenCalledWith('meeting-1', 60));
  await waitFor(() => expect(screen.getByLabelText('Event reminder')).toHaveValue('60'));
  expect(screen.getByText(/1 hour before · Only affects you/i)).toBeInTheDocument();
});

test('opens an in-app call lobby from a scheduled meeting', async () => {
  const event = meeting({ my_response: 'accepted' });
  window.history.replaceState({}, '', '/calendar?event=meeting-1');
  getCalendarEvent.mockResolvedValue(event);
  getCalendarEvents.mockResolvedValue([event]);

  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'Design review' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Join video call' }));
  expect(screen.getByRole('dialog', { name: /Design review call/i })).toBeInTheDocument();
  expect(screen.getByText('Scheduled team meeting')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Join now' })).toBeEnabled();
});

test('compares private free-busy calendars and transfers a common slot into a meeting', async () => {
  const startsAt = '2026-09-02T15:00:00.000Z';
  const endsAt = '2026-09-02T15:30:00.000Z';
  getCalendarAvailability.mockResolvedValue({
    timezone: 'America/Chicago', range_start: '2026-09-02T05:00:00Z', range_end: '2026-09-07T05:00:00Z',
    users: [{ user, busy: [] }, { user: contact, busy: [{ starts_at: '2026-09-02T14:00:00Z', ends_at: startsAt }] }],
    suggestions: [{
      starts_at: startsAt, ends_at: endsAt,
      available_user_ids: [user.id, contact.id], unavailable_user_ids: [],
      attendance_count: 2, total_count: 2, score: 100,
    }],
  });
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'My calendar' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /schedule meeting/i }));
  expect(screen.getByRole('dialog', { name: /schedule a meeting/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('combobox', { name: /meeting availability participants/i }));
  fireEvent.change(screen.getByRole('searchbox', { name: /search meeting availability participants/i }), {
    target: { value: 'taylor@example.com' },
  });
  fireEvent.click(await screen.findByRole('option', { name: /Taylor Morgan/i }));
  fireEvent.click(screen.getByRole('button', { name: /suggest open times for 2/i }));

  expect(await screen.findByText('Everyone is open')).toBeInTheDocument();
  expect(getCalendarAvailability).toHaveBeenCalledWith(expect.objectContaining({
    userIds: [user.id, contact.id], durationMinutes: 30,
    workdayStartsAt: '09:00', workdayEndsAt: '17:00', maxSuggestions: 16,
  }));
  expect(screen.getAllByLabelText(/Taylor Morgan, .*busy/i)).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: /schedule this time/i }));

  expect(screen.getByRole('heading', { name: 'Schedule an event' })).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: /meeting attendees/i })).toHaveTextContent('1 selected');
  expect(screen.getByLabelText('Date')).toHaveValue(dateKeyForTest(startsAt));
});

test('keeps duration and end time synchronized when scheduling manually', async () => {
  render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'My calendar' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /schedule meeting/i }));
  fireEvent.change(screen.getByLabelText('Meeting duration'), { target: { value: '60' } });
  fireEvent.click(screen.getByRole('button', { name: /set a time manually/i }));

  expect(screen.getByLabelText('Event duration')).toHaveValue('60');
  expect(screen.getByLabelText('Starts')).toHaveValue('09:00');
  expect(screen.getByLabelText('Ends')).toHaveValue('10:00');
  fireEvent.change(screen.getByLabelText('Starts'), { target: { value: '10:15' } });
  expect(screen.getByLabelText('Ends')).toHaveValue('11:15');
  fireEvent.change(screen.getByLabelText('Event duration'), { target: { value: '30' } });
  expect(screen.getByLabelText('Ends')).toHaveValue('10:45');
});

test('changes suggested open times with the selected comparison day', async () => {
  const first = new Date();
  first.setHours(10, 0, 0, 0);
  const second = new Date(first);
  second.setDate(second.getDate() + 1);
  second.setHours(11, 0, 0, 0);
  const suggestion = (start) => ({
    starts_at: start.toISOString(), ends_at: new Date(start.getTime() + 30 * 60000).toISOString(),
    available_user_ids: [user.id, contact.id], unavailable_user_ids: [], attendance_count: 2, total_count: 2, score: 100,
  });
  getCalendarAvailability.mockResolvedValue({
    timezone: 'America/Chicago', range_start: first.toISOString(), range_end: second.toISOString(),
    users: [{ user, busy: [] }, { user: contact, busy: [] }], suggestions: [suggestion(first), suggestion(second)],
  });
  const { container } = render(<CalendarManagement user={user} onNavigate={jest.fn()} />);

  await screen.findByRole('heading', { name: 'My calendar' });
  fireEvent.click(screen.getByRole('button', { name: /schedule meeting/i }));
  fireEvent.click(screen.getByRole('combobox', { name: /meeting availability participants/i }));
  fireEvent.click(await screen.findByRole('option', { name: /Taylor Morgan/i }));
  fireEvent.click(screen.getByRole('button', { name: /suggest open times for 2/i }));
  await screen.findByText('Everyone is open');

  const suggestions = container.querySelector('.availability-suggestions');
  expect(suggestions).toHaveTextContent(/10:00/);
  expect(suggestions).not.toHaveTextContent(/11:00/);
  fireEvent.click(container.querySelectorAll('.availability-timeline nav button')[1]);
  expect(suggestions).toHaveTextContent(/11:00/);
  expect(suggestions).not.toHaveTextContent(/10:00/);
});

function dateKeyForTest(value) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
