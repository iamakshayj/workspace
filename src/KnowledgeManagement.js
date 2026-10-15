import React, { useEffect, useMemo, useRef, useState } from 'react';
import WorkspaceTopNav from './WorkspaceTopNav';
import { getCommunicationOverview } from './communicationService';
import { UserMultiSelect, UserSelect } from './UserPicker';
import {
  addKnowledgeComment, createKnowledgeDocument, createKnowledgeSpace, getKnowledgeDocument,
  duplicateKnowledgeDocument, followKnowledgeDocument, getKnowledgeOverview, getKnowledgeRevision,
  resolveKnowledgeComment, restoreKnowledgeRevision, updateKnowledgeAccess, updateKnowledgeDocument,
  updateKnowledgeSpace,
} from './knowledgeService';

const EMPTY_EDITOR = {
  title: '', summary: '', body: '', status: 'draft', visibility: 'workspace',
  classification: 'internal', template: 'blank', owner_id: '', parent_id: '', icon: '▤', labels: '',
  space_id: '', review_due_at: '', expires_at: '',
};

function dateLabel(value) {
  if (!value) return 'Not set';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    .format(new Date(`${value.slice(0, 10)}T12:00:00`));
}

function timeLabel(value) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    .format(new Date(value));
}

function documentFromQuery() {
  return new URLSearchParams(window.location.search).get('document') || '';
}

function InlineMarkdown({ text, onOpenDocument }) {
  const parts = String(text).split(/(\[\[doc:[0-9a-fA-F-]{36}\]\]|\[[^\]]+\]\(https?:\/\/[^)]+\)|\*\*[^*]+\*\*|_[^_]+_|`[^`]+`|(?<![\w@])@[a-zA-Z0-9._-]{2,80})/g);
  return parts.map((part, index) => {
    const doc = part.match(/^\[\[doc:([0-9a-fA-F-]{36})\]\]$/);
    if (doc) return <button className="knowledge-inline-link" key={`${part}-${index}`} onClick={() => onOpenDocument(doc[1])}>Linked document</button>;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('_') && part.endsWith('_')) return <em key={`${part}-${index}`}>{part.slice(1, -1)}</em>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={`${part}-${index}`}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
    if (link) return <a key={`${part}-${index}`} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    if (part.startsWith('@')) return <span className="knowledge-mention" key={`${part}-${index}`}>{part}</span>;
    return <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>;
  });
}

function MarkdownPreview({ body, onOpenDocument, pageTitle = '' }) {
  if (!body.trim()) return <div className="knowledge-preview-empty">Start writing to see a formatted preview.</div>;
  const lines = body.split('\n');
  const firstContentIndex = lines.findIndex((line) => line.trim());
  const blocks = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    if (line.startsWith('```')) {
      const language = line.slice(3).trim(); const content = []; const start = index; index += 1;
      while (index < lines.length && !lines[index].startsWith('```')) { content.push(lines[index]); index += 1; }
      blocks.push({ kind: 'code', language, content: content.join('\n'), index: start }); index += 1; continue;
    }
    const panel = line.match(/^:::(info|warning|success|note)(?:\s+(.+))?$/);
    const expand = line.match(/^:::expand(?:\s+(.+))?$/);
    if (panel || expand) {
      const content = []; const start = index; index += 1;
      while (index < lines.length && lines[index].trim() !== ':::') { content.push(lines[index]); index += 1; }
      blocks.push({ kind: expand ? 'expand' : 'panel', variant: panel?.[1], title: expand?.[1] || panel?.[2], content: content.join('\n'), index: start }); index += 1; continue;
    }
    if (line.includes('|') && line.trim().startsWith('|') && /^\|?\s*:?-+/.test(lines[index + 1] || '')) {
      const rows = []; const start = index;
      rows.push(line.split('|').slice(1, -1).map((cell) => cell.trim())); index += 2;
      while (index < lines.length && lines[index].trim().startsWith('|')) { rows.push(lines[index].split('|').slice(1, -1).map((cell) => cell.trim())); index += 1; }
      blocks.push({ kind: 'table', rows, index: start }); continue;
    }
    blocks.push({ kind: 'line', content: line, index }); index += 1;
  }
  return <div className="knowledge-markdown">{blocks.map((block) => {
    if (block.kind === 'code') return <pre className="knowledge-code-block" key={block.index}><span>{block.language || 'code'}</span><code>{block.content}</code></pre>;
    if (block.kind === 'panel') return <aside className={`knowledge-panel ${block.variant}`} key={block.index}><strong>{block.title || block.variant}</strong><MarkdownPreview body={block.content} pageTitle="" onOpenDocument={onOpenDocument} /></aside>;
    if (block.kind === 'expand') return <details className="knowledge-expand" key={block.index}><summary>{block.title || 'More details'}</summary><MarkdownPreview body={block.content} pageTitle="" onOpenDocument={onOpenDocument} /></details>;
    if (block.kind === 'table') return <div className="knowledge-table-wrap" key={block.index}><table><thead><tr>{block.rows[0].map((cell, cellIndex) => <th key={cellIndex}><InlineMarkdown text={cell} onOpenDocument={onOpenDocument} /></th>)}</tr></thead><tbody>{block.rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}><InlineMarkdown text={cell} onOpenDocument={onOpenDocument} /></td>)}</tr>)}</tbody></table></div>;
    const line = block.content; const index = block.index;
    if (index === firstContentIndex && line.startsWith('# ') && line.slice(2).trim() === pageTitle.trim()) return null;
    const content = <InlineMarkdown text={line.replace(/^#{1,3}\s+|^[-*]\s+|^>\s+/, '')} onOpenDocument={onOpenDocument} />;
    const headingId = `knowledge-heading-${index}`;
    if (line.startsWith('### ')) return <h3 id={headingId} key={index}>{content}</h3>;
    if (line.startsWith('## ')) return <h2 id={headingId} key={index}>{content}</h2>;
    if (line.startsWith('# ')) return <h1 id={headingId} key={index}>{content}</h1>;
    if (line.startsWith('> ')) return <blockquote key={index}>{content}</blockquote>;
    const task = line.match(/^[-*]\s+\[([ xX])\]\s+(.+)/);
    if (task) return <label className="knowledge-task-line" key={index}><input type="checkbox" checked={task[1].toLowerCase() === 'x'} readOnly /><span><InlineMarkdown text={task[2]} onOpenDocument={onOpenDocument} /></span></label>;
    if (/^[-*]\s+/.test(line)) return <div className="knowledge-list-line" key={index}>• {content}</div>;
    const ordered = line.match(/^\d+\.\s+(.+)/);
    if (ordered) return <div className="knowledge-list-line ordered" key={index}><b>{line.match(/^\d+/)?.[0]}.</b> <InlineMarkdown text={ordered[1]} onOpenDocument={onOpenDocument} /></div>;
    if (/^---+$/.test(line.trim())) return <hr key={index} />;
    if (!line.trim()) return <div className="knowledge-paragraph-gap" key={index} />;
    return <p key={index}>{content}</p>;
  })}</div>;
}

