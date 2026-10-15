import React, { useMemo, useRef, useState } from 'react';
import { getCalendarAvailability } from './calendarService';
import { UserMultiSelect } from './UserPicker';

const DURATIONS = [15, 30, 45, 60, 90, 120];
const DAY_RANGES = [3, 5, 10, 14];

function dateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function formatDay(value, options = { weekday: 'short', month: 'short', day: 'numeric' }) {
  return new Intl.DateTimeFormat(undefined, options).format(new Date(`${value}T12:00:00`));
}

function formatSlot(value) {
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

function rangeDates(startDate, count) {
  const start = new Date(`${startDate}T00:00:00`);
  return Array.from({ length: count }, (_, index) => {
    const day = new Date(start);
    day.setDate(day.getDate() + index);
    return dateKey(day);
  });
}

function rangeInput(startDate, days) {
  const start = new Date(`${startDate}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + days);
  return { startsAfter: start.toISOString(), startsBefore: end.toISOString() };
}

function timeMinutes(value) {
  const [hours, minutes] = value.split(':').map(Number);
  return hours * 60 + minutes;
}

function timelineSlots(day, startsAt, endsAt) {
  const slots = [];
  for (let minutes = timeMinutes(startsAt); minutes < timeMinutes(endsAt); minutes += 30) {
    const start = new Date(`${day}T00:00:00`);
    start.setMinutes(minutes);
    slots.push({ startsAt: start, endsAt: new Date(start.getTime() + 30 * 60 * 1000) });
  }
  return slots;
}

function localSlot(day, startsAt, durationMinutes) {
  const start = new Date(`${day}T${startsAt}:00`);
  return {
    startsAt: start.toISOString(),
    endsAt: new Date(start.getTime() + durationMinutes * 60 * 1000).toISOString(),
  };
}

function isBusy(entry, slot) {
  return entry.busy.some((block) => new Date(block.starts_at) < slot.endsAt && new Date(block.ends_at) > slot.startsAt);
}

function userById(users, id) {
  return users.find((user) => user.id === id);
}

function nonOverlappingSuggestions(suggestions) {
  const picked = [];
  [...suggestions].sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at)).forEach((suggestion) => {
    const previous = picked.at(-1);
    if (!previous || new Date(suggestion.starts_at) >= new Date(previous.ends_at)) picked.push(suggestion);
  });
  return picked;
}

export default function MeetingScheduler({ users = [], currentUser, initialDate, onClose, onUseSlot, onManualSchedule, onAddPersonal }) {
  const allUsers = useMemo(() => Array.from(new Map([currentUser, ...users]
    .filter((user) => user?.id).map((user) => [user.id, user])).values()), [currentUser, users]);
  const [participantIds, setParticipantIds] = useState([currentUser.id]);
  const [startDate, setStartDate] = useState(initialDate || dateKey(new Date()));
  const [days, setDays] = useState(5);
  const [duration, setDuration] = useState(30);
  const [workdayStart, setWorkdayStart] = useState('09:00');
  const [workdayEnd, setWorkdayEnd] = useState('17:00');
  const [includeWeekends, setIncludeWeekends] = useState(false);
  const [selectedDay, setSelectedDay] = useState(initialDate || dateKey(new Date()));
  const [availability, setAvailability] = useState(null);
  const [state, setState] = useState('idle');
  const [dayState, setDayState] = useState('idle');
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [showAllSuggestions, setShowAllSuggestions] = useState(false);
  const dayRequestRef = useRef(0);
  const dates = useMemo(() => rangeDates(startDate, days), [days, startDate]);
  const slots = useMemo(() => timelineSlots(selectedDay, workdayStart, workdayEnd),
    [selectedDay, workdayEnd, workdayStart]);
  const selectedSuggestions = useMemo(() => (availability?.suggestions || [])
    .filter((suggestion) => dateKey(new Date(suggestion.starts_at)) === selectedDay), [availability, selectedDay]);
  const recommendedSuggestions = useMemo(() => nonOverlappingSuggestions(selectedSuggestions), [selectedSuggestions]);
  const visibleSuggestions = showAllSuggestions ? selectedSuggestions : recommendedSuggestions.slice(0, 6);
  const valid = participantIds.length > 1 && workdayEnd > workdayStart;

  const availabilityInput = (range, maxSuggestions = 16) => ({
    userIds: participantIds,
    ...range,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    durationMinutes: duration,
    workdayStartsAt: workdayStart,
    workdayEndsAt: workdayEnd,
    intervalMinutes: 15,
    includeWeekends,
    maxSuggestions,
  });

  const updateParticipants = (ids) => {
    const guests = ids.filter((id) => id !== currentUser.id).slice(0, 99);
    setParticipantIds(Array.from(new Set([currentUser.id, ...guests])));
    setAvailability(null); setState('idle'); setCopied(false); setShowAllSuggestions(false);
  };

  const findTimes = async () => {
    if (!valid) return;
    setState('loading'); setError(''); setCopied(false);
    try {
      const range = rangeInput(startDate, days);
      const result = await getCalendarAvailability(availabilityInput(range));
      setAvailability(result); setState('ready'); setShowAllSuggestions(false);
      if (result.suggestions[0]) setSelectedDay(dateKey(new Date(result.suggestions[0].starts_at)));
    } catch (requestError) {
      setError(requestError.message || 'Availability could not be checked.'); setState('error');
    }
  };

  const selectDay = async (day) => {
    setSelectedDay(day); setCopied(false); setShowAllSuggestions(false);
    if (!availability) return;
    const requestId = dayRequestRef.current + 1;
    dayRequestRef.current = requestId;
    setDayState('loading'); setError('');
    try {
      const result = await getCalendarAvailability(availabilityInput(rangeInput(day, 1)));
      if (dayRequestRef.current !== requestId) return;
      setAvailability((current) => current ? {
        ...current,
        suggestions: [
          ...current.suggestions.filter((suggestion) => dateKey(new Date(suggestion.starts_at)) !== day),
          ...result.suggestions,
        ],
      } : current);
      setDayState('ready');
    } catch (requestError) {
      if (dayRequestRef.current !== requestId) return;
      setError(requestError.message || 'Availability for this day could not be checked.');
      setDayState('error');
    }
  };

  const copyOptions = async () => {
    const options = recommendedSuggestions.slice(0, 5).map((suggestion) =>
      `${formatDay(dateKey(new Date(suggestion.starts_at)), { weekday: 'long', month: 'short', day: 'numeric' })} · ${formatSlot(suggestion.starts_at)}–${formatSlot(suggestion.ends_at)} · ${suggestion.attendance_count}/${suggestion.total_count} available`
    ).join('\n');
    if (!options || !navigator.clipboard) return;
    await navigator.clipboard.writeText(options);
    setCopied(true);
  };

  const scheduleSlot = (suggestion) => onUseSlot({
    startsAt: suggestion.starts_at,
    endsAt: suggestion.ends_at,
    durationMinutes: duration,
    attendeeIds: participantIds.filter((id) => id !== currentUser.id),
  });

  const scheduleManually = () => {
    const slot = localSlot(selectedDay, workdayStart, duration);
    onManualSchedule({
      ...slot,
      durationMinutes: duration,
      attendeeIds: participantIds.filter((id) => id !== currentUser.id),
    });
  };

  return <div className="meeting-scheduler-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="meeting-scheduler" role="dialog" aria-modal="true" aria-label="Schedule a meeting">
      <header><div><p className="eyebrow">Calendar · Shared availability</p><h2>Schedule a meeting</h2>
        <p>Select the people first, then choose one of the suggested times when everyone is open.</p></div>
        <div className="scheduler-header-actions">{onAddPersonal && <button className="button secondary" onClick={onAddPersonal}>＋ Personal time</button>}
          <button className="icon-button" aria-label="Close scheduling assistant" onClick={onClose}>×</button></div></header>
      <div className="meeting-scheduler-body">
        <aside className="meeting-scheduler-controls">
          <section><div className="scheduler-section-heading"><span><strong>People</strong><small>{participantIds.length} selected</small></span>
            <div><button onClick={() => updateParticipants(allUsers.map((user) => user.id))}>Add everyone</button>
              <button onClick={() => updateParticipants([currentUser.id])}>Only me</button></div></div>
            <UserMultiSelect ariaLabel="Meeting availability participants" users={allUsers}
              value={participantIds} onChange={updateParticipants} requiredIds={[currentUser.id]}
              placeholder="Select meeting participants" />
            <p className="scheduler-privacy-note"><span>⌾</span> Calendar titles, descriptions, and locations stay private.</p>
          </section>
          <section className="scheduler-constraints"><strong>Meeting constraints</strong>
            <div><label>Starting<input type="date" aria-label="Availability start date" value={startDate}
              onChange={(event) => { setStartDate(event.target.value); setSelectedDay(event.target.value); setAvailability(null); }} /></label>
              <label>Search<select aria-label="Availability date range" value={days} onChange={(event) => { setDays(Number(event.target.value)); setAvailability(null); }}>
                {DAY_RANGES.map((value) => <option value={value} key={value}>{value} days</option>)}</select></label></div>
            <div><label>Duration<select aria-label="Meeting duration" value={duration} onChange={(event) => { setDuration(Number(event.target.value)); setAvailability(null); }}>
              {DURATIONS.map((value) => <option value={value} key={value}>{value < 60 ? `${value} min` : `${value / 60} ${value === 60 ? 'hour' : 'hours'}`}</option>)}</select></label>
              <label>From<input type="time" aria-label="Working hours start" value={workdayStart} onChange={(event) => { setWorkdayStart(event.target.value); setAvailability(null); }} /></label>
              <label>To<input type="time" aria-label="Working hours end" value={workdayEnd} onChange={(event) => { setWorkdayEnd(event.target.value); setAvailability(null); }} /></label></div>
            <label className="scheduler-weekend-option"><input type="checkbox" checked={includeWeekends}
              onChange={(event) => { setIncludeWeekends(event.target.checked); setAvailability(null); }} /> Include weekends</label>
          </section>
          {participantIds.length < 2 && <p className="scheduler-help">Add at least one workspace contact to compare calendars.</p>}
          {participantIds.length === 100 && <p className="scheduler-help">This scheduling check is at the 100-person limit.</p>}
          {workdayEnd <= workdayStart && <p className="scheduler-help error">Working hours must end after they start.</p>}
          {error && <div className="notice error" role="alert">{error}</div>}
          <button className="button primary scheduler-find-button" disabled={!valid || state === 'loading'} onClick={findTimes}>
            {state === 'loading' ? 'Checking calendars…' : `Suggest open times for ${participantIds.length}`}
          </button>
          {onManualSchedule && <button className="scheduler-manual-button" onClick={scheduleManually}>Set a time manually</button>}
        </aside>

        <main className="meeting-availability-results">
          {!availability && state !== 'loading' && <div className="scheduler-welcome"><span>◷</span><strong>Suggested times for the whole group</strong>
            <p>Select contacts and meeting preferences. Workspace compares private free/busy data and ranks times when every selected person is open.</p>
            <div><span><b>1</b>Select contacts</span><span><b>2</b>Suggest open times</span><span><b>3</b>Finish the invitation</span></div></div>}
          {state === 'loading' && <div className="scheduler-loading"><span className="spinner dark" /><strong>Comparing {participantIds.length} calendars…</strong><small>Only free/busy intervals are being checked.</small></div>}
          {availability && <>
            <div className="availability-summary"><span><strong>{participantIds.length}</strong><small>people compared</small></span>
              <span><strong>{days}</strong><small>days checked</small></span>
              <span><strong>{selectedSuggestions.filter((item) => item.score === 100).length}</strong><small>openings on this day</small></span>
              <span><strong>{availability.timezone}</strong><small>display timezone</small></span></div>
            <div className="availability-layout">
              <section className="availability-timeline"><header><div><strong>Calendar comparison</strong><span><i className="free" />Open <i className="busy" />Busy</span></div>
                <nav aria-label="Availability days">{dates.map((day) => <button className={selectedDay === day ? 'active' : ''}
                  key={day} onClick={() => selectDay(day)}>{formatDay(day)}</button>)}</nav></header>
                <div className="availability-grid" style={{ '--slot-count': slots.length }}>
                  <div className="availability-time-heading"><span>People</span><div>{slots.map((slot, index) => <small key={slot.startsAt.toISOString()}>{index % 2 === 0 ? formatSlot(slot.startsAt) : ''}</small>)}</div></div>
                  {availability.users.map((entry) => <div className="availability-person-row" key={entry.user.id}>
                    <span><i style={{ '--avatar-color': entry.user.color }}>{initials(entry.user.display_name)}</i><b>{entry.user.id === currentUser.id ? 'You' : entry.user.display_name}</b></span>
                    <div>{slots.map((slot) => {
                      const busy = isBusy(entry, slot);
                      return <i className={busy ? 'busy' : 'free'} key={slot.startsAt.toISOString()}
                        title={`${entry.user.display_name} · ${formatSlot(slot.startsAt)} · ${busy ? 'Busy' : 'Open'}`}
                        aria-label={`${entry.user.display_name}, ${formatSlot(slot.startsAt)}, ${busy ? 'busy' : 'open'}`} />;
                    })}</div>
                  </div>)}
                </div>
              </section>
              <aside className="availability-suggestions" aria-live="polite"><header><span><strong>Suggested open times for {formatDay(selectedDay, { weekday: 'long', month: 'short', day: 'numeric' })}</strong><small>{dayState === 'loading' ? 'Checking this day…' : 'Changes with the selected comparison day'}</small></span>
                {selectedSuggestions.length > 0 && <button onClick={copyOptions}>{copied ? 'Copied ✓' : 'Copy options'}</button>}</header>
                <div>{visibleSuggestions.map((suggestion, index) => {
                  const unavailable = suggestion.unavailable_user_ids.map((id) => userById(allUsers, id)?.display_name).filter(Boolean);
                  const exactCount = visibleSuggestions.filter((item) => item.score === 100).length;
                  return <React.Fragment key={`${suggestion.starts_at}-${suggestion.ends_at}`}>{suggestion.score < 100 && index === exactCount && <div className="availability-alternatives-heading"><strong>Closest alternatives</strong><small>Use these only if not everyone must attend</small></div>}<article className={suggestion.score === 100 ? 'exact' : 'partial'}>
                    <div><time>{formatDay(dateKey(new Date(suggestion.starts_at)), { weekday: 'short', month: 'short', day: 'numeric' })}</time>
                      <strong>{formatSlot(suggestion.starts_at)} – {formatSlot(suggestion.ends_at)}</strong></div>
                    <span><b>{suggestion.score === 100 ? 'Everyone is open' : `${suggestion.attendance_count} of ${suggestion.total_count} open`}</b>
                      {unavailable.length > 0 && <small>Conflicts: {unavailable.slice(0, 3).join(', ')}{unavailable.length > 3 ? ` +${unavailable.length - 3}` : ''}</small>}</span>
                    <button className="button secondary" onClick={() => scheduleSlot(suggestion)}>Schedule this time</button>
                  </article></React.Fragment>;
                })}
                {selectedSuggestions.length === 0 && <div className="scheduler-no-times"><span>◷</span><strong>No suggested openings on this day</strong><p>Choose another comparison day, expand working hours, or search a wider date range.</p></div>}</div>
                {selectedSuggestions.length > visibleSuggestions.length && <button className="scheduler-show-more" onClick={() => setShowAllSuggestions(true)}>Show all {selectedSuggestions.length} times</button>}
                {showAllSuggestions && selectedSuggestions.length > 6 && <button className="scheduler-show-more" onClick={() => setShowAllSuggestions(false)}>Show recommended times</button>}
              </aside>
            </div>
          </>}
        </main>
      </div>
    </section>
  </div>;
}
