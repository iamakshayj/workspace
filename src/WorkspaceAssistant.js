import React, { useEffect, useRef, useState } from 'react';
import { askWorkspaceAssistant } from './assistantService';

const PAGE_CONTEXT = {
  home: ['Home', ['Plan my day', 'Summarize what I should prioritize', 'Draft a project update']],
  work: ['Work', ['Break this goal into stories', 'Write acceptance criteria', 'Identify delivery risks']],
  calendar: ['Calendar', ['Prepare a meeting agenda', 'Draft a follow-up message', 'Help plan my week']],
  workflows: ['Workflows', ['Turn a process into steps', 'Find gaps in this process', 'Write a process description']],
  knowledge: ['Knowledge', ['Draft a team document', 'Summarize this topic', 'Create a decision record']],
  operations: ['Operations', ['Analyze operational risks', 'Draft an executive summary', 'Suggest useful metrics']],
};

const SHORTCUTS = [
  { label: 'Task', icon: '✓', path: '/work?create=1&item_type=task&source=assistant' },
  { label: 'Meeting', icon: '◷', path: '/calendar?create=1&source=assistant' },
  { label: 'Page', icon: '▤', path: '/knowledge?create=1&source=assistant' },
  { label: 'Workflow', icon: '◇', path: '/editor?ai=1&source=assistant' },
];

function loadConversation(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value.slice(-20) : [];
  } catch { return []; }
}

function timeLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function localDateKey(value) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
}

