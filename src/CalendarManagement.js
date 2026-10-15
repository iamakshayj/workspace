import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import WorkspaceTopNav from './WorkspaceTopNav';
import { CommunicationClient, getCommunicationOverview } from './communicationService';
import VideoCallPanel from './VideoCallPanel';
import { UserMultiSelect } from './UserPicker';
import MeetingScheduler from './MeetingScheduler';
import {
  cancelCalendarEvent,
  createCalendarEvent,
  getCalendarEvent,
  getCalendarEvents,
  respondToCalendarEvent,
  setCalendarEventReminder,
  updateCalendarEvent,
} from './calendarService';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const REMINDER_OPTIONS = [
  ['', 'No reminder'], [0, 'At start time'], [5, '5 minutes before'],
  [10, '10 minutes before'], [15, '15 minutes before'], [30, '30 minutes before'],
  [60, '1 hour before'], [120, '2 hours before'], [1440, '1 day before'],
];
const REPEAT_OPTIONS = [
  ['none', 'Does not repeat'], ['daily', 'Every day'], ['weekdays', 'Every weekday'],
  ['weekly', 'Every week'], ['monthly', 'Every month'], ['custom', 'Custom…'],
];
const EVENT_DURATIONS = [15, 30, 45, 60, 90, 120];
const CALENDAR_VIEWS = [
  ['day', 'Daily', 'One selected day with its scheduled events.'],
  ['week', 'Weekly', 'Seven days side by side for short-term planning.'],
  ['month', 'Monthly', 'The month at a glance. Click a day for its details.'],
  ['agenda', 'Agenda', 'A chronological list of every event in this month.'],
];

function reminderLabel(value) {
  return REMINDER_OPTIONS.find(([minutes]) => String(minutes) === String(value ?? ''))?.[1] || 'No reminder';
}

function futureDateKey(value, days) {
  const result = dateFromKey(value);
  result.setDate(result.getDate() + days);
  return dateKey(result);
}

function repeatFrequency(form) {
  return form.repeat === 'custom' ? form.repeatFrequency : form.repeat;
}

function repeatSummary(value) {
  const frequency = value.recurrence_frequency || repeatFrequency(value);
  if (!frequency || frequency === 'none') return 'Does not repeat';
  const interval = Number(value.recurrence_interval ?? value.repeatInterval ?? 1);
  const startsAt = value.starts_at ? new Date(value.starts_at) : dateFromKey(value.date);
  const weekday = new Intl.DateTimeFormat(undefined, { weekday: 'long' }).format(startsAt);
  const descriptions = {
    daily: interval === 1 ? 'Every day' : `Every ${interval} days`,
    weekdays: interval === 1 ? 'Every weekday' : `Every ${interval} weekdays`,
    weekly: interval === 1 ? `Every week on ${weekday}` : `Every ${interval} weeks on ${weekday}`,
    monthly: interval === 1 ? `Every month on day ${startsAt.getDate()}` : `Every ${interval} months on day ${startsAt.getDate()}`,
  };
  const count = value.recurrence_count ?? (value.repeatEnds === 'count' ? Number(value.repeatCount) : null);
  const endsAt = value.recurrence_ends_at || (value.repeatEnds === 'date' ? value.repeatUntil : null);
  const formattedEnd = endsAt
    ? formatDate(dateFromKey(endsAt), { month: 'short', day: 'numeric', year: 'numeric' }) : '';
  const ending = value.series_id && count && endsAt
    ? `${count} occurrences · ends ${formattedEnd}`
    : count
    ? `${count} occurrences`
    : endsAt ? `until ${formattedEnd}` : '';
  return `${descriptions[frequency] || 'Repeats'}${ending ? ` · ${ending}` : ''}`;
}

function dateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dateFromKey(value) {
  return new Date(`${value}T12:00:00`);
}

function formatDate(value, options = { month: 'short', day: 'numeric' }) {
  return new Intl.DateTimeFormat(undefined, options).format(new Date(value));
}

function formatTime(value, allDay = false) {
  if (allDay) return 'All day';
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function inviteeCount(event) {
  return Math.max(0, (event.attendees?.length || 0) - 1) + (event.external_attendees?.length || 0);
}

function CalendarAvatar({ user }) {
  return <span className="calendar-avatar" style={{ '--avatar-color': user.color }} title={user.display_name}>{initials(user.display_name)}</span>;
}

function monthRange(month) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const startsAt = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay());
  const endsAt = new Date(startsAt.getFullYear(), startsAt.getMonth(), startsAt.getDate() + 42);
  return { startsAt, endsAt };
}

function startOfWeek(value) {
  const date = new Date(value);
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() - date.getDay());
}

function initialTimes(selectedDate) {
  const today = dateKey(new Date());
  if (selectedDate !== today) return { startTime: '09:00', endTime: '09:30' };
  const start = new Date();
  start.setMinutes(Math.ceil(start.getMinutes() / 30) * 30, 0, 0);
  const end = new Date(start.getTime() + 30 * 60 * 1000);
  const time = (value) => `${String(value.getHours()).padStart(2, '0')}:${String(value.getMinutes()).padStart(2, '0')}`;
  return { startTime: time(start), endTime: time(end) };
}

function minutesBetween(startTime, endTime) {
  const [startHour, startMinute] = startTime.split(':').map(Number);
  const [endHour, endMinute] = endTime.split(':').map(Number);
  return Math.max(0, endHour * 60 + endMinute - (startHour * 60 + startMinute));
}

