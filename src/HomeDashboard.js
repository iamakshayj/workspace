import React, { useEffect, useMemo, useState } from 'react';
import { getCalendarEvents } from './calendarService';
import { getCommunicationOverview } from './communicationService';
import { getWorkOverview } from './workService';
import { snoozeNotification } from './enterpriseService';
import { getWorkIntelligenceBriefing } from './intelligenceService';

const EMPTY_SNAPSHOT = { work: null, events: [], notifications: [], intelligence: null };
const PRIORITY_WEIGHT = { highest: 5, high: 4, medium: 3, low: 2, lowest: 1 };

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function localDateKey(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function todayRange(now = new Date()) {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return { startsAfter: start.toISOString(), startsBefore: end.toISOString() };
}

function timeLabel(value, allDay = false) {
  if (allDay) return 'All day';
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

function shortDate(value) {
  if (!value) return 'No due date';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
    .format(new Date(`${value.slice(0, 10)}T12:00:00`));
}

function relativeTime(value) {
  const elapsed = Math.max(1, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function greeting(date = new Date()) {
  const hour = date.getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function notificationTarget(notification) {
  if (notification.document_id) return `/knowledge?document=${notification.document_id}`;
  if (notification.work_item_id) return `/work?item=${notification.work_item_id}`;
  if (notification.calendar_event_id) return '/calendar';
  if (notification.project_id) return `/projects/${notification.project_id}`;
  return '/work';
}

function DashboardAvatar({ user }) {
  return <span className="home-avatar" style={{ '--avatar-color': user?.color || '#6657D9' }}>
    {initials(user?.display_name)}
  </span>;
}

function EmptyPanel({ icon, title, detail }) {
  return <div className="home-panel-empty"><span>{icon}</span><strong>{title}</strong><small>{detail}</small></div>;
}

export default function HomeDashboard({
  user, recentProjects = [], projectTotalCount = 0, projectsState = 'loading',
  onNavigate,
}) {
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  const [state, setState] = useState('loading');

  useEffect(() => {
    let active = true;
    const range = todayRange();
    setState('loading');
    Promise.allSettled([
      getWorkOverview(),
      getCalendarEvents(range.startsAfter, range.startsBefore),
      getCommunicationOverview(),
      getWorkIntelligenceBriefing(),
    ]).then(([workResult, calendarResult, communicationResult, intelligenceResult]) => {
      if (!active) return;
      setSnapshot({
        work: workResult.status === 'fulfilled' ? workResult.value : null,
        events: calendarResult.status === 'fulfilled' && Array.isArray(calendarResult.value) ? calendarResult.value : [],
        notifications: communicationResult.status === 'fulfilled' && Array.isArray(communicationResult.value?.notifications)
          ? communicationResult.value.notifications : [],
        intelligence: intelligenceResult.status === 'fulfilled' ? intelligenceResult.value : null,
      });
      setState([workResult, calendarResult, communicationResult, intelligenceResult].every((result) => result.status === 'rejected') ? 'error' : 'ready');
    });
    return () => { active = false; };
  }, [user.id]);

  const today = localDateKey();
  const workItems = useMemo(() => Array.isArray(snapshot.work?.items) ? snapshot.work.items : [], [snapshot.work?.items]);
  const assignedWork = useMemo(() => workItems
    .filter((item) => item.assignee?.id === user.id && item.status !== 'done')
    .sort((left, right) => {
      const leftDue = left.due_date || '9999-12-31';
      const rightDue = right.due_date || '9999-12-31';
      return leftDue.localeCompare(rightDue)
        || (PRIORITY_WEIGHT[right.priority] || 0) - (PRIORITY_WEIGHT[left.priority] || 0)
        || new Date(right.updated_at) - new Date(left.updated_at);
    }), [workItems, user.id]);
  const unreadNotifications = snapshot.notifications.filter((item) => !item.read);
  const todayEvents = [...snapshot.events]
    .filter((event) => event.status !== 'cancelled')
    .sort((left, right) => new Date(left.starts_at) - new Date(right.starts_at));
  const projectsWithPlans = recentProjects.filter((project) => (project.task_count || 0) + (project.deliverable_count || 0) > 0);
  const portfolioProgress = projectsWithPlans.length
    ? Math.round(projectsWithPlans.reduce((sum, project) => sum + (project.plan_progress || 0), 0) / projectsWithPlans.length)
    : 0;
  const overdueAssigned = assignedWork.filter((item) => item.due_date && item.due_date < today).length;
  const intelligenceSummary = snapshot.intelligence?.summary;
  const recommendations = snapshot.intelligence?.recommendations || [];
  const intelligenceHealth = new Map((snapshot.intelligence?.project_health || [])
    .map((item) => [item.project_id, item]));
  const snooze = async (event, notification) => {
    event.stopPropagation();
    await snoozeNotification(notification.id, new Date(Date.now() + 60 * 60 * 1000).toISOString());
    setSnapshot((current) => ({ ...current, notifications: current.notifications.filter((item) => item.id !== notification.id) }));
  };

  return <section className="home-dashboard-content">
    <header className="home-dashboard-hero">
      <div><p className="eyebrow">{user.entity_name || 'Workspace'} · Today</p>
        <h1>{greeting()}, {user.display_name.split(' ')[0]}.</h1>
        <p>Here’s the work, schedule, and team activity that needs your attention.</p></div>
    </header>

    <details className="home-daily-briefing">
      <summary><strong>Daily briefing</strong>{state === 'loading' ? <><span>Loading today’s priorities, meetings, and updates…</span><small>Please wait</small></> : <><span>{(intelligenceSummary?.overdue_assigned ?? overdueAssigned) ? `${intelligenceSummary?.overdue_assigned ?? overdueAssigned} overdue assignment${(intelligenceSummary?.overdue_assigned ?? overdueAssigned) === 1 ? '' : 's'}` : 'No overdue assignments'} · {intelligenceSummary?.meetings_today ?? todayEvents.length} event{(intelligenceSummary?.meetings_today ?? todayEvents.length) === 1 ? '' : 's'} today · {intelligenceSummary?.unread_notifications ?? unreadNotifications.length} unread update{(intelligenceSummary?.unread_notifications ?? unreadNotifications.length) === 1 ? '' : 's'}</span><small>{recommendations.length ? `${recommendations.length} evidence-backed action${recommendations.length === 1 ? '' : 's'} · Expand` : 'No additional action suggested'}</small></>}</summary>
      {recommendations.length > 0 && <div className="home-briefing-recommendations" aria-label="Recommended actions">
        {recommendations.slice(0, 4).map((item) => <button key={item.id} onClick={() => onNavigate(item.proposed_action.url)}>
          <i className={item.severity} aria-hidden="true" /><span><strong>{item.title}</strong><small>{item.explanation}</small>
            <em>{Math.round(item.confidence * 100)}% confidence · {item.freshness.state} · {item.sources.length} source{item.sources.length === 1 ? '' : 's'}</em></span><b>{item.proposed_action.label} →</b>
        </button>)}
        <p>Generated from information you can currently access. Every action is a review link; nothing is changed automatically.</p>
      </div>}
    </details>

    {state === 'error' && <div className="notice error home-dashboard-error"><strong>Dashboard data is temporarily unavailable.</strong><span>You can still open Work, Calendar, and Workflows from the navigation.</span></div>}

    <div className="home-focus-grid">
      <section className="home-panel home-work-panel">
        <header><div><p className="eyebrow">Focus</p><h2>Assigned to me</h2></div><button onClick={() => onNavigate('/work')}>View all work →</button></header>
        {state === 'loading' && <div className="home-panel-loading"><span className="spinner dark" /> Loading assigned work…</div>}
        {state !== 'loading' && assignedWork.length === 0 && <EmptyPanel icon="✓" title="Your queue is clear" detail="Newly assigned stories and tasks will appear here." />}
        {assignedWork.slice(0, 5).map((item) => {
          const isOverdue = item.due_date && item.due_date < today;
          return <button className="home-work-row" key={item.id} onClick={() => onNavigate(`/work?item=${item.id}`)}>
            <span className={`home-work-type ${item.item_type}`}>{({ epic: '⚡', story: '▤', subtask: '↳', bug: '◆', milestone: '◇' })[item.item_type] || '✓'}</span>
            <span><strong>{item.summary}</strong><small>{item.key} · {item.status.replaceAll('_', ' ')}</small></span>
            <span className={`home-priority ${item.priority}`}>{item.priority}</span>
            <time className={isOverdue ? 'overdue' : ''}>{isOverdue ? 'Overdue · ' : ''}{shortDate(item.due_date)}</time>
          </button>;
        })}
      </section>

      <section className="home-panel home-calendar-panel">
        <header><div><p className="eyebrow">Schedule</p><h2>Today</h2></div><button onClick={() => onNavigate('/calendar')}>Full calendar →</button></header>
        <div className="home-day-heading"><span>{new Intl.DateTimeFormat(undefined, { weekday: 'long' }).format(new Date())}</span><strong>{new Date().getDate()}</strong><small>{new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(new Date())}</small></div>
        {state === 'loading' && <div className="home-panel-loading"><span className="spinner dark" /> Loading schedule…</div>}
        {state !== 'loading' && todayEvents.length === 0 && <EmptyPanel icon="◷" title="Your day is open" detail="Use Schedule meeting to find a time when everyone is open." />}
        <div className="home-agenda-list">{todayEvents.slice(0, 5).map((event) => <button key={event.id} onClick={() => onNavigate('/calendar')}>
          <time>{timeLabel(event.starts_at, event.all_day)}</time><i className={event.event_type} />
          <span><strong>{event.title}</strong><small>{event.event_type === 'meeting' ? `${event.attendees?.length || 0} participants` : 'Personal calendar'}</small></span>
        </button>)}</div>
      </section>
    </div>

    <div className="home-insight-grid">
      <section className="home-panel home-flow-panel">
        <header><div><p className="eyebrow">Process portfolio</p><h2>Workflow health</h2></div><button onClick={() => onNavigate('/workflows')}>All workflows →</button></header>
        <div className="home-portfolio-summary"><span><strong>{projectsState === 'loading' ? '—' : projectTotalCount}</strong><small>Accessible workflows</small></span><span><strong>{projectsState === 'loading' ? '—' : `${portfolioProgress}%`}</strong><small>Average delivery</small></span><span><strong>{projectsState === 'loading' ? '—' : (intelligenceSummary?.at_risk_projects ?? recentProjects.filter((project) => project.approval_status === 'approved').length)}</strong><small>{intelligenceSummary ? 'Need attention' : 'Recently approved'}</small></span></div>
        {projectsState === 'loading' && <div className="home-panel-loading"><span className="spinner dark" /> Loading workflows…</div>}
        {projectsState !== 'loading' && recentProjects.length === 0 && <EmptyPanel icon="↳" title="No workflows yet" detail="Create a process map to connect work with execution." />}
        <div className="home-flow-list">{recentProjects.slice(0, 4).map((project) => {
          const health = intelligenceHealth.get(project.id);
          return <button key={project.id} onClick={() => onNavigate(`/projects/${project.id}`)}>
            <span className="home-flow-symbol"><i /><i /><i /></span><span><strong>{project.title}</strong><small>{project.node_count} steps · Updated {relativeTime(project.updated_at)}{health ? ` · ${health.health.replaceAll('_', ' ')}` : ''}</small></span>
            <span className={`home-flow-progress ${health?.health || ''}`}><b>{health ? `${health.score}/100` : `${project.plan_progress || 0}%`}</b><i><b style={{ width: `${health?.score ?? project.plan_progress ?? 0}%` }} /></i></span>
          </button>;
        })}</div>
      </section>

      <section className="home-panel home-notification-panel">
        <header><div><p className="eyebrow">Team activity</p><h2>Notifications</h2></div><span>{state === 'loading' ? 'Loading…' : `${unreadNotifications.length} unread`}</span></header>
        {state === 'loading' && <div className="home-panel-loading"><span className="spinner dark" /> Loading updates…</div>}
        {state !== 'loading' && unreadNotifications.length === 0 && <EmptyPanel icon="●" title="You’re all caught up" detail="Mentions, assignments, and invitations will appear here." />}
        <div className="home-notification-list">{unreadNotifications.slice(0, 4).map((notification) => <div className="home-notification-row" key={notification.id}><button onClick={() => onNavigate(notificationTarget(notification))}>
          <DashboardAvatar user={notification.actor} /><span><strong>{notification.title}</strong><small>{notification.body}</small><em>{relativeTime(notification.created_at)}</em></span>
        </button><button className="home-notification-snooze" onClick={(event) => snooze(event, notification)}>Snooze 1h</button></div>)}</div>
      </section>
    </div>

  </section>;
}