function normalizeCommand(text) {
  return String(text || '').trim().toLowerCase()
    .replace(/\bcalender\b/g, 'calendar')
    .replace(/\bdashbord\b/g, 'dashboard')
    .replace(/\bknowlege\b/g, 'knowledge')
    .replace(/\bflow\s*sh?art\b/g, 'flowchart')
    .replace(/\bsot(?:ry|ries)\b/g, 'story')
    .replace(/\bhie?archy\b/g, 'hierarchy')
    .replace(/\bdependancies\b/g, 'dependencies')
    .replace(/\badminstration\b/g, 'administration')
    .replace(/\bopertations\b/g, 'operations')
    .replace(/\bnotifs?\b/g, 'notifications')
    .replace(/[^a-z0-9:@._'\-\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const NAVIGATION_DESTINATIONS = [
  { aliases: ['active sprint board', 'current sprint board', 'sprint board'], path: '/work?tab=board&scope=active', label: 'active sprint board' },
  { aliases: ['workspace board', 'work board', 'kanban board', 'board'], path: '/work?tab=board&scope=all', label: 'workspace board' },
  { aliases: ['issue navigator', 'issues', 'tickets'], path: '/work?tab=issues', label: 'issue navigator' },
  { aliases: ['story hierarchy', 'stories hierarchy', 'work hierarchy', 'hierarchy', 'stories'], path: '/work?tab=stories', label: 'story hierarchy' },
  { aliases: ['product backlog', 'backlog'], path: '/work?tab=backlog', label: 'backlog' },
  { aliases: ['sprint planning', 'sprints'], path: '/work?tab=sprints', label: 'sprint planning' },
  { aliases: ['release planning', 'releases'], path: '/work?tab=releases', label: 'releases' },
  { aliases: ['roadmap', 'roadmaps'], path: '/work?tab=roadmap', label: 'roadmap' },
  { aliases: ['dependency map', 'dependencies', 'blockers'], path: '/work?tab=dependencies', label: 'dependency map' },
  { aliases: ['work reports', 'delivery reports', 'agile reports'], path: '/work?tab=reports', label: 'work reports' },
  { aliases: ['calendar', 'schedule'], path: '/calendar', label: 'calendar' },
  { aliases: ['workflow library', 'workflow list', 'flowcharts', 'flowchart', 'diagrams', 'process maps', 'workflows'], path: '/workflows', label: 'workflows' },
  { aliases: ['knowledge base', 'documents', 'documentation', 'docs', 'wiki', 'pages', 'knowledge'], path: '/knowledge', label: 'knowledge' },
  { aliases: ['organization chart', 'organization', 'org chart', 'people', 'teams'], path: '/operations?tab=organization', label: 'organization' },
  { aliases: ['organizational memory', 'audit history', 'memory', 'audit'], path: '/operations?tab=memory', label: 'organizational memory' },
  { aliases: ['meeting records', 'meeting history', 'meetings'], path: '/operations?tab=meetings', label: 'meeting records' },
  { aliases: ['executive dashboards', 'dashboards'], path: '/operations?tab=dashboards', label: 'dashboards' },
  { aliases: ['enterprise reports', 'report builder'], path: '/operations?tab=reports', label: 'enterprise reports' },
  { aliases: ['file manager', 'workspace files', 'files'], path: '/operations?tab=files', label: 'workspace files' },
  { aliases: ['approval center', 'approvals'], path: '/operations?tab=approvals', label: 'approvals' },
  { aliases: ['notification preferences', 'notifications'], path: '/operations?tab=preferences', label: 'notification preferences' },
  { aliases: ['project portfolio', 'projects', 'operations'], path: '/operations?tab=projects', label: 'workspace operations' },
  { aliases: ['access policy', 'access policies'], path: '/admin?tab=access', label: 'access policies' },
  { aliases: ['data governance', 'data residency'], path: '/admin?tab=governance', label: 'data governance' },
  { aliases: ['integrations and api', 'integrations', 'api settings'], path: '/admin?tab=integrations', label: 'integrations' },
  { aliases: ['plans and support', 'commercial controls'], path: '/admin?tab=commercial', label: 'plans and support' },
  { aliases: ['reliability', 'service health'], path: '/admin?tab=reliability', label: 'service health' },
  { aliases: ['compliance evidence', 'compliance'], path: '/admin?tab=compliance', label: 'compliance evidence' },
  { aliases: ['administration', 'admin'], path: '/admin', label: 'administration' },
  { aliases: ['my work', 'work'], path: '/work', label: 'work' },
  { aliases: ['home page', 'homepage', 'dashboard', 'home'], path: '/', label: 'dashboard' },
];

function navigationDestination(command) {
  const withoutCourtesy = command.replace(/^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?/, '');
  const match = withoutCourtesy.match(/^(?:go|open|show(?: me)?|navigate|switch|take me|bring me)(?:\s+to)?(?:\s+the)?\s+(.+)$/);
  if (!match) return null;
  const destination = match[1].replace(/\s+page$/, '').trim();
  return NAVIGATION_DESTINATIONS.find(({ aliases }) => aliases.some((alias) => destination === alias || destination.startsWith(`${alias} `))) || null;
}

function interfaceAction(command) {
  const isOpenCommand = /^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:go|open|show(?: me)?|navigate|switch|take me|bring me|check)(?:\s+to)?(?:\s+the)?\s+/.test(command);
  if (!isOpenCommand) return null;
  if (/\b(chat|messages|inbox)\b/.test(command)) {
    return { type: 'ui_action', event: 'workspace:open-communication', detail: { panel: 'messages' }, label: 'messages' };
  }
  if (/\bnotifications?\b/.test(command) && !/\b(preferences|settings)\b/.test(command)) {
    return { type: 'ui_action', event: 'workspace:open-communication', detail: { panel: 'notifications' }, label: 'notifications' };
  }
  const settings = command.match(/\b(profile|preferences|settings|security settings|team settings|contacts)\b/);
  if (settings) {
    const tab = settings[1] === 'profile' ? 'profile'
      : settings[1].includes('security') ? 'security'
        : /team|contacts/.test(settings[1]) ? 'team' : 'preferences';
    return { type: 'ui_action', event: 'workspace:open-settings', detail: { tab }, label: tab === 'team' ? 'entity and contacts' : tab };
  }
  return null;
}

export function parseWorkspaceAction(text, now = new Date()) {
  const value = String(text || '').trim();
  const command = normalizeCommand(value);
  const approvalDraft = /\b(?:create|add|make|start|new)\b/.test(command)
    && command.match(/\b(approval definition|approval workflow|approval request)\b/);
  if (approvalDraft) {
    const isRequest = approvalDraft[1] === 'approval request';
    return {
      type: 'route_draft',
      path: `/operations?tab=approvals&create=${isRequest ? 'approval-request' : 'approval-definition'}`,
      label: isRequest ? 'approval request' : 'approval definition',
    };
  }

  const workMatch = command.match(/\b(?:create|add|make|start|new)\b[\s\S]*?\b(initiative|epic|feature|user story|story|subtask|task|bug|defect|spike|improvement|technical debt|milestone|request|deliverable|approval|ticket|issue)\b/i);
  if (workMatch) {
    const rawType = workMatch[1].toLowerCase();
    const itemType = ({ 'user story': 'story', defect: 'bug', ticket: 'task', issue: 'task' })[rawType] || rawType.replace(' ', '_');
    const summaryMatch = value.match(/\b(?:called|named|titled)\s+["']?(.+?)["']?[.!?]*$/i)
      || value.match(/\b(?:initiative|epic|feature|user story|story|subtask|task|bug|defect|spike|improvement|technical debt|milestone|request|deliverable|approval|ticket|issue)\s*:\s*(.+)$/i);
    return {
      type: 'work_draft', itemType, label: itemType,
      summary: summaryMatch?.[1]?.trim() || '',
    };
  }

  const isMeetingRequest = /\b(schedule|book|set up|arrange|create|add|new)\b/i.test(value) && /\b(call|meeting|sync)\b/i.test(value);

  if (isMeetingRequest) {
    const timeMatch = value.match(/\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i);
    if (timeMatch) {
      let hour = Number(timeMatch[1]);
      const minute = Number(timeMatch[2] || 0);
      if (hour >= 1 && hour <= 12 && minute <= 59) {
        if (timeMatch[3].toLowerCase() === 'pm' && hour !== 12) hour += 12;
        if (timeMatch[3].toLowerCase() === 'am' && hour === 12) hour = 0;

        const date = new Date(now);
        date.setHours(12, 0, 0, 0);
        let dateRecognized = true;
        if (/\b(tomorrow|tmrw|tmr)\b/i.test(value)) date.setDate(date.getDate() + 1);
        else if (!/\btoday\b/i.test(value)) {
          const weekday = value.match(/\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b/i);
          if (weekday) {
            const target = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'].indexOf(weekday[1].slice(0, 3).toLowerCase());
            const offset = (target - date.getDay() + 7) % 7 || 7;
            date.setDate(date.getDate() + offset);
          } else dateRecognized = false;
        }

        const contactMatch = value.match(/\bwith\s+(.+?)(?=\s+(?:tomorrow|tmrw|tmr|today|on\b|at\s+\d|for\s+\d)|$)/i);
        const contact = contactMatch?.[1]?.trim().replace(/[,.]+$/, '') || '';
        if (contact && dateRecognized) {
          const durationMatch = value.match(/\bfor\s+(\d{1,3})\s*(minutes?|mins?|hours?|hrs?)\b/i);
          const duration = durationMatch
            ? Number(durationMatch[1]) * (/^h/i.test(durationMatch[2]) ? 60 : 1)
            : 30;
          const safeDuration = [15, 30, 45, 60, 90, 120].includes(duration) ? duration : 30;
          return {
            type: 'meeting_draft', contact, date: localDateKey(date),
            time: `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`,
            duration: safeDuration, title: `Call with ${contact}`,
          };
        }
      }
    }
    return { type: 'route_draft', path: '/calendar?create=1&source=assistant', label: 'meeting' };
  }

  const createIntent = /\b(create|add|make|start|new)\b/.test(command);
  if (createIntent && /\b(page|document|doc|wiki article)\b/.test(command)) {
    return { type: 'route_draft', path: '/knowledge?create=1&source=assistant', label: 'page' };
  }
  if (createIntent && /\b(workflow|flowchart|diagram|process map)\b/.test(command)) {
    return { type: 'route_draft', path: '/editor?ai=1&source=assistant', label: 'workflow' };
  }
  const enterpriseDrafts = [
    [/\b(team|group|department|business unit|organization unit)\b/, '/operations?tab=organization&create=organization', 'organization unit'],
    [/\b(dependency|relationship|blocker)\b/, '/operations?tab=dependencies&create=relationship', 'dependency'],
    [/\b(dashboard)\b/, '/operations?tab=dashboards&create=dashboards', 'dashboard'],
    [/\b(report)\b/, '/operations?tab=reports&create=report', 'report'],
    [/\b(file|folder|file reference)\b/, '/operations?tab=files&create=files', 'file reference'],
    [/\b(approval definition|approval workflow)\b/, '/operations?tab=approvals&create=approval-definition', 'approval definition'],
    [/\b(approval request)\b/, '/operations?tab=approvals&create=approval-request', 'approval request'],
    [/\b(risk)\b/, '/operations?tab=projects&create=risk', 'project risk'],
    [/\b(decision)\b/, '/operations?tab=projects&create=decision', 'project decision'],
  ];
  if (createIntent) {
    const draft = enterpriseDrafts.find(([pattern]) => pattern.test(command));
    if (draft) return { type: 'route_draft', path: draft[1], label: draft[2] };
  }

  const interfaceCommand = interfaceAction(command);
  if (interfaceCommand) return interfaceCommand;
  const navigation = navigationDestination(command);
  if (navigation) return { type: 'navigate', path: navigation.path, label: navigation.label };
  return null;
}

function AssistantInline({ text }) {
  return String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function AssistantText({ text }) {
  return <div className="workspace-ai-answer">{String(text).split('\n').map((line, index) => {
    if (/^[-*]\s+/.test(line)) return <p className="workspace-ai-list" key={index}>• <AssistantInline text={line.replace(/^[-*]\s+/, '')} /></p>;
    if (/^#{1,3}\s+/.test(line)) return <strong key={index}><AssistantInline text={line.replace(/^#{1,3}\s+/, '')} /></strong>;
    if (!line.trim()) return <span className="workspace-ai-gap" key={index} />;
    return <p key={index}><AssistantInline text={line} /></p>;
  })}</div>;
}

export default function WorkspaceAssistant({ active = 'home', onNavigate, currentUser: user }) {
  const storageKey = `workspace:assistant:${user.id}`;
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState(() => loadConversation(storageKey));
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const [pageLabel, suggestions] = PAGE_CONTEXT[active] || PAGE_CONTEXT.home;

  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(messages.slice(-20)));
    if (typeof scrollRef.current?.scrollTo === 'function') {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, storageKey]);

  useEffect(() => {
    const openAssistant = () => setOpen(true);
    const closeOnEscape = (event) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('workspace:open-assistant', openAssistant);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('workspace:open-assistant', openAssistant);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, []);

  const send = async (text = draft, { retry = false } = {}) => {
    const content = text.trim();
    if (!content || busy) return;
    const userMessage = { id: `${Date.now()}-user`, role: 'user', content, createdAt: new Date().toISOString() };
    const nextMessages = retry ? messages : [...messages, userMessage].slice(-19);
    if (!retry) setMessages(nextMessages);
    setDraft('');
    setError('');
    const action = parseWorkspaceAction(content);
    if (action?.type === 'navigate') {
      setMessages((current) => [...current, {
        id: `${Date.now()}-assistant`, role: 'assistant', mode: 'navigation', actionPerformed: false,
        content: `Opening the ${action.label}.`, createdAt: new Date().toISOString(),
      }].slice(-20));
      onNavigate(action.path);
      setOpen(false);
      return;
    }
    if (action?.type === 'ui_action') {
      setMessages((current) => [...current, {
        id: `${Date.now()}-assistant`, role: 'assistant', mode: 'navigation', actionPerformed: true,
        content: `Opening ${action.label}.`, createdAt: new Date().toISOString(),
      }].slice(-20));
      setOpen(false);
      window.requestAnimationFrame(() => window.dispatchEvent(new CustomEvent(action.event, { detail: action.detail })));
      return;
    }
    if (action?.type === 'route_draft') {
      setMessages((current) => [...current, {
        id: `${Date.now()}-assistant`, role: 'assistant', mode: 'draft', actionPerformed: false,
        content: `I opened the ${action.label} form. Review the details, then save it.`, createdAt: new Date().toISOString(),
      }].slice(-20));
      onNavigate(action.path);
      setOpen(false);
      return;
    }
    if (action?.type === 'work_draft') {
      const params = new URLSearchParams({
        create: '1', source: 'assistant', item_type: action.itemType, request: String(Date.now()),
      });
      if (action.summary) params.set('summary', action.summary);
      setMessages((current) => [...current, {
        id: `${Date.now()}-assistant`, role: 'assistant', mode: 'draft', actionPerformed: false,
        content: `I opened a new ${action.label} form${action.summary ? ` for “${action.summary}”` : ''}. Add any remaining details, then create it.`,
        createdAt: new Date().toISOString(),
      }].slice(-20));
      onNavigate(`/work?${params.toString()}`);
      setOpen(false);
      return;
    }
    if (action?.type === 'meeting_draft') {
      const params = new URLSearchParams({
        create: '1', source: 'assistant', title: action.title, date: action.date,
        time: action.time, duration: String(action.duration), attendee: action.contact,
        request: String(Date.now()),
      });
      setMessages((current) => [...current, {
        id: `${Date.now()}-assistant`, role: 'assistant', mode: 'draft', actionPerformed: false,
        content: `I prepared a ${action.duration}-minute call with ${action.contact} for ${action.date} at ${action.time}. Review the details, then send the invitation.`,
        createdAt: new Date().toISOString(),
      }].slice(-20));
      onNavigate(`/calendar?${params.toString()}`);
      setOpen(false);
      return;
    }
    setBusy(true);
    try {
      const visibleHeading = window.document.querySelector('h1')?.textContent?.trim();
      const result = await askWorkspaceAssistant(
        nextMessages.map(({ role, content: messageContent }) => ({ role, content: messageContent })).slice(-20),
        { page: active, title: visibleHeading || pageLabel, details: `The user is viewing ${window.location.pathname}${window.location.search}.` },
      );
      setMessages((current) => [...current, {
        id: `${Date.now()}-assistant`, role: 'assistant', content: result.answer,
        mode: result.mode || 'advisory', actionPerformed: Boolean(result.action_performed), createdAt: new Date().toISOString(),
      }].slice(-20));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
      window.requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  const clearConversation = () => {
    setMessages([]);
    setError('');
    localStorage.removeItem(storageKey);
  };

  return <div className="workspace-ai-control">
    <button className={`workspace-ai-trigger ${open ? 'active' : ''}`} aria-label="Workspace AI" aria-expanded={open} onClick={() => setOpen((value) => !value)}><span>✦</span><strong>AI</strong></button>
    {open && <section className="workspace-ai-panel" role="dialog" aria-modal="false" aria-label="Workspace AI assistant">
      <header><div><span className="workspace-ai-mark">✦</span><div><h2>Workspace AI</h2><p>Ask anything · {pageLabel} context</p></div></div><span className="workspace-ai-private">Advisory</span><button aria-label="Clear AI conversation" title="Clear conversation" onClick={clearConversation}>↺</button><button aria-label="Close Workspace AI" onClick={() => setOpen(false)}>×</button></header>
      <div className="workspace-ai-history" ref={scrollRef}>
        {!messages.length && <div className="workspace-ai-welcome"><span>✦</span><h3>How can I help?</h3><p>Ask a general question or use the current page as context for planning, writing, analysis, and brainstorming.</p><div>{suggestions.map((item) => <button key={item} onClick={() => send(item)}>{item}<span>→</span></button>)}</div></div>}
        {messages.map((message) => <article className={message.role} key={message.id}>
          <span>{message.role === 'assistant' ? '✦' : user.display_name.split(' ').map((item) => item[0]).slice(0, 2).join('')}</span><div>{message.role === 'assistant' ? <AssistantText text={message.content} /> : <p>{message.content}</p>}{message.role === 'assistant' && <footer><small>{message.actionPerformed ? 'Workspace updated' : message.mode === 'draft' ? 'Draft prepared · not saved' : message.mode === 'navigation' ? 'Navigation completed' : message.mode === 'fallback' ? 'Limited mode · no changes made' : 'Advisory · no changes made'}{timeLabel(message.createdAt) ? ` · ${timeLabel(message.createdAt)}` : ''}</small><button onClick={() => navigator.clipboard?.writeText(message.content)}>Copy</button></footer>}</div>
        </article>)}
        {busy && <article className="assistant workspace-ai-thinking"><span>✦</span><div><i /><i /><i /><small>Thinking…</small></div></article>}
        {error && <div className="workspace-ai-error"><strong>Couldn’t answer</strong><p>{error}</p><button onClick={() => send(messages.filter((item) => item.role === 'user').at(-1)?.content || draft, { retry: true })}>Try again</button></div>}
      </div>
      <div className="workspace-ai-shortcuts"><span>Create in Workspace</span>{SHORTCUTS.map((item) => <button key={item.label} onClick={() => { onNavigate(item.path); setOpen(false); }}><i>{item.icon}</i>{item.label}</button>)}</div>
      <form className="workspace-ai-composer" onSubmit={(event) => { event.preventDefault(); send(); }}><textarea ref={inputRef} aria-label="Ask Workspace AI" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
      }} placeholder={`Ask anything, or ask about ${pageLabel.toLowerCase()}…`} /><footer><span>Enter to send · Shift+Enter for a new line</span><button disabled={!draft.trim() || busy} aria-label="Send to Workspace AI">↑</button></footer></form>
      <p className="workspace-ai-disclaimer">AI can make mistakes. Review important answers and generated work.</p>
    </section>}
  </div>;
}