function endTimeForDuration(startTime, durationMinutes) {
  const [hours, minutes] = startTime.split(':').map(Number);
  const total = Math.min(23 * 60 + 59, hours * 60 + minutes + Number(durationMinutes));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

function eventFormValue(event, selectedDate, preset) {
  if (!event) {
    const presetStart = preset?.startsAt ? new Date(preset.startsAt) : null;
    const presetEnd = preset?.endsAt ? new Date(preset.endsAt) : null;
    const date = presetStart ? dateKey(presetStart) : selectedDate;
    const defaultTimes = initialTimes(date);
    const times = presetStart && presetEnd ? {
      startTime: `${String(presetStart.getHours()).padStart(2, '0')}:${String(presetStart.getMinutes()).padStart(2, '0')}`,
      endTime: `${String(presetEnd.getHours()).padStart(2, '0')}:${String(presetEnd.getMinutes()).padStart(2, '0')}`,
    } : {
      ...defaultTimes,
      endTime: endTimeForDuration(defaultTimes.startTime, preset?.durationMinutes || 30),
    };
    const durationMinutes = minutesBetween(times.startTime, times.endTime);
    return {
      title: preset?.title || '', eventType: preset?.eventType || 'meeting', description: preset?.description || '', date,
      startTime: times.startTime, endTime: times.endTime,
      durationMinutes: EVENT_DURATIONS.includes(durationMinutes) ? durationMinutes : 'custom', allDay: false,
      location: '', meetingUrl: '', attendeeIds: preset?.attendeeIds || [], externalAttendeeEmails: [],
      reminderMinutes: preset?.reminderMinutes ?? 15,
      repeat: 'none', repeatFrequency: 'weekly', repeatInterval: 1,
      repeatEnds: 'count', repeatCount: 10, repeatUntil: futureDateKey(date, 90),
    };
  }
  const start = new Date(event.starts_at);
  const end = new Date(event.ends_at);
  return {
    title: event.title,
    eventType: event.event_type,
    description: event.description || '',
    date: dateKey(start),
    startTime: `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`,
    endTime: `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`,
    durationMinutes: EVENT_DURATIONS.includes(minutesBetween(
      `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`,
      `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`,
    )) ? minutesBetween(
      `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`,
      `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`,
    ) : 'custom',
    allDay: event.all_day,
    location: event.location || '',
    meetingUrl: event.meeting_url || '',
    attendeeIds: event.attendees.filter((attendee) => !attendee.is_organizer).map((attendee) => attendee.user.id),
    externalAttendeeEmails: (event.external_attendees || []).map((attendee) => attendee.email),
    reminderMinutes: event.reminder_minutes ?? '',
    repeat: event.recurrence_frequency || 'none',
    repeatFrequency: event.recurrence_frequency || 'weekly',
    repeatInterval: event.recurrence_interval || 1,
    repeatEnds: event.recurrence_ends_at ? 'date' : 'count',
    repeatCount: event.recurrence_count || 10,
    repeatUntil: event.recurrence_ends_at || futureDateKey(dateKey(start), 90),
  };
}

function ExternalGuestInput({ value, workspaceEmails, onChange }) {
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const add = () => {
    const email = draft.trim().replace(/,$/, '').toLowerCase();
    if (!email) return;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 320) {
      setError('Enter a valid email address.'); return;
    }
    if (workspaceEmails.has(email)) {
      setError('This person is in your workspace. Select them above instead.'); return;
    }
    if (value.includes(email)) {
      setError('This guest is already invited.'); return;
    }
    onChange([...value, email]); setDraft(''); setError('');
  };
  return <section className="calendar-external-guests" aria-label="External email guests">
    <div><strong>External guests</strong><small>Outside your workspace · Invitation sent by email</small></div>
    {value.length > 0 && <div className="calendar-external-chips">{value.map((email) => <span key={email}>{email}
      <button type="button" aria-label={`Remove external guest ${email}`} onClick={() => onChange(value.filter((item) => item !== email))}>×</button></span>)}</div>}
    <div className="calendar-external-entry"><label htmlFor="external-guest-email">Guest email</label><div>
      <input id="external-guest-email" type="email" value={draft} onChange={(event) => { setDraft(event.target.value); setError(''); }}
        onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ',') { event.preventDefault(); add(); } }}
        placeholder="guest@company.com" />
      <button type="button" className="button secondary" onClick={add} disabled={!draft.trim()}>Add guest</button>
    </div></div>
    {error && <p role="alert">{error}</p>}
    <small>External guests receive meeting details and the meeting link, but no workspace access.</small>
  </section>;
}