function PageOutline({ body, pageTitle = '' }) {
  const headings = String(body || '').split('\n').map((line, index) => {
    const match = line.match(/^(#{1,3})\s+(.+)/);
    const label = match?.[2].replace(/[*`]/g, '') || '';
    return match && label !== pageTitle ? { id: `knowledge-heading-${index}`, level: match[1].length, label } : null;
  }).filter(Boolean);
  if (!headings.length) return <p className="knowledge-outline-empty">Add headings to create page navigation.</p>;
  return <nav className="knowledge-outline" aria-label="On this page">{headings.map((heading) => <button
    className={`level-${heading.level}`} key={heading.id} onClick={() => window.document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
    {heading.label}
  </button>)}</nav>;
}

function StatusBadge({ document }) {
  const warning = document.expired ? 'Expired' : document.review_overdue ? 'Review due' : document.status;
  return <span className={`knowledge-status ${document.expired || document.review_overdue ? 'warning' : document.status}`}>{warning}</span>;
}

function PageTree({ documents, selectedId, onOpen }) {
  const ids = new Set(documents.map((item) => item.id));
  const children = new Map();
  documents.forEach((item) => {
    const parent = item.parent_id && ids.has(item.parent_id) ? item.parent_id : 'root';
    children.set(parent, [...(children.get(parent) || []), item]);
  });
  children.forEach((items) => items.sort((left, right) => (left.position || 0) - (right.position || 0) || left.title.localeCompare(right.title)));
  const branch = (parent = 'root', level = 0) => (children.get(parent) || []).map((item) => <div className="knowledge-tree-branch" key={item.id}>
    <button className={selectedId === item.id ? 'active' : ''} style={{ '--tree-level': level }} onClick={() => onOpen(item.id)}>
      <i>{item.icon || '▤'}</i><span>{item.title}</span>{children.has(item.id) && <b>{children.get(item.id).length}</b>}
    </button>
    {branch(item.id, level + 1)}
  </div>);
  return <div className="knowledge-page-tree">{branch()}</div>;
}

function downloadText(filename, type, content) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function KnowledgeManagement({ user, onNavigate, navigationKey = window.location.search }) {
  const [overview, setOverview] = useState({ spaces: [], documents: [], templates: [], counts: {} });
  const [members, setMembers] = useState([user]);
  const [state, setState] = useState('loading');
  const [search, setSearch] = useState('');
  const [spaceId, setSpaceId] = useState('');
  const [selectedId, setSelectedId] = useState(documentFromQuery);
  const [document, setDocument] = useState(null);
  const [editor, setEditor] = useState(EMPTY_EDITOR);
  const [tab, setTab] = useState('content');
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState(false);
  const [dialog, setDialog] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [comment, setComment] = useState('');
  const [replyTo, setReplyTo] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const [labelFilter, setLabelFilter] = useState('');
  const [documentLimit, setDocumentLimit] = useState(20);
  const [draftAvailable, setDraftAvailable] = useState(null);
  const [compareData, setCompareData] = useState(null);
  const [spaceForm, setSpaceForm] = useState({ name: '', description: '', visibility: 'workspace', memberIds: [] });
  const [newDoc, setNewDoc] = useState({ ...EMPTY_EDITOR, space_id: '' });
  const [accessIds, setAccessIds] = useState([]);
  const [accessRoles, setAccessRoles] = useState({});
  const [favoriteIds, setFavoriteIds] = useState(() => {
    try { return JSON.parse(localStorage.getItem('workspace:knowledge:favorites') || '[]'); } catch { return []; }
  });
  const editorRef = useRef(null);

  const reloadOverview = async (nextSpace = spaceId, nextSearch = search, archived = showArchived) => {
    setState('loading');
    try {
      const result = await getKnowledgeOverview({ search: nextSearch, spaceId: nextSpace, includeArchived: archived });
      setOverview(result);
      setState('ready');
      return result;
    } catch (requestError) {
      setError(requestError.message);
      setState('error');
      return null;
    }
  };

  useEffect(() => {
    reloadOverview('', '');
    getCommunicationOverview().then((result) => {
      const people = [user, ...(result.contacts || []).map((item) => item.user)];
      setMembers(Array.from(new Map(people.map((item) => [item.id, item])).values()));
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);

  useEffect(() => {
    const timer = window.setTimeout(() => reloadOverview(spaceId, search), 250);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, spaceId, showArchived]);

  const openDocument = async (id) => {
    if (!id) return;
    setSelectedId(id);
    setError('');
    setDocument(null);
    setEditing(false);
    setTab('content');
    const url = new URL(window.location.href);
    url.pathname = '/knowledge';
    url.searchParams.set('document', id);
    window.history.pushState({}, '', `${url.pathname}${url.search}`);
    try {
      const result = await getKnowledgeDocument(id);
      setDocument(result);
      setSpaceId(result.space_id || '');
      setEditor({
        title: result.title, summary: result.summary || '', body: result.body || '', status: result.status,
        visibility: result.visibility, classification: result.classification, template: result.template,
        owner_id: result.owner?.id || '', space_id: result.space_id, parent_id: result.parent_id || '',
        icon: result.icon || '▤', labels: (result.labels || []).join(', '),
        review_due_at: result.review_due_at || '', expires_at: result.expires_at || '',
      });
      const entries = result.access || [];
      setAccessIds(entries.map((item) => item.user.id));
      setAccessRoles(Object.fromEntries(entries.map((item) => [item.user.id, item.role])));
    } catch (requestError) {
      setError(requestError.message);
      setSelectedId('');
    }
  };

  useEffect(() => { if (selectedId) openDocument(selectedId); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const closeDocument = () => {
    setSelectedId('');
    setDocument(null);
    setEditing(false);
    window.history.pushState({}, '', '/knowledge');
  };

  const beginEditing = () => {
    try {
      const draft = JSON.parse(localStorage.getItem(`workspace:knowledge:draft:${document.id}`) || 'null');
      if (draft?.revision === document.revision && draft.editor?.body !== editor.body) setDraftAvailable(draft);
      else { setDraftAvailable(null); setEditing(true); }
    } catch { setEditing(true); }
  };

  useEffect(() => {
    if (!editing || !document) return undefined;
    const timer = window.setTimeout(() => localStorage.setItem(
      `workspace:knowledge:draft:${document.id}`,
      JSON.stringify({ revision: document.revision, editor, savedAt: new Date().toISOString() }),
    ), 600);
    return () => window.clearTimeout(timer);
  }, [editing, document, editor]);

  const saveDocument = async () => {
    if (!document || !editor.title.trim()) return;
    setSaving(true);
    setError('');
    try {
      const updated = await updateKnowledgeDocument(document.id, {
        expected_revision: document.revision, title: editor.title, summary: editor.summary, body: editor.body,
        space_id: editor.space_id, parent_id: editor.parent_id || null, icon: editor.icon || '▤',
        labels: editor.labels.split(',').map((item) => item.trim()).filter(Boolean),
        status: editor.status, visibility: editor.visibility, classification: editor.classification,
        owner_id: editor.owner_id, review_due_at: editor.review_due_at || null,
        expires_at: editor.expires_at || null, change_summary: 'Updated in knowledge editor',
      });
      setDocument(updated);
      setEditing(false);
      localStorage.removeItem(`workspace:knowledge:draft:${document.id}`);
      await reloadOverview();
    } catch (requestError) {
      setError(requestError.status === 409 ? 'Another person saved this document. Reopen it to review their version before saving yours.' : requestError.message);
    } finally { setSaving(false); }
  };

  const makeSpace = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const created = await createKnowledgeSpace({
        name: spaceForm.name, description: spaceForm.description, visibility: spaceForm.visibility,
        members: spaceForm.memberIds.map((id) => ({ user_id: id, role: 'editor' })),
      });
      setDialog('');
      setSpaceForm({ name: '', description: '', visibility: 'workspace', memberIds: [] });
      await reloadOverview(created.id, '');
      setSpaceId(created.id);
    } catch (requestError) { setError(requestError.message); } finally { setSaving(false); }
  };

  const makeDocument = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const template = overview.templates.find((item) => item.id === newDoc.template);
      const created = await createKnowledgeDocument({
        space_id: newDoc.space_id, title: newDoc.title, summary: newDoc.summary, body: newDoc.body || template?.body || '',
        parent_id: newDoc.parent_id || null, icon: newDoc.icon || '▤',
        labels: newDoc.labels.split(',').map((item) => item.trim()).filter(Boolean),
        status: newDoc.status, visibility: newDoc.visibility, classification: newDoc.classification,
        template: newDoc.template, owner_id: newDoc.owner_id || user.id,
        review_due_at: newDoc.review_due_at || null, expires_at: newDoc.expires_at || null,
      });
      setDialog('');
      setNewDoc({ ...EMPTY_EDITOR, space_id: '' });
      await reloadOverview();
      await openDocument(created.id);
    } catch (requestError) { setError(requestError.message); } finally { setSaving(false); }
  };

  const postComment = async () => {
    if (!comment.trim() || !document) return;
    setSaving(true);
    try {
      await addKnowledgeComment(document.id, comment, replyTo?.id || null);
      setComment('');
      setReplyTo(null);
      await openDocument(document.id);
      setTab('comments');
    } catch (requestError) { setError(requestError.message); } finally { setSaving(false); }
  };

  const saveAccess = async () => {
    setSaving(true);
    try {
      const updated = await updateKnowledgeAccess(document.id, accessIds.map((id) => ({ user_id: id, role: accessRoles[id] || 'viewer' })));
      setDocument(updated);
    } catch (requestError) { setError(requestError.message); } finally { setSaving(false); }
  };

  const visibleMembers = useMemo(() => members.filter((item) => item.id !== document?.owner?.id), [members, document]);
  const selectedSpace = overview.spaces.find((item) => item.id === spaceId);
  const labels = useMemo(() => Array.from(new Set(overview.documents.flatMap((item) => item.labels || []))).sort(), [overview.documents]);
  const visibleDocuments = useMemo(() => labelFilter ? overview.documents.filter((item) => (item.labels || []).includes(labelFilter)) : overview.documents, [overview.documents, labelFilter]);
  const listedDocuments = visibleDocuments.slice(0, documentLimit);

  const startDocument = (template = 'blank') => {
    setNewDoc({ ...EMPTY_EDITOR, template, owner_id: user.id, space_id: spaceId || overview.spaces[0]?.id || '' });
    setDialog('document');
  };

  useEffect(() => {
    if (!overview.spaces.length) return;
    const params = new URLSearchParams(navigationKey);
    if (params.get('create') === '1') {
      params.delete('create');
      window.history.replaceState({}, '', `/knowledge${params.toString() ? `?${params}` : ''}`);
      startDocument();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigationKey, overview.spaces.length]);

  const toggleFavorite = (id) => {
    const next = favoriteIds.includes(id) ? favoriteIds.filter((item) => item !== id) : [...favoriteIds, id];
    setFavoriteIds(next);
    localStorage.setItem('workspace:knowledge:favorites', JSON.stringify(next));
  };

  const insertMarkdown = (before, after = '', fallback = 'text') => {
    const textarea = editorRef.current;
    const start = textarea?.selectionStart ?? editor.body.length;
    const end = textarea?.selectionEnd ?? editor.body.length;
    const selected = editor.body.slice(start, end) || fallback;
    const body = `${editor.body.slice(0, start)}${before}${selected}${after}${editor.body.slice(end)}`;
    setEditor({ ...editor, body });
    window.requestAnimationFrame(() => {
      textarea?.focus();
      const cursor = start + before.length + selected.length + after.length;
      textarea?.setSelectionRange(cursor, cursor);
    });
  };

  const toggleFollow = async () => {
    try { setDocument(await followKnowledgeDocument(document.id, !document.following)); }
    catch (requestError) { setError(requestError.message); }
  };

  const copyDocument = async () => {
    setSaving(true);
    try {
      const copy = await duplicateKnowledgeDocument(document.id);
      await reloadOverview();
      await openDocument(copy.id);
    } catch (requestError) { setError(requestError.message); } finally { setSaving(false); }
  };

  const archiveDocument = async () => {
    const nextStatus = document.status === 'archived' ? 'draft' : 'archived';
    if (nextStatus === 'archived' && !window.confirm('Archive this page? It will be hidden from normal page lists, but its history and links will be preserved.')) return;
    try {
      const updated = await updateKnowledgeDocument(document.id, {
        expected_revision: document.revision, status: nextStatus,
        change_summary: nextStatus === 'archived' ? 'Page archived' : 'Page restored from archive',
      });
      setDocument(updated);
      await reloadOverview();
    } catch (requestError) { setError(requestError.message); }
  };

  const updateCurrentSpace = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      await updateKnowledgeSpace(selectedSpace.id, {
        name: spaceForm.name, description: spaceForm.description, visibility: spaceForm.visibility,
      });
      setDialog(''); await reloadOverview();
    } catch (requestError) { setError(requestError.message); } finally { setSaving(false); }
  };

  return <main id="workspace-main" className="knowledge-shell">
    <WorkspaceTopNav active="knowledge" onNavigate={onNavigate} role={user.role}
      actions={<button className="button primary" disabled={!overview.spaces.length} onClick={() => startDocument()}>+ Create</button>} />
    <section className="knowledge-layout confluence-layout">
      <aside className="knowledge-sidebar confluence-sidebar">
        <header><button className="knowledge-brand" onClick={() => { setSpaceId(''); closeDocument(); }}><span>▤</span><div><small>Workspace</small><h1>Knowledge</h1></div></button>
          {user.role === 'admin' && <button aria-label="Create space" title="Create space" onClick={() => setDialog('space')}>+</button>}</header>
        <label className="knowledge-side-search"><span>⌕</span><input type="search" aria-label="Search knowledge" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search knowledge" /></label>
        <button className={!spaceId && !selectedId ? 'active' : ''} onClick={() => { setSpaceId(''); closeDocument(); }}><span><i>⌂</i>Knowledge home</span></button>
        {!!favoriteIds.length && <><p>Favorites</p><PageTree documents={overview.documents.filter((item) => favoriteIds.includes(item.id))} selectedId={selectedId} onOpen={openDocument} /></>}
        <p>Spaces</p>
        <div className="knowledge-space-list">{overview.spaces.map((space) => <React.Fragment key={space.id}>
          <button className={spaceId === space.id ? 'active' : ''} onClick={() => { setSpaceId(space.id); closeDocument(); }}>
            <span><i>{space.visibility === 'restricted' ? '⌾' : space.name.slice(0, 1).toUpperCase()}</i>{space.name}</span><b>{space.document_count}</b>
          </button>
          {spaceId === space.id && <PageTree documents={visibleDocuments} selectedId={selectedId} onOpen={openDocument} />}
        </React.Fragment>)}</div>
        {!overview.spaces.length && state === 'ready' && <div className="knowledge-sidebar-empty">Create a space to organize your team’s pages.</div>}
        <footer><span><b>{overview.counts.needs_review || 0}</b> reviews due</span><span><b>{overview.counts.expired || 0}</b> expired</span></footer>
      </aside>

      <section className={`knowledge-main ${selectedId ? 'document-open' : ''}`}>
        {error && <div className="notice error knowledge-error"><strong>Knowledge couldn’t complete that action</strong><span>{error}</span><button onClick={() => setError('')}>Dismiss</button></div>}
        {selectedId && !document && <div className="knowledge-empty">Loading page…</div>}
        {!selectedId && <>
          <header className="knowledge-home-header"><div><span className="eyebrow">Company knowledge</span><h1>{selectedSpace?.name || 'Knowledge home'}</h1><p>{selectedSpace?.description || 'Find answers, document decisions, and keep your team aligned in one shared source of truth.'}</p></div>
            <div className="knowledge-home-actions">{selectedSpace && ['admin', 'owner'].includes(selectedSpace.current_user_access) && <button className="button secondary" onClick={() => { setSpaceForm({ name: selectedSpace.name, description: selectedSpace.description || '', visibility: selectedSpace.visibility, memberIds: [] }); setDialog('space-settings'); }}>Space settings</button>}<button className="button primary" disabled={!overview.spaces.length} onClick={() => startDocument()}>Create a page</button></div></header>
          <section className="knowledge-metrics" aria-label="Knowledge overview"><article><b>{overview.counts.documents || 0}</b><span>Pages</span></article><article><b>{overview.counts.published || 0}</b><span>Published</span></article><article><b>{overview.counts.drafts || 0}</b><span>Drafts</span></article><article><b>{overview.counts.needs_review || 0}</b><span>Reviews due</span></article></section>
          {!!overview.templates.length && <section className="knowledge-template-section"><div className="knowledge-section-heading"><div><h2>Start with a template</h2><p>Move faster with a structure your team can reuse.</p></div></div>
            <div className="knowledge-template-grid">{overview.templates.slice(0, 8).map((item) => <button key={item.id} onClick={() => startDocument(item.id)}><span>{item.id === 'blank' ? '＋' : '▤'}</span><div><strong>{item.name}</strong><small>{item.description || 'Start a focused team page'}</small></div></button>)}</div>
          </section>}
          <section className="knowledge-recent-section"><div className="knowledge-section-heading"><div><h2>{selectedSpace ? 'Pages in this space' : 'Recently updated'}</h2><p>{visibleDocuments.length} page{visibleDocuments.length === 1 ? '' : 's'} available to you</p></div><div className="knowledge-list-filters"><select aria-label="Filter by label" value={labelFilter} onChange={(event) => { setLabelFilter(event.target.value); setDocumentLimit(20); }}><option value="">All labels</option>{labels.map((label) => <option key={label} value={label}>{label}</option>)}</select><label><input type="checkbox" checked={showArchived} onChange={(event) => { setShowArchived(event.target.checked); setDocumentLimit(20); }} /> Show archived</label></div></div>
            {state === 'loading' && <div className="knowledge-empty compact">Loading knowledge…</div>}
            {state === 'ready' && !overview.documents.length && <div className="knowledge-empty compact"><span>▤</span><h2>No pages here yet</h2><p>Capture decisions, procedures, policies, and project context around your work.</p>{overview.spaces.length ? <button className="button primary" onClick={() => startDocument()}>Create page</button> : user.role === 'admin' && <button className="button primary" onClick={() => setDialog('space')}>Create first space</button>}</div>}
            {!!visibleDocuments.length && <div className="knowledge-page-list">{listedDocuments.map((item) => <button key={item.id} onClick={() => openDocument(item.id)}>
              <span className="knowledge-page-icon">{item.icon || '▤'}</span><span className="knowledge-page-description"><strong>{item.title}</strong><small>{item.summary || 'No summary added.'}</small>{!!item.labels?.length && <em>{item.labels.slice(0, 3).join(' · ')}</em>}</span>
              <span className="knowledge-page-space">{item.space_name}</span><span className="knowledge-page-owner">{item.owner?.display_name || 'Unassigned'}</span><time>{timeLabel(item.updated_at)}</time><StatusBadge document={item} />
            </button>)}{visibleDocuments.length > documentLimit && <button className="knowledge-load-more" onClick={() => setDocumentLimit((value) => value + 20)}>Show {Math.min(20, visibleDocuments.length - documentLimit)} more pages</button>}</div>}
          </section>
        </>}

        {document && <article className="knowledge-document-page" aria-label="Knowledge document">
          <header className="knowledge-page-chrome"><nav aria-label="Breadcrumb"><button onClick={() => { setSpaceId(''); closeDocument(); }}>Knowledge</button><span>/</span><button onClick={() => { setSpaceId(document.space_id); closeDocument(); }}>{document.space_name}</button><span>/</span><b>{document.title}</b></nav><div>
            <button className={`knowledge-star ${favoriteIds.includes(document.id) ? 'active' : ''}`} aria-label={favoriteIds.includes(document.id) ? 'Remove from favorites' : 'Add to favorites'} onClick={() => toggleFavorite(document.id)}>{favoriteIds.includes(document.id) ? '★' : '☆'}</button>
            <button className={`button secondary ${document.following ? 'active' : ''}`} onClick={toggleFollow}>{document.following ? 'Following' : 'Follow'}</button>
            <button className="button secondary" onClick={() => setTab('comments')}>Comments {document.comments.length}</button>
            {!editing && <details className="knowledge-more-menu"><summary aria-label="Page actions">•••</summary><div><button onClick={copyDocument}>Copy page</button><button onClick={() => downloadText(`${document.slug || 'page'}.md`, 'text/markdown', `# ${document.title}\n\n${document.body}`)}>Export Markdown</button><button onClick={() => window.print()}>Print / PDF</button>{document.can_edit && <button onClick={archiveDocument}>{document.status === 'archived' ? 'Restore page' : 'Archive page'}</button>}</div></details>}
            {document.can_edit && !editing && <button className="button primary" onClick={beginEditing}>Edit</button>}
            {editing && <><button className="button secondary" onClick={() => setEditing(false)}>Cancel</button><button className="button primary" disabled={saving} onClick={saveDocument}>{saving ? 'Saving…' : 'Save'}</button></>}
          </div></header>
          {draftAvailable && !editing && <div className="knowledge-draft-banner"><span><b>Unsaved draft found</b> from {timeLabel(draftAvailable.savedAt)}</span><button onClick={() => { localStorage.removeItem(`workspace:knowledge:draft:${document.id}`); setDraftAvailable(null); setEditing(true); }}>Discard</button><button className="button primary" onClick={() => { setEditor(draftAvailable.editor); setDraftAvailable(null); setEditing(true); }}>Recover draft</button></div>}
          {editing ? <div className="knowledge-editor confluence-editor">
            <input className="knowledge-title-input" aria-label="Document title" value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} />
            <input className="knowledge-summary-input" aria-label="Document summary" placeholder="Add a concise summary" value={editor.summary} onChange={(event) => setEditor({ ...editor, summary: event.target.value })} />
            <div className="knowledge-format-toolbar" aria-label="Formatting toolbar"><button type="button" title="Heading" onClick={() => insertMarkdown('## ', '', 'Heading')}>H2</button><button type="button" title="Bold" onClick={() => insertMarkdown('**', '**')}>B</button><button type="button" title="Italic" onClick={() => insertMarkdown('_', '_')}>I</button><button type="button" title="Inline code" onClick={() => insertMarkdown('`', '`', 'code')}>{'<>'}</button><button type="button" title="Bulleted list" onClick={() => insertMarkdown('- ', '', 'List item')}>☷</button><button type="button" title="Task" onClick={() => insertMarkdown('- [ ] ', '', 'Action item')}>☑</button><button type="button" title="Quote" onClick={() => insertMarkdown('> ', '', 'Quote')}>❝</button><button type="button" title="Table" onClick={() => insertMarkdown('| Column 1 | Column 2 |\n| --- | --- |\n| ', ' | Value |', 'Value')}>Table</button><button type="button" title="Information panel" onClick={() => insertMarkdown(':::info Helpful context\n', '\n:::', 'Add information')}>Panel</button><button type="button" title="Expandable section" onClick={() => insertMarkdown(':::expand Details\n', '\n:::', 'Hidden details')}>Expand</button><span />
              <button className={!preview ? 'active' : ''} type="button" onClick={() => setPreview(false)}>Write</button><button className={preview ? 'active' : ''} type="button" onClick={() => setPreview(true)}>Preview</button></div>
            {preview ? <MarkdownPreview body={editor.body} pageTitle={editor.title} onOpenDocument={openDocument} /> : <textarea ref={editorRef} aria-label="Document content" value={editor.body} onChange={(event) => setEditor({ ...editor, body: event.target.value })} placeholder="Start writing, or use Markdown shortcuts…" />}
            <details className="knowledge-page-settings"><summary>Page settings and governance</summary><section className="knowledge-metadata-grid">
              <label>Status<select value={editor.status} onChange={(event) => setEditor({ ...editor, status: event.target.value })}><option value="draft">Draft</option><option value="published">Published</option><option value="archived">Archived</option></select></label>
              <label>Visibility<select value={editor.visibility} onChange={(event) => setEditor({ ...editor, visibility: event.target.value })}><option value="workspace">Workspace</option><option value="restricted">Restricted</option></select></label>
              <label>Classification<select value={editor.classification} onChange={(event) => setEditor({ ...editor, classification: event.target.value })}><option value="public">Public</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option></select></label>
              <label>Space<select value={editor.space_id} onChange={(event) => setEditor({ ...editor, space_id: event.target.value, parent_id: '' })}>{overview.spaces.filter((item) => ['admin', 'owner', 'editor'].includes(item.current_user_access)).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <label>Parent page<select value={editor.parent_id} onChange={(event) => setEditor({ ...editor, parent_id: event.target.value })}><option value="">Top level</option>{overview.documents.filter((item) => item.space_id === editor.space_id && item.id !== document.id).map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
              <label>Page icon<input maxLength="16" value={editor.icon} onChange={(event) => setEditor({ ...editor, icon: event.target.value })} /></label>
              <label>Labels<input placeholder="policy, onboarding" value={editor.labels} onChange={(event) => setEditor({ ...editor, labels: event.target.value })} /></label>
              <UserSelect users={members} value={editor.owner_id} onChange={(owner_id) => setEditor({ ...editor, owner_id })} label="Owner" />
              <label>Review date<input type="date" value={editor.review_due_at} onChange={(event) => setEditor({ ...editor, review_due_at: event.target.value })} /></label>
              <label>Expiry date<input type="date" value={editor.expires_at} onChange={(event) => setEditor({ ...editor, expires_at: event.target.value })} /></label>
            </section></details>
          </div> : <>
            <nav className="knowledge-tabs">{['content', 'comments', 'history', 'access', 'backlinks'].map((item) => <button className={tab === item ? 'active' : ''} key={item} onClick={() => setTab(item)}>{item === 'backlinks' ? 'Related pages' : item}{item === 'comments' ? ` ${document.comments.length}` : ''}</button>)}</nav>
            <div className={`knowledge-document-body ${tab === 'content' ? 'with-outline' : ''}`}>
              <section className="knowledge-page-content">
                {tab === 'content' && <><div className="knowledge-page-title-row"><div><span className="knowledge-document-icon">{document.icon || '▤'}</span><h1>{document.title}</h1>{document.summary && <p className="knowledge-document-summary">{document.summary}</p>}</div><StatusBadge document={document} /></div>{!!document.labels?.length && <div className="knowledge-labels">{document.labels.map((item) => <button key={item} onClick={() => { setLabelFilter(item); closeDocument(); }}>#{item}</button>)}</div>}<div className="knowledge-byline"><span>{document.owner?.display_name?.split(' ').map((item) => item[0]).join('') || '?'}</span><p>By <b>{document.owner?.display_name || 'Unassigned'}</b><small>Updated {timeLabel(document.updated_at)} · {document.revision} version{document.revision === 1 ? '' : 's'} · {document.watchers?.length || 0} follower{document.watchers?.length === 1 ? '' : 's'}</small></p></div><MarkdownPreview body={document.body} pageTitle={document.title} onOpenDocument={openDocument} /></>}
                {tab === 'comments' && <section className="knowledge-comments"><header><h2>Comments</h2><p>Discuss this page without losing the context.</p></header>
                  {document.comments.map((item) => <article className={`${item.resolved ? 'resolved' : ''} ${item.parent_id ? 'reply' : ''}`} key={item.id}><header><b>{item.author.display_name}</b><span>@{item.author.handle} · {timeLabel(item.created_at)}</span></header>{item.parent_id && <small className="knowledge-reply-context">Reply in thread</small>}<p><InlineMarkdown text={item.body} onOpenDocument={openDocument} /></p><footer><button onClick={() => { setReplyTo(item); setComment(`@${item.author.handle} `); }}>Reply</button>{(document.can_edit || item.author.id === user.id) && <button onClick={async () => { await resolveKnowledgeComment(document.id, item.id); await openDocument(document.id); setTab('comments'); }}>{item.resolved ? 'Reopen' : 'Resolve'}</button>}</footer></article>)}
                  {!document.comments.length && <div className="knowledge-tab-empty">No comments yet. Use @username to notify a workspace member.</div>}
                  {document.can_comment && <div className="knowledge-comment-composer">{replyTo && <div className="knowledge-reply-banner"><span>Replying to <b>{replyTo.author.display_name}</b></span><button onClick={() => setReplyTo(null)}>×</button></div>}<textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add feedback or mention @username" /><small>{members.slice(0, 4).map((item) => `@${item.handle}`).join(' · ')}</small><button className="button primary" disabled={!comment.trim() || saving} onClick={postComment}>{replyTo ? 'Reply' : 'Comment'}</button></div>}
                </section>}
                {tab === 'history' && <section className="knowledge-history"><header><h2>Page history</h2><p>Compare or restore any previous version.</p></header>{compareData && <section className="knowledge-version-compare"><header><div><b>Version {compareData.version}</b><small>{compareData.change_summary}</small></div><span>compared with</span><div><b>Current version {document.revision}</b><small>Latest saved page</small></div><button onClick={() => setCompareData(null)}>×</button></header><div><article><h3>{compareData.title}</h3><MarkdownPreview body={compareData.body} pageTitle={compareData.title} onOpenDocument={openDocument} /></article><article><h3>{document.title}</h3><MarkdownPreview body={document.body} pageTitle={document.title} onOpenDocument={openDocument} /></article></div></section>}{document.revisions.map((item) => <article key={item.id}><span><b>Version {item.version}</b><small>{item.change_summary} · {item.created_by.display_name} · {timeLabel(item.created_at)}</small></span><div><button onClick={async () => setCompareData(await getKnowledgeRevision(document.id, item.id))}>Compare</button>{document.can_edit && item.version !== document.revisions[0]?.version && <button onClick={async () => { const restored = await restoreKnowledgeRevision(document.id, item.id, document.revision); setDocument(restored); }}>Restore</button>}</div></article>)}</section>}
                {tab === 'access' && <section className="knowledge-access"><h2>Page access</h2><p>{document.visibility === 'workspace' ? 'Everyone with access to this space can view this page. Add people for elevated access.' : 'Only the owner, admins, and people below can access this restricted page.'}</p>{document.can_manage ? <><UserMultiSelect users={visibleMembers} value={accessIds} onChange={(ids) => { setAccessIds(ids); setAccessRoles((current) => ({ ...Object.fromEntries(ids.map((id) => [id, current[id] || 'viewer'])) })); }} label="People with access" />{accessIds.map((id) => <label className="knowledge-role-row" key={id}><span>{members.find((item) => item.id === id)?.display_name}</span><select value={accessRoles[id] || 'viewer'} onChange={(event) => setAccessRoles({ ...accessRoles, [id]: event.target.value })}><option value="viewer">Can view</option><option value="commenter">Can comment</option><option value="editor">Can edit</option></select></label>)}<button className="button primary" disabled={saving} onClick={saveAccess}>Save access</button></> : <div className="knowledge-access-list">{document.access.map((item) => <span key={item.user.id}><b>{item.user.display_name}</b>{item.role}</span>)}</div>}</section>}
                {tab === 'backlinks' && <section className="knowledge-links"><h2>Related pages</h2><p>See how this page connects to the rest of your company knowledge.</p><h3>Links from this page</h3>{document.outbound_links.map((item) => <button key={item.id} onClick={() => openDocument(item.id)}>↗ {item.title}</button>)}{!document.outbound_links.length && <p>No outbound links.</p>}<h3>Pages linking here</h3>{document.backlinks.map((item) => <button key={item.id} onClick={() => openDocument(item.id)}>↩ {item.title}</button>)}{!document.backlinks.length && <p>No backlinks yet.</p>}</section>}
              </section>
              {tab === 'content' && <aside className="knowledge-context-panel"><section><h3>On this page</h3><PageOutline body={document.body} pageTitle={document.title} /></section><section><h3>Page details</h3><dl><div><dt>Owner</dt><dd>{document.owner?.display_name}</dd></div><div><dt>Classification</dt><dd>{document.classification}</dd></div><div><dt>Location</dt><dd>{document.parent_id ? 'Child page' : 'Top level'}</dd></div><div><dt>Followers</dt><dd>{document.watchers?.length || 0}</dd></div><div><dt>Review</dt><dd>{dateLabel(document.review_due_at)}</dd></div><div><dt>Expiry</dt><dd>{dateLabel(document.expires_at)}</dd></div></dl></section></aside>}
            </div>
          </>}
        </article>}
      </section>
    </section>

    {dialog && <div className="knowledge-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(''); }}><form className="knowledge-dialog" onSubmit={dialog === 'space' ? makeSpace : dialog === 'space-settings' ? updateCurrentSpace : makeDocument}>
      <header><div><span className="eyebrow">{dialog.startsWith('space') ? 'Knowledge space' : 'New knowledge'}</span><h2>{dialog === 'space' ? 'Create a space' : dialog === 'space-settings' ? 'Space settings' : 'Create a document'}</h2></div><button type="button" onClick={() => setDialog('')}>×</button></header>
      {dialog.startsWith('space') ? <>
        <label>Name<input autoFocus required value={spaceForm.name} onChange={(event) => setSpaceForm({ ...spaceForm, name: event.target.value })} /></label>
        <label>Description<textarea value={spaceForm.description} onChange={(event) => setSpaceForm({ ...spaceForm, description: event.target.value })} /></label>
        <label>Visibility<select value={spaceForm.visibility} onChange={(event) => setSpaceForm({ ...spaceForm, visibility: event.target.value })}><option value="workspace">Workspace</option><option value="restricted">Restricted</option></select></label>
        {dialog === 'space' && <UserMultiSelect users={members.filter((item) => item.id !== user.id)} value={spaceForm.memberIds} onChange={(memberIds) => setSpaceForm({ ...spaceForm, memberIds })} label="Space editors" />}
      </> : <>
        <label>Title<input autoFocus required value={newDoc.title} onChange={(event) => setNewDoc({ ...newDoc, title: event.target.value })} /></label>
        <label>Space<select required value={newDoc.space_id} onChange={(event) => setNewDoc({ ...newDoc, space_id: event.target.value, parent_id: '' })}><option value="">Select a space</option>{overview.spaces.filter((item) => ['admin', 'owner', 'editor'].includes(item.current_user_access)).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        <label>Parent page<select value={newDoc.parent_id} onChange={(event) => setNewDoc({ ...newDoc, parent_id: event.target.value })}><option value="">Top level</option>{overview.documents.filter((item) => item.space_id === newDoc.space_id).map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select><small>Use child pages to create a navigable page tree.</small></label>
        <label>Template<select value={newDoc.template} onChange={(event) => setNewDoc({ ...newDoc, template: event.target.value })}>{overview.templates.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><small>{overview.templates.find((item) => item.id === newDoc.template)?.description}</small></label>
        <label>Summary<textarea value={newDoc.summary} onChange={(event) => setNewDoc({ ...newDoc, summary: event.target.value })} /></label>
        <div className="knowledge-form-grid"><label>Page icon<input maxLength="16" value={newDoc.icon} onChange={(event) => setNewDoc({ ...newDoc, icon: event.target.value })} /></label><label>Labels<input placeholder="policy, onboarding" value={newDoc.labels} onChange={(event) => setNewDoc({ ...newDoc, labels: event.target.value })} /></label></div>
        <div className="knowledge-form-grid"><label>Visibility<select value={newDoc.visibility} onChange={(event) => setNewDoc({ ...newDoc, visibility: event.target.value })}><option value="workspace">Workspace</option><option value="restricted">Restricted</option></select></label><label>Classification<select value={newDoc.classification} onChange={(event) => setNewDoc({ ...newDoc, classification: event.target.value })}><option value="internal">Internal</option><option value="public">Public</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option></select></label></div>
      </>}
      <footer><button type="button" className="button secondary" onClick={() => setDialog('')}>Cancel</button><button className="button primary" disabled={saving}>{saving ? 'Saving…' : dialog === 'space-settings' ? 'Save settings' : 'Create'}</button></footer>
    </form></div>}
  </main>;
}
