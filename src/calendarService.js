import { graphqlRequest } from './communicationService';

const USER_FIELDS = `id display_name: displayName email role handle color`;
const EVENT_FIELDS = `
  id title description event_type: eventType starts_at: startsAt ends_at: endsAt
  timezone all_day: allDay location meeting_url: meetingUrl status
  series_id: seriesId recurrence_frequency: recurrenceFrequency
  recurrence_interval: recurrenceInterval recurrence_ends_at: recurrenceEndsAt
  recurrence_count: recurrenceCount occurrence_index: occurrenceIndex
  my_response: myResponse reminder_minutes: reminderMinutes can_manage: canManage
  created_at: createdAt updated_at: updatedAt
  organizer { ${USER_FIELDS} }
  attendees { response is_organizer: isOrganizer user { ${USER_FIELDS} } }
  external_attendees: externalAttendees { email response delivery_status: deliveryStatus }
`;

export function getCalendarEvents(startsAfter, startsBefore) {
  return graphqlRequest(`query CalendarEvents($startsAfter: DateTime!, $startsBefore: DateTime!) {
    calendar_events: calendarEvents(startsAfter: $startsAfter, startsBefore: $startsBefore) { ${EVENT_FIELDS} }
  }`, { startsAfter, startsBefore }).then((data) => data.calendar_events);
}

export function getCalendarEvent(eventId) {
  return graphqlRequest(`query CalendarEvent($eventId: ID!) {
    calendar_event: calendarEvent(eventId: $eventId) { ${EVENT_FIELDS} }
  }`, { eventId }).then((data) => data.calendar_event);
}

export function getCalendarAvailability(input) {
  return graphqlRequest(`query CalendarAvailability($input: CalendarAvailabilityInput!) {
    calendar_availability: calendarAvailability(input: $input) {
      timezone range_start: rangeStart range_end: rangeEnd
      users { user { ${USER_FIELDS} } busy { starts_at: startsAt ends_at: endsAt } }
      suggestions {
        starts_at: startsAt ends_at: endsAt
        available_user_ids: availableUserIds unavailable_user_ids: unavailableUserIds
        attendance_count: attendanceCount total_count: totalCount score
      }
    }
  }`, { input }).then((data) => data.calendar_availability);
}

export function createCalendarEvent(input) {
  return graphqlRequest(`mutation CreateCalendarEvent($input: CalendarEventInput!) {
    createCalendarEvent(input: $input) { ${EVENT_FIELDS} }
  }`, { input }).then((data) => data.createCalendarEvent);
}

export function updateCalendarEvent(eventId, input) {
  return graphqlRequest(`mutation UpdateCalendarEvent($eventId: ID!, $input: CalendarEventInput!) {
    updateCalendarEvent(eventId: $eventId, input: $input) { ${EVENT_FIELDS} }
  }`, { eventId, input }).then((data) => data.updateCalendarEvent);
}

export function respondToCalendarEvent(eventId, response) {
  return graphqlRequest(`mutation RespondToCalendarEvent($eventId: ID!, $response: String!) {
    respondToCalendarEvent(eventId: $eventId, response: $response) { ${EVENT_FIELDS} }
  }`, { eventId, response }).then((data) => data.respondToCalendarEvent);
}

export function setCalendarEventReminder(eventId, reminderMinutes) {
  return graphqlRequest(`mutation SetCalendarEventReminder($eventId: ID!, $reminderMinutes: Int) {
    setCalendarEventReminder(eventId: $eventId, reminderMinutes: $reminderMinutes) { ${EVENT_FIELDS} }
  }`, { eventId, reminderMinutes }).then((data) => data.setCalendarEventReminder);
}

export function cancelCalendarEvent(eventId, scope = 'event') {
  return graphqlRequest(`mutation CancelCalendarEvent($eventId: ID!, $scope: String!) {
    cancelCalendarEvent(eventId: $eventId, scope: $scope) { ${EVENT_FIELDS} }
  }`, { eventId, scope }).then((data) => data.cancelCalendarEvent);
}