function EventForm({ event, selectedDate, preset, contacts, saving, onCancel, onSubmit }) {
  const [form, setForm] = useState(() => eventFormValue(event, selectedDate, preset));
  const set = (name, value) => setForm((current) => ({ ...current, [name]: value }));
  const contactUsers = useMemo(() => contacts.map((contact) => contact.user || contact), [contacts]);
  const workspaceEmails = useMemo(() => new Set(contactUsers.map((contact) => contact.email.toLowerCase())), [contactUsers]);
  const recurrenceValid = form.repeat === 'none'
    || (form.repeatEnds === 'count' && Number(form.repeatCount) >= 2 && Number(form.repeatCount) <= 100)
    || (form.repeatEnds === 'date' && form.repeatUntil > form.date && form.repeatUntil <= futureDateKey(form.date, 370));
  const valid = form.title.trim() && (form.eventType === 'personal' || form.attendeeIds.length + form.externalAttendeeEmails.length > 0)
    && (form.allDay || form.endTime > form.startTime) && recurrenceValid;
  const setStartTime = (startTime) => setForm((current) => ({
    ...current,
    startTime,
    endTime: current.durationMinutes === 'custom' ? current.endTime : endTimeForDuration(startTime, current.durationMinutes),
  }));
  const setEndTime = (endTime) => setForm((current) => {
    const minutes = minutesBetween(current.startTime, endTime);
    return { ...current, endTime, durationMinutes: EVENT_DURATIONS.includes(minutes) ? minutes : 'custom' };
  });
  const setDuration = (durationMinutes) => setForm((current) => ({
    ...current,
    durationMinutes,
    endTime: durationMinutes === 'custom' ? current.endTime : endTimeForDuration(current.startTime, durationMinutes),
  }));

  const submit = (submitEvent) => {
    submitEvent.preventDefault();
    if (!valid) return;
    const start = form.allDay
      ? new Date(`${form.date}T00:00:00`)
      : new Date(`${form.date}T${form.startTime}:00`);
    const end = form.allDay
      ? new Date(new Date(`${form.date}T00:00:00`).getTime() + 24 * 60 * 60 * 1000)
      : new Date(`${form.date}T${form.endTime}:00`);
    onSubmit({
      title: form.title.trim(), eventType: form.eventType,
      description: form.description.trim(), startsAt: start.toISOString(), endsAt: end.toISOString(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', allDay: form.allDay,
      location: form.location.trim(), meetingUrl: form.meetingUrl.trim(),
      reminderMinutes: form.reminderMinutes === '' ? null : Number(form.reminderMinutes),
      recurrenceFrequency: event ? 'none' : repeatFrequency(form),
      recurrenceInterval: event || form.repeat === 'none' ? 1 : Number(form.repeatInterval),
      recurrenceEndsAt: !event && form.repeat !== 'none' && form.repeatEnds === 'date' ? form.repeatUntil : null,
      recurrenceCount: !event && form.repeat !== 'none' && form.repeatEnds === 'count' ? Number(form.repeatCount) : null,
      attendeeIds: form.eventType === 'meeting' ? form.attendeeIds : [],
      externalAttendeeEmails: form.eventType === 'meeting' ? form.externalAttendeeEmails : [],
    });
  };

  return <form className="calendar-event-form" role="dialog" aria-modal="true" aria-labelledby="calendar-event-form-title" onSubmit={submit}>
    <header><div><p className="eyebrow">{event ? 'Update schedule' : 'New calendar item'}</p><h2 id="calendar-event-form-title">{event ? 'Edit event' : 'Schedule an event'}</h2></div>
      <button type="button" className="icon-button" aria-label="Close event form" onClick={onCancel}>×</button></header>
    <div className="calendar-event-type" role="radiogroup" aria-label="Event type">
      <label><input type="radio" checked={form.eventType === 'meeting'} onChange={() => set('eventType', 'meeting')} />
        <span><b>◎</b><strong>Meeting</strong><small>Invite one person or a team</small></span></label>
      <label><input type="radio" checked={form.eventType === 'personal'} onChange={() => set('eventType', 'personal')} />
        <span><b>◷</b><strong>Personal</strong><small>Private time on your calendar</small></span></label>
    </div>
    <label className="calendar-form-field full">Title<input autoFocus required maxLength="160" value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="Weekly planning" /></label>
    <div className="calendar-form-row">
      <label className="calendar-form-field">Date<input type="date" required value={form.date} onChange={(e) => set('date', e.target.value)} /></label>
      <label className="calendar-all-day"><input type="checkbox" checked={form.allDay} onChange={(e) => set('allDay', e.target.checked)} /><span>All day</span></label>
    </div>
    {!form.allDay && <div className="calendar-form-row times">
      <label className="calendar-form-field">Starts<input type="time" required value={form.startTime} onChange={(e) => setStartTime(e.target.value)} /></label>
      <span>→</span>
      <label className="calendar-form-field">Ends<input type="time" required value={form.endTime} onChange={(e) => setEndTime(e.target.value)} /></label>
      <label className="calendar-form-field calendar-duration-field">Duration<select aria-label="Event duration" value={form.durationMinutes} onChange={(e) => setDuration(e.target.value === 'custom' ? 'custom' : Number(e.target.value))}>
        {EVENT_DURATIONS.map((minutes) => <option value={minutes} key={minutes}>{minutes < 60 ? `${minutes} min` : `${minutes / 60} ${minutes === 60 ? 'hour' : 'hours'}`}</option>)}<option value="custom">Custom</option>
      </select></label>
    </div>}
    {!event && <section className="calendar-repeat-field" aria-label="Repeat schedule">
      <label className="calendar-form-field full">Repeat <small>Like an alarm</small>
        <select aria-label="Repeat" value={form.repeat} onChange={(changeEvent) => set('repeat', changeEvent.target.value)}>
          {REPEAT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {form.repeat === 'custom' && <div className="calendar-repeat-every"><span>Every</span>
        <input aria-label="Repeat interval" type="number" min="1" max="30" value={form.repeatInterval}
          onChange={(changeEvent) => set('repeatInterval', Math.max(1, Math.min(30, Number(changeEvent.target.value) || 1)))} />
        <select aria-label="Repeat unit" value={form.repeatFrequency} onChange={(changeEvent) => set('repeatFrequency', changeEvent.target.value)}>
          <option value="daily">days</option><option value="weekdays">weekdays</option>
          <option value="weekly">weeks</option><option value="monthly">months</option>
        </select></div>}
      {form.repeat !== 'none' && <div className="calendar-repeat-ends"><strong>Ends</strong>
        <label><input type="radio" name="repeat-ends" checked={form.repeatEnds === 'count'} onChange={() => set('repeatEnds', 'count')} />After
          <input aria-label="Number of occurrences" type="number" min="2" max="100" value={form.repeatCount} disabled={form.repeatEnds !== 'count'}
            onChange={(changeEvent) => set('repeatCount', changeEvent.target.value)} />occurrences</label>
        <label><input type="radio" name="repeat-ends" checked={form.repeatEnds === 'date'} onChange={() => set('repeatEnds', 'date')} />On
          <input aria-label="Repeat end date" type="date" min={futureDateKey(form.date, 1)} max={futureDateKey(form.date, 370)} value={form.repeatUntil} disabled={form.repeatEnds !== 'date'}
            onChange={(changeEvent) => set('repeatUntil', changeEvent.target.value)} /></label>
        <p><span aria-hidden="true">↻</span>{repeatSummary(form)}</p>
      </div>}
    </section>}
    {event?.series_id && <section className="calendar-repeat-readonly"><span aria-hidden="true">↻</span><div><strong>{repeatSummary(event)}</strong>
      <small>This edit changes only this occurrence. The rest of the series keeps its schedule.</small></div></section>}
    <label className="calendar-form-field full calendar-reminder-field">Reminder <small>Notification bell</small>
      <select aria-label="Reminder" value={form.reminderMinutes} onChange={(event) => set('reminderMinutes', event.target.value === '' ? '' : Number(event.target.value))}>
        {REMINDER_OPTIONS.map(([minutes, label]) => <option key={String(minutes)} value={minutes}>{label}</option>)}
      </select>
      <span>We’ll alert you here. Every attendee controls their own reminder.</span>
    </label>
    {form.eventType === 'meeting' && <UserMultiSelect label="Invite people" ariaLabel="Meeting attendees"
      users={contactUsers} value={form.attendeeIds} onChange={(ids) => set('attendeeIds', ids)}
      placeholder="Select attendees" />}
    {form.eventType === 'meeting' && preset?.unmatchedAttendee && form.attendeeIds.length === 0
      && <p className="calendar-form-hint">We couldn’t match “{preset.unmatchedAttendee}” to a workspace contact. Select the intended person before sending.</p>}
    {form.eventType === 'meeting' && <ExternalGuestInput value={form.externalAttendeeEmails}
      workspaceEmails={workspaceEmails} onChange={(emails) => set('externalAttendeeEmails', emails)} />}
    <label className="calendar-form-field full">Location <small>Optional</small><input maxLength="240" value={form.location} onChange={(e) => set('location', e.target.value)} placeholder="Conference room or office" /></label>
    {form.eventType === 'meeting' && <label className="calendar-form-field full">Meeting link <small>{form.externalAttendeeEmails.length ? 'Recommended for external guests' : 'Optional'}</small><input type="url" maxLength="500" value={form.meetingUrl} onChange={(e) => set('meetingUrl', e.target.value)} placeholder="https://meet.example.com/..." /></label>}
    <label className="calendar-form-field full">Description <small>Optional</small><textarea maxLength="2000" value={form.description} onChange={(e) => set('description', e.target.value)} placeholder="Agenda, goals, or preparation notes" /></label>
    {!valid && form.eventType === 'meeting' && form.title.trim() && <p className="calendar-form-hint">Select at least one attendee and make sure the end time follows the start time.</p>}
    <footer><span>{Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'}</span><div><button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
      <button className="button primary" disabled={!valid || saving}>{saving ? 'Saving…' : event ? 'Save changes' : form.eventType === 'meeting' ? 'Send invitation' : 'Add to calendar'}</button></div></footer>
  </form>;
}

function EventDetail({ event, saving, onClose, onEdit, onRespond, onSetReminder, onCancelEvent, onJoinCall, onCreateFollowUp }) {
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [cancelScope, setCancelScope] = useState('event');
  const activeAttendees = event.attendees.filter((attendee) => !attendee.is_organizer);
  const externalAttendees = event.external_attendees || [];
  return <aside className="calendar-event-detail" role="dialog" aria-modal="true" aria-label="Event details">
    <header><span className={`calendar-event-kind ${event.event_type}`}>{event.event_type === 'personal' ? '◷' : '◎'}</span>
      <div><p className="eyebrow">{event.event_type === 'personal' ? 'Private event' : 'Meeting'}</p><h2>{event.title}</h2></div>
      <button className="icon-button" aria-label="Close event details" onClick={onClose}>×</button></header>
    <div className="calendar-event-detail-body">
      {event.status === 'cancelled' && <div className="calendar-cancelled">Cancelled by the organizer</div>}
      <section className="calendar-detail-time"><span>◷</span><div><strong>{formatDate(event.starts_at, { weekday: 'long', month: 'long', day: 'numeric' })}</strong>
        <small>{formatTime(event.starts_at, event.all_day)}{!event.all_day && ` – ${formatTime(event.ends_at)}`} · {event.timezone}</small></div></section>
      {event.series_id && <section className="calendar-detail-line calendar-detail-repeat"><span>↻</span><div><strong>{repeatSummary(event)}</strong>
        <small>Occurrence {(event.occurrence_index || 0) + 1} of {event.recurrence_count}</small></div></section>}
      {event.status !== 'cancelled' && <section className="calendar-detail-line calendar-detail-reminder"><span>♢</span><div><label htmlFor={`event-reminder-${event.id}`}>Reminder</label>
        <select id={`event-reminder-${event.id}`} aria-label="Event reminder" value={event.reminder_minutes ?? ''} disabled={saving}
          onChange={(changeEvent) => onSetReminder(changeEvent.target.value === '' ? null : Number(changeEvent.target.value))}>
          {REMINDER_OPTIONS.map(([minutes, label]) => <option key={String(minutes)} value={minutes}>{label}</option>)}
        </select><small>{reminderLabel(event.reminder_minutes)} · Only affects you</small></div></section>}
      {event.location && <section className="calendar-detail-line"><span>⌖</span><div><strong>Location</strong><small>{event.location}</small></div></section>}
      {event.event_type === 'meeting' && event.status !== 'cancelled' && <div className="calendar-call-actions">
        <button className="calendar-join-button in-app" onClick={onJoinCall}>Join video call</button>
        {event.meeting_url && <a className="calendar-join-button" href={event.meeting_url} target="_blank" rel="noreferrer">External meeting ↗</a>}
      </div>}
      {event.description && <section className="calendar-detail-description"><strong>Details</strong><p>{event.description}</p></section>}
      {event.event_type === 'meeting' && <button className="calendar-follow-up-button" onClick={onCreateFollowUp}>＋ Create follow-up task</button>}
      <section className="calendar-organizer"><strong>Organizer</strong><div><CalendarAvatar user={event.organizer} /><span><b>{event.organizer.display_name}</b><small>{event.organizer.email}</small></span></div></section>
      {event.event_type === 'meeting' && <section className="calendar-attendees"><strong>Attendees <small>{activeAttendees.length + externalAttendees.length}</small></strong>
        {activeAttendees.map((attendee) => <div key={attendee.user.id}><CalendarAvatar user={attendee.user} /><span><b>{attendee.user.display_name}</b><small>{attendee.user.email}</small></span>
          <em className={attendee.response}>{attendee.response}</em></div>)}
        {externalAttendees.map((attendee) => <div className="external" key={attendee.email}><span className="calendar-avatar">✉</span><span><b>{attendee.email}</b><small>External guest · Email invitation</small></span>
          <em className={attendee.delivery_status}>{attendee.delivery_status === 'logged' ? 'email ready' : attendee.delivery_status}</em></div>)}</section>}
      {!event.can_manage && event.event_type === 'meeting' && event.status !== 'cancelled' && <section className="calendar-response"><strong>Your response</strong>
        <div>{[['accepted', '✓ Accept'], ['tentative', '? Maybe'], ['declined', '× Decline']].map(([response, label]) =>
          <button key={response} className={event.my_response === response ? `active ${response}` : ''} disabled={saving} onClick={() => onRespond(response)}>{label}</button>)}</div></section>}
    </div>
    {event.can_manage && event.status !== 'cancelled' && <footer>{confirmingCancel ? <div className={`calendar-cancel-confirm ${event.series_id ? 'series' : ''}`}><span><strong>{event.series_id ? 'Cancel recurring meeting?' : 'Cancel this event?'}</strong><small>Attendees will be notified.</small>
        {event.series_id && <select aria-label="Cancel recurring meeting" value={cancelScope} onChange={(changeEvent) => setCancelScope(changeEvent.target.value)}>
          <option value="event">Only this meeting</option><option value="future">This and future meetings</option><option value="series">Every meeting in the series</option>
        </select>}</span>
      <button className="button secondary" onClick={() => setConfirmingCancel(false)}>Keep</button><button className="button destructive" disabled={saving} onClick={() => onCancelEvent(cancelScope)}>Cancel</button></div>
      : <><button className="button secondary" onClick={() => setConfirmingCancel(true)}>Cancel event</button><button className="button primary" onClick={onEdit}>Edit</button></>}</footer>}
  </aside>;
}

export default function CalendarManagement({ user, onNavigate, navigationKey = window.location.search }) {
  const today = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const [selectedDate, setSelectedDate] = useState(dateKey(today));
  const [agendaOpen, setAgendaOpen] = useState(false);
  const [viewMode, setViewMode] = useState('month');
  const [events, setEvents] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [state, setState] = useState('loading');
  const [error, setError] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [saving, setSaving] = useState(false);
  const [activeCall, setActiveCall] = useState(null);
  const [schedulerOpen, setSchedulerOpen] = useState(false);
  const [schedulePreset, setSchedulePreset] = useState(null);
  const [filter, setFilter] = useState('all');
  const loadRequestRef = useRef(0);
  const deepLinkHandledRef = useRef('');

  const load = useCallback(async () => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    const range = monthRange(month);
    setState('loading'); setError('');
    try {
      const [calendarEvents, overview] = await Promise.all([
        getCalendarEvents(range.startsAt.toISOString(), range.endsAt.toISOString()),
        getCommunicationOverview(),
      ]);
      if (loadRequestRef.current !== requestId) return;
      setEvents(calendarEvents);
      setContacts(overview.communication_contacts || []);
      setSelectedEvent((current) => current
        ? calendarEvents.find((event) => event.id === current.id) || null : null);
      setState('ready');
    } catch (requestError) {
      if (loadRequestRef.current !== requestId) return;
      setError(requestError.message); setState('error');
    }
  }, [month]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (state !== 'ready' || deepLinkHandledRef.current === navigationKey) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('create') === '1') {
      deepLinkHandledRef.current = navigationKey;
      const requestedDate = params.get('date');
      if (/^\d{4}-\d{2}-\d{2}$/.test(requestedDate || '')) {
        const requested = dateFromKey(requestedDate);
        setSelectedDate(requestedDate);
        setMonth(new Date(requested.getFullYear(), requested.getMonth(), 1));
      }
      const requestedDuration = Number(params.get('duration'));
      const requestedTime = params.get('time');
      const scheduledDate = /^\d{4}-\d{2}-\d{2}$/.test(requestedDate || '') ? requestedDate : selectedDate;
      const validRequestedTime = /^([01]\d|2[0-3]):[0-5]\d$/.test(requestedTime || '');
      const startsAt = validRequestedTime ? new Date(`${scheduledDate}T${requestedTime}:00`) : null;
      const durationMinutes = EVENT_DURATIONS.includes(requestedDuration) ? requestedDuration : 30;
      const attendeeQuery = params.get('attendee')?.trim().toLocaleLowerCase();
      const attendee = attendeeQuery && contacts.map((contact) => contact.user || contact).find((contact) =>
        [contact.display_name, contact.email, contact.handle].filter(Boolean)
          .some((candidate) => candidate.toLocaleLowerCase() === attendeeQuery));
      setSchedulePreset({
        title: params.get('title') || '',
        description: params.get('description') || '',
        eventType: params.get('event_type') === 'personal' ? 'personal' : 'meeting',
        durationMinutes,
        startsAt: startsAt?.toISOString(),
        endsAt: startsAt ? new Date(startsAt.getTime() + durationMinutes * 60 * 1000).toISOString() : undefined,
        attendeeIds: attendee ? [attendee.id] : [],
        unmatchedAttendee: attendee ? '' : params.get('attendee') || '',
      });
      setEditingEvent(null); setFormOpen(true);
    }
  }, [contacts, navigationKey, selectedDate, state]);

  useEffect(() => {
    const eventId = new URLSearchParams(window.location.search).get('event');
    if (!eventId) return;
    getCalendarEvent(eventId).then((event) => {
      const eventDate = new Date(event.starts_at);
      setMonth((current) => current.getFullYear() === eventDate.getFullYear() && current.getMonth() === eventDate.getMonth()
        ? current : new Date(eventDate.getFullYear(), eventDate.getMonth(), 1));
      setSelectedDate(dateKey(eventDate)); setSelectedEvent(event);
    }).catch(() => {});
  }, [navigationKey]);

  useEffect(() => {
    if (typeof WebSocket === 'undefined') return undefined;
    const client = new CommunicationClient({
      onEvent: (event) => { if (event.type === 'calendar_updated') load(); },
      onError: setError,
    });
    client.connect();
    return () => client.disconnect();
  }, [load]);

  const range = monthRange(month);
  const calendarDays = Array.from({ length: 42 }, (_, index) => new Date(
    range.startsAt.getFullYear(), range.startsAt.getMonth(), range.startsAt.getDate() + index
  ));
  const focusDate = dateFromKey(selectedDate);
  const weekStartsAt = startOfWeek(focusDate);
  const weekDates = Array.from({ length: 7 }, (_, index) => new Date(
    weekStartsAt.getFullYear(), weekStartsAt.getMonth(), weekStartsAt.getDate() + index
  ));
  const visibleEvents = useMemo(() => events.filter((event) => filter === 'all'
    || (filter === 'meetings' && event.event_type === 'meeting')
    || (filter === 'personal' && event.event_type === 'personal')), [events, filter]);
  const agendaEvents = useMemo(() => visibleEvents.filter((event) => {
    const date = new Date(event.starts_at);
    return event.status !== 'cancelled' && date.getFullYear() === month.getFullYear() && date.getMonth() === month.getMonth();
  }).sort((first, second) => new Date(first.starts_at) - new Date(second.starts_at)), [visibleEvents, month]);
  const eventsForDate = useCallback((key) => {
    const start = new Date(`${key}T00:00:00`);
    const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
    return visibleEvents.filter((event) => new Date(event.starts_at) < end && new Date(event.ends_at) > start);
  }, [visibleEvents]);
  const selectedEvents = eventsForDate(selectedDate);
  const periodLabel = ['month', 'agenda'].includes(viewMode)
    ? formatDate(month, { month: 'long', year: 'numeric' })
    : viewMode === 'week'
      ? `${formatDate(weekDates[0], { month: 'short', day: 'numeric' })} – ${formatDate(weekDates[6], { month: 'short', day: 'numeric', year: 'numeric' })}`
      : formatDate(focusDate, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  const viewDescription = CALENDAR_VIEWS.find(([value]) => value === viewMode)?.[2];
  const upcoming = visibleEvents.filter((event) => new Date(event.ends_at) >= new Date() && event.status !== 'cancelled').slice(0, 5);
  const pendingCount = events.filter((event) => event.my_response === 'pending' && event.status !== 'cancelled').length;

  const saveEvent = async (payload) => {
    loadRequestRef.current += 1;
    setSaving(true); setError('');
    try {
      const saved = editingEvent
        ? await updateCalendarEvent(editingEvent.id, payload)
        : await createCalendarEvent(payload);
      if (saved.series_id) {
        await load();
      } else {
        setEvents((current) => [...current.filter((event) => event.id !== saved.id), saved]
          .sort((first, second) => new Date(first.starts_at) - new Date(second.starts_at)));
      }
      setSelectedDate(dateKey(saved.starts_at)); setSelectedEvent(saved);
      setFormOpen(false); setEditingEvent(null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  const respond = async (response) => {
    loadRequestRef.current += 1;
    setSaving(true); setError('');
    try {
      const updated = await respondToCalendarEvent(selectedEvent.id, response);
      setSelectedEvent(updated);
      setEvents((current) => current.map((event) => event.id === updated.id ? updated : event));
    } catch (requestError) { setError(requestError.message); }
    finally { setSaving(false); }
  };

  const cancelEvent = async (scope = 'event') => {
    loadRequestRef.current += 1;
    setSaving(true); setError('');
    try {
      const updated = await cancelCalendarEvent(selectedEvent.id, scope);
      setSelectedEvent(updated);
      if (scope === 'event') {
        setEvents((current) => current.map((event) => event.id === updated.id ? updated : event));
      } else {
        await load();
        setSelectedEvent(updated);
      }
    } catch (requestError) { setError(requestError.message); }
    finally { setSaving(false); }
  };

  const changeReminder = async (reminderMinutes) => {
    loadRequestRef.current += 1;
    setSaving(true); setError('');
    try {
      const updated = await setCalendarEventReminder(selectedEvent.id, reminderMinutes);
      setSelectedEvent(updated);
      setEvents((current) => current.map((event) => event.id === updated.id ? updated : event));
    } catch (requestError) { setError(requestError.message); }
    finally { setSaving(false); }
  };

  const goToday = () => {
    const now = new Date();
    setMonth(new Date(now.getFullYear(), now.getMonth(), 1)); setSelectedDate(dateKey(now));
    setAgendaOpen(false);
  };

  const changeView = (nextView) => {
    setViewMode(nextView);
    setAgendaOpen(false);
    const focus = dateFromKey(selectedDate);
    setMonth(new Date(focus.getFullYear(), focus.getMonth(), 1));
  };

  const movePeriod = (direction) => {
    if (['month', 'agenda'].includes(viewMode)) {
      const nextMonth = new Date(month.getFullYear(), month.getMonth() + direction, 1);
      setMonth(nextMonth); setSelectedDate(dateKey(nextMonth));
    } else {
      const focus = dateFromKey(selectedDate);
      focus.setDate(focus.getDate() + direction * (viewMode === 'week' ? 7 : 1));
      setSelectedDate(dateKey(focus)); setMonth(new Date(focus.getFullYear(), focus.getMonth(), 1));
    }
    setAgendaOpen(false);
  };

  const openScheduler = () => {
    setSchedulePreset(null); setEditingEvent(null); setSelectedEvent(null); setSchedulerOpen(true);
  };

  return <main id="workspace-main" className="calendar-shell">
    <WorkspaceTopNav active="calendar" onNavigate={onNavigate} role={user.role} />
    <section className={`calendar-workspace ${agendaOpen ? 'agenda-open' : ''}`}>
      <aside className="calendar-sidebar"><div className="calendar-user-card"><CalendarAvatar user={{ ...user, color: user.color || '#5B4BE7' }} /><span><small>Personal calendar</small><strong>{user.display_name}</strong></span></div>
        <section><span>Today</span><strong>{formatDate(today, { weekday: 'long', month: 'long', day: 'numeric' })}</strong></section>
        <nav><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}><i className="meeting" />My calendar</button>
          <button className={filter === 'meetings' ? 'active' : ''} onClick={() => setFilter('meetings')}><i className="meeting" />Meetings</button>
          <button className={filter === 'personal' ? 'active' : ''} onClick={() => setFilter('personal')}><i className="personal" />Private time</button></nav>
        <div className="calendar-sidebar-metric"><strong>{pendingCount}</strong><span>meeting {pendingCount === 1 ? 'invitation' : 'invitations'} awaiting response</span></div>
        <div className="calendar-upcoming"><h3>Coming up</h3>{upcoming.map((event) => <button key={event.id} onClick={() => { setSelectedDate(dateKey(event.starts_at)); setSelectedEvent(event); }}><time>{formatDate(event.starts_at, { month: 'short', day: 'numeric' })}</time><span><strong>{event.title}</strong><small>{formatTime(event.starts_at, event.all_day)}</small></span></button>)}
          {upcoming.length === 0 && <p>Your upcoming schedule is clear.</p>}</div></aside>
      <section className="calendar-main"><header className="calendar-toolbar"><div className="calendar-toolbar-heading"><div><p className="eyebrow">Workspace schedule</p><h1>My calendar</h1><small className="calendar-view-help">{viewDescription}</small></div><button className="button primary calendar-schedule-button" onClick={openScheduler}><span aria-hidden="true">＋</span> Schedule meeting</button></div>
        <div><div className="calendar-view-switch" role="tablist" aria-label="Calendar views">{CALENDAR_VIEWS.map(([value, label, description]) => <button key={value} role="tab" title={description} aria-selected={viewMode === value} className={viewMode === value ? 'active' : ''} onClick={() => changeView(value)}>{label}</button>)}</div>
          <button className="button secondary" onClick={goToday}>Today</button><span><button aria-label={`Previous ${viewMode}`} onClick={() => movePeriod(-1)}>‹</button>
          <strong>{periodLabel}</strong><button aria-label={`Next ${viewMode}`} onClick={() => movePeriod(1)}>›</button></span></div></header>
        {error && <div className="calendar-error notice error" role="alert"><strong>Calendar needs attention</strong><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
        {state === 'loading' && events.length === 0 && <div className="calendar-loading"><span className="spinner dark" /> Loading your schedule…</div>}
        {state === 'error' && events.length === 0 && <div className="calendar-empty"><span>!</span><strong>Couldn’t load your calendar</strong><button className="button secondary" onClick={load}>Try again</button></div>}
        {viewMode === 'month' && <div className="personal-calendar" aria-label="Monthly calendar"><div className="personal-calendar-weekdays">{WEEKDAYS.map((day) => <span key={day}>{day}</span>)}</div>
          <div className="personal-calendar-grid">{calendarDays.map((day) => {
            const key = dateKey(day);
            const dayEvents = eventsForDate(key);
            return <button key={key} className={`${day.getMonth() === month.getMonth() ? '' : 'outside'} ${key === dateKey(today) ? 'today' : ''} ${agendaOpen && key === selectedDate ? 'selected' : ''}`}
              aria-label={`${formatDate(day, { month: 'long', day: 'numeric', year: 'numeric' })}, ${dayEvents.length} events`} onClick={() => { setSelectedDate(key); setAgendaOpen(true); }}>
              <span>{day.getDate()}</span><div>{dayEvents.slice(0, 3).map((event) => <i key={event.id} className={`${event.event_type} ${event.status}`}><b>{event.all_day ? '' : formatTime(event.starts_at)}</b>{event.title}</i>)}
                {dayEvents.length > 3 && <small>+{dayEvents.length - 3} more</small>}</div></button>;
          })}</div></div>}
        {viewMode === 'week' && <section className="weekly-calendar" aria-label="Weekly calendar">
          <div className="weekly-calendar-header">{weekDates.map((day) => <button key={dateKey(day)} className={`${dateKey(day) === dateKey(today) ? 'today' : ''} ${agendaOpen && dateKey(day) === selectedDate ? 'selected' : ''}`} onClick={() => { setSelectedDate(dateKey(day)); setAgendaOpen(true); }}><span>{WEEKDAYS[day.getDay()]}</span><strong>{day.getDate()}</strong></button>)}</div>
          <div className="weekly-calendar-grid">{weekDates.map((day) => {
            const key = dateKey(day);
            const dayEvents = eventsForDate(key);
            return <section key={key} aria-label={formatDate(day, { weekday: 'long', month: 'long', day: 'numeric' })}>
              {dayEvents.map((event) => <button key={event.id} className={`${event.event_type} ${event.status}`} onClick={() => { setSelectedDate(key); setSelectedEvent(event); }}><time>{formatTime(event.starts_at, event.all_day)}</time><strong>{event.title}</strong><small>{event.event_type === 'personal' ? 'Private' : `${inviteeCount(event)} invited`}</small></button>)}
              {dayEvents.length === 0 && <div><span>Open</span><small>No events</small></div>}
            </section>;
          })}</div>
        </section>}
        {viewMode === 'day' && <section className="daily-calendar" aria-label="Daily calendar">
          <header><div><span>{formatDate(focusDate, { weekday: 'long' })}</span><strong>{focusDate.getDate()}</strong></div><p>{selectedEvents.length} {selectedEvents.length === 1 ? 'event' : 'events'} scheduled</p></header>
          <div className="daily-calendar-schedule">{selectedEvents.map((event) => <button key={event.id} className={`${event.event_type} ${event.status}`} onClick={() => setSelectedEvent(event)}><time>{formatTime(event.starts_at, event.all_day)}{!event.all_day && <small>{formatTime(event.ends_at)}</small>}</time><span><strong>{event.title}</strong><small>{event.description || (event.event_type === 'personal' ? 'Private calendar block' : `${inviteeCount(event)} invited`)}</small></span><em>{event.my_response}</em></button>)}
            {selectedEvents.length === 0 && <div className="daily-calendar-empty"><span>◷</span><strong>Your day is open</strong><p>Schedule focus time or invite your team to a meeting.</p><button className="button primary" onClick={openScheduler}>＋ Schedule</button></div>}
          </div>
        </section>}
        {viewMode === 'agenda' && <section className="calendar-agenda-view" aria-label="Calendar agenda">
          <header><div><p className="eyebrow">Chronological month view</p><h2>Agenda</h2><small>Unlike Daily, Agenda lists every event in the selected month.</small></div><span>{agendaEvents.length} events this month</span></header>
          <div>{agendaEvents.map((event, index, list) => {
            const key = dateKey(event.starts_at);
            const showDate = index === 0 || dateKey(list[index - 1].starts_at) !== key;
            return <React.Fragment key={event.id}>{showDate && <h3>{formatDate(event.starts_at, { weekday: 'long', month: 'long', day: 'numeric' })}</h3>}
              <button className={`${event.event_type} ${event.status}`} onClick={() => { setSelectedDate(key); setSelectedEvent(event); }}><time>{formatTime(event.starts_at, event.all_day)}{!event.all_day && <small>{formatTime(event.ends_at)}</small>}</time><span><strong>{event.title}</strong><small>{event.location || event.description || (event.event_type === 'personal' ? 'Private calendar block' : `${inviteeCount(event)} invited`)}</small></span><em>{event.my_response}</em></button></React.Fragment>;
          })}{agendaEvents.length === 0 && <div className="daily-calendar-empty"><span>◷</span><strong>Your agenda is clear</strong><p>Schedule focus time or invite your team to a meeting.</p></div>}</div>
        </section>}
      </section>
      {agendaOpen && <aside className="calendar-day-agenda" aria-label="Selected day agenda"><header><p className="eyebrow">Selected day</p><h2>{formatDate(dateFromKey(selectedDate), { weekday: 'long', month: 'long', day: 'numeric' })}</h2><div className="calendar-day-actions"><button className="button secondary" onClick={openScheduler}>＋ Add</button><button className="icon-button" aria-label="Close selected day" onClick={() => setAgendaOpen(false)}>×</button></div></header>
        <div>{selectedEvents.map((event) => <button key={event.id} className={`${event.event_type} ${event.status}`} onClick={() => setSelectedEvent(event)}><time>{formatTime(event.starts_at, event.all_day)}{!event.all_day && <small>{formatTime(event.ends_at)}</small>}</time><span><strong>{event.title}</strong><small>{event.event_type === 'personal' ? 'Private' : `${inviteeCount(event)} invited`}</small></span><em>{event.my_response}</em></button>)}
          {selectedEvents.length === 0 && <div className="calendar-day-empty"><span>◷</span><strong>No events</strong><p>This day is open for focus time or a team meeting.</p></div>}</div></aside>}
    </section>
    {formOpen && <div className="calendar-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) { setFormOpen(false); setEditingEvent(null); } }}>
      <EventForm event={editingEvent} selectedDate={selectedDate} preset={schedulePreset} contacts={contacts} saving={saving}
        onCancel={() => { setFormOpen(false); setEditingEvent(null); }} onSubmit={saveEvent} /></div>}
    {selectedEvent && !formOpen && <div className="calendar-detail-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedEvent(null); }}>
      <EventDetail event={selectedEvent} saving={saving} onClose={() => setSelectedEvent(null)}
        onEdit={() => { setEditingEvent(selectedEvent); setFormOpen(true); }} onRespond={respond} onSetReminder={changeReminder} onCancelEvent={cancelEvent}
        onCreateFollowUp={() => onNavigate(`/work?${new URLSearchParams({ create: '1', item_type: 'task', summary: `Follow up: ${selectedEvent.title}`.slice(0, 160), source: 'calendar', event: selectedEvent.id })}`)}
        onJoinCall={() => setActiveCall({
          callId: `meeting-${selectedEvent.id}`,
          context: { kind: 'calendar', id: selectedEvent.id },
          title: selectedEvent.title,
          media: 'video',
          ring: true,
          isHost: selectedEvent.organizer?.id === user.id,
        })} /></div>}
    {activeCall && <VideoCallPanel currentUser={user} call={activeCall} onClose={() => setActiveCall(null)} />}
    {schedulerOpen && <MeetingScheduler currentUser={{ ...user, color: user.color || '#5B4BE7' }}
      users={contacts.map((contact) => contact.user || contact)} initialDate={selectedDate}
      onAddPersonal={() => { setSchedulePreset({ eventType: 'personal' }); setEditingEvent(null); setSchedulerOpen(false); setFormOpen(true); }}
      onManualSchedule={(preset) => { setSchedulePreset(preset); setEditingEvent(null); setSchedulerOpen(false); setFormOpen(true); }}
      onClose={() => setSchedulerOpen(false)} onUseSlot={(preset) => {
        setSchedulePreset(preset); setEditingEvent(null); setSchedulerOpen(false); setFormOpen(true);
      }} />}
  </main>;
}
