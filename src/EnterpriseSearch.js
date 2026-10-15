import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  clearRecentSearches, createSavedSearch, deleteSavedSearch, getRecentSearches,
  getSavedSearches, searchWorkspace,
} from './searchService';
import { getObjectHistory, getRelatedItems } from './workGraphService';

const SEARCH_TYPES = [
  ['project', 'Projects'], ['work_item', 'Work'], ['document', 'Documents'],
  ['meeting', 'Meetings'], ['decision', 'Decisions'], ['risk', 'Risks'],
  ['release', 'Releases'], ['sprint', 'Sprints'], ['file', 'Files'],
];
const TYPE_ICONS = {
  project: '◇', work_item: '✓', document: '▤', meeting: '◷', decision: '◆',
  risk: '△', release: '🚀', sprint: '↻', file: '▱',
};
const QUICK_COMMANDS = [
  ['⌂', 'Open Home', '/'], ['✓', 'Open Work', '/work'], ['◷', 'Open Calendar', '/calendar'],
  ['◇', 'Open Workflows', '/workflows'], ['▤', 'Open Knowledge', '/knowledge'],
  ['＋', 'Create workflow', '/editor'],
];

function labelForType(type) {
  return SEARCH_TYPES.find(([value]) => value === type)?.[1]?.replace(/s$/, '') || type.replaceAll('_', ' ');
}

function formatDate(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
}

function currentFilters(types, statuses) {
  return { types, statuses };
}

export default function EnterpriseSearch({ onNavigate }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('keyword');
  const [types, setTypes] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [state, setState] = useState('idle');
  const [error, setError] = useState('');
  const [response, setResponse] = useState({ results: [], facets: { types: [], statuses: [], projects: [] }, total: 0 });
  const [selected, setSelected] = useState(null);
  const [related, setRelated] = useState(null);
  const [history, setHistory] = useState([]);
  const [graphDepth, setGraphDepth] = useState(1);
  const [saved, setSaved] = useState([]);
  const [recent, setRecent] = useState([]);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef(null);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    Promise.all([getSavedSearches(), getRecentSearches()])
      .then(([savedItems, recentItems]) => { setSaved(savedItems); setRecent(recentItems); })
      .catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!open || !query.trim()) {
      setState('idle');
      setResponse({ results: [], facets: { types: [], statuses: [], projects: [] }, total: 0 });
      setSelected(null);
      return undefined;
    }
    setState('loading');
    setError('');
    const timer = window.setTimeout(() => {
      searchWorkspace({ query, mode, types, statuses })
        .then((result) => { setResponse(result); setState('ready'); setRecent((items) => items); })
        .catch((requestError) => { setError(requestError.message); setState('error'); });
    }, 280);
    return () => window.clearTimeout(timer);
  }, [open, query, mode, types, statuses]);

  useEffect(() => {
    setActiveIndex(response.results.length ? 0 : -1);
  }, [response.results]);

  useEffect(() => {
    if (!selected) {
      setRelated(null); setHistory([]); return undefined;
    }
    let active = true;
    setRelated(null);
    Promise.all([
      getRelatedItems(selected.type, selected.id, { depth: graphDepth, limit: 80 }),
      getObjectHistory(selected.type, selected.id, 20),
    ]).then(([graph, timeline]) => {
      if (active) { setRelated(graph); setHistory(timeline.events || []); }
    }).catch(() => { if (active) setRelated({ nodes: [], edges: [] }); });
    return () => { active = false; };
  }, [selected, graphDepth]);

  const activeFilters = types.length + statuses.length;
  const groupedRelated = useMemo(() => {
    const result = {};
    (related?.nodes || []).forEach((item) => { (result[item.depth] ||= []).push(item); });
    return result;
  }, [related]);

  const toggleType = (value) => setTypes((current) => current.includes(value)
    ? current.filter((item) => item !== value) : [...current, value]);
  const toggleStatus = (value) => setStatuses((current) => current.includes(value)
    ? current.filter((item) => item !== value) : [...current, value]);

  const runSaved = (item) => {
    setQuery(item.query); setMode(item.mode || 'keyword');
    setTypes(item.filters?.types || []); setStatuses(item.filters?.statuses || []);
  };

  const saveCurrent = async (event) => {
    event.preventDefault();
    if (!saveName.trim()) return;
    setSaving(true);
    try {
      const item = await createSavedSearch({
        name: saveName.trim(), query: query.trim(), mode,
        filters: currentFilters(types, statuses), shared: false,
      });
      setSaved((items) => [item, ...items]);
      setSaveName('');
    } catch (requestError) {
      setError(requestError.message);
    } finally { setSaving(false); }
  };

  const removeSaved = async (event, item) => {
    event.stopPropagation();
    await deleteSavedSearch(item.id);
    setSaved((items) => items.filter((savedItem) => savedItem.id !== item.id));
  };

  const openResult = (item) => {
    if (!item) return;
    setOpen(false);
    onNavigate(item.url);
  };

  const handleSearchKeys = (event) => {
    if (!response.results.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => Math.min(response.results.length - 1, index + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => Math.max(0, index - 1));
    } else if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
      event.preventDefault();
      openResult(response.results[Math.max(0, activeIndex)]);
    }
  };

  return <>
    <button className="global-search-trigger" aria-label="Search workspace" onClick={() => setOpen(true)}>
      <span>⌕</span><strong>Search</strong><kbd>⌘ K</kbd>
    </button>
    {open && <div className="enterprise-search-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setOpen(false);
    }}>
      <section className="enterprise-search-dialog" role="dialog" aria-modal="true" aria-labelledby="enterprise-search-title">
        <header className="enterprise-search-header">
          <div className="enterprise-search-input">
            <span aria-hidden="true">⌕</span>
            <input ref={inputRef} type="search" aria-label="Search everything" value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleSearchKeys} aria-controls="enterprise-search-results"
              aria-activedescendant={activeIndex >= 0 ? `enterprise-search-result-${activeIndex}` : undefined}
              placeholder="Search projects, work, meetings, decisions, documents and risks…" />
            {query && <button aria-label="Clear search" onClick={() => setQuery('')}>×</button>}
          </div>
          <select aria-label="Search mode" value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="keyword">Exact words</option><option value="hybrid">Best match</option><option value="semantic">Meaning</option>
          </select>
          <button className="icon-button" aria-label="Close search" onClick={() => setOpen(false)}>×</button>
        </header>

        <div className="enterprise-search-layout">
          <aside className="enterprise-search-sidebar">
            <section><header><strong>Search in</strong>{activeFilters > 0 && <button onClick={() => { setTypes([]); setStatuses([]); }}>Reset</button>}</header>
              <div className="search-type-list">{SEARCH_TYPES.map(([value, label]) => <button key={value}
                className={types.includes(value) ? 'active' : ''} onClick={() => toggleType(value)}>
                <span>{TYPE_ICONS[value]}</span>{label}
                <small>{response.facets.types.find((item) => item.value === value)?.count || ''}</small>
              </button>)}</div></section>
            {response.facets.statuses.length > 0 && <section><header><strong>Status</strong></header>
              <div className="search-facet-list">{response.facets.statuses.slice(0, 8).map((facet) => <button key={facet.value}
                className={statuses.includes(facet.value) ? 'active' : ''} onClick={() => toggleStatus(facet.value)}>
                <span>{facet.value.replaceAll('_', ' ')}</span><small>{facet.count}</small></button>)}</div></section>}
          </aside>

          <main className="enterprise-search-results">
            {!query.trim() && <div className="search-start">
              <div className="search-start-column"><header><h2 id="enterprise-search-title">Quick actions</h2><span>{QUICK_COMMANDS.length}</span></header>
                {QUICK_COMMANDS.map(([icon, label, path]) => <button className="search-memory-item" key={path} onClick={() => { setOpen(false); onNavigate(path); }}>
                  <span>{icon}</span><div><strong>{label}</strong><small>Workspace command</small></div>
                </button>)}
              </div>
              <div className="search-start-column"><header><h2>Saved searches</h2><span>{saved.length}</span></header>
                {saved.map((item) => <button className="search-memory-item" key={item.id} onClick={() => runSaved(item)}>
                  <span>★</span><div><strong>{item.name}</strong><small>{item.query || 'Filtered workspace view'} · {item.mode}</small></div>
                  {item.can_edit && <i role="button" tabIndex="0" aria-label={`Delete ${item.name}`} onClick={(event) => removeSaved(event, item)}>×</i>}
                </button>)}
                {!saved.length && <p>No saved searches yet.</p>}
              </div>
              <div className="search-start-column"><header><h2>Recent</h2>{recent.length > 0 && <button onClick={async () => { await clearRecentSearches(); setRecent([]); }}>Clear</button>}</header>
                {recent.map((item) => <button className="search-memory-item" key={item.id} onClick={() => runSaved(item)}>
                  <span>↺</span><div><strong>{item.query}</strong><small>{item.result_count} results · {item.mode}</small></div>
                </button>)}
                {!recent.length && <p>Your recent searches will appear here.</p>}
              </div>
            </div>}

            {query.trim() && <>
              <div className="search-results-heading"><div><h2 id="enterprise-search-title">Results</h2>
                <span>{state === 'loading' ? 'Searching…' : `${response.total.toLocaleString()} found`}</span></div>
                <form onSubmit={saveCurrent}><input aria-label="Saved search name" value={saveName}
                  onChange={(event) => setSaveName(event.target.value)} placeholder="Name this search" />
                  <button disabled={saving || !saveName.trim()}>{saving ? 'Saving…' : 'Save'}</button></form></div>
              {state === 'error' && <div className="search-message error" role="alert">{error}</div>}
              {state === 'loading' && <div className="search-message"><span className="spinner dark" /> Searching every permitted workspace object…</div>}
              {state === 'ready' && response.results.length === 0 && <div className="search-empty"><span>⌕</span><h3>No permitted results</h3><p>Try fewer filters, a related term, or Hybrid mode.</p></div>}
              <div id="enterprise-search-results" className="search-result-list" role="list" aria-label="Workspace search results">{response.results.map((item, index) => <button key={`${item.type}:${item.id}`}
                id={`enterprise-search-result-${index}`} aria-current={index === activeIndex ? 'true' : undefined}
                className={(selected?.id === item.id && selected?.type === item.type) || index === activeIndex ? 'selected' : ''}
                onMouseEnter={() => setActiveIndex(index)} onFocus={() => setActiveIndex(index)}
                onClick={() => { setSelected(item); setActiveIndex(index); }} onDoubleClick={() => openResult(item)}>
                <span className={`search-result-icon type-${item.type}`}>{TYPE_ICONS[item.type] || '◇'}</span>
                <div><span><em>{labelForType(item.type)}</em>{item.key && <b>{item.key}</b>}{item.status && <i>{item.status.replaceAll('_', ' ')}</i>}</span>
                  <strong>{item.title}</strong><p>{item.snippet}</p><small>{item.updated_at ? `Updated ${formatDate(item.updated_at)}` : ''}</small></div>
                <span className="search-result-arrow">›</span>
              </button>)}</div>
            </>}
          </main>

          {selected && <aside className="search-preview">
            <header><div><span>{labelForType(selected.type)}</span><h2>{selected.title}</h2>{selected.key && <b>{selected.key}</b>}</div>
              <button aria-label="Close preview" onClick={() => setSelected(null)}>×</button></header>
            <p>{selected.snippet}</p>
            <button className="button primary search-open-result" onClick={() => openResult(selected)}>Open {labelForType(selected.type)}</button>
            <section className="related-items-panel"><header><div><strong>Related items</strong><small>Permission-filtered work graph</small></div>
              <select aria-label="Relationship depth" value={graphDepth} onChange={(event) => setGraphDepth(Number(event.target.value))}>
                <option value="1">1 hop</option><option value="2">2 hops</option><option value="3">3 hops</option>
              </select></header>
              {!related && <div className="related-loading"><span className="spinner dark" /> Loading graph…</div>}
              {related && related.nodes.length === 0 && <p>No related items you can access.</p>}
              {Object.entries(groupedRelated).map(([depth, items]) => <div className="related-depth" key={depth}><small>{depth} {Number(depth) === 1 ? 'hop' : 'hops'} away</small>
                {items.map((item) => <button key={`${item.type}:${item.id}`} onClick={() => setSelected(item)}>
                  <span>{TYPE_ICONS[item.type] || '◇'}</span><div><strong>{item.title}</strong><small>{labelForType(item.type)}{item.status ? ` · ${item.status.replaceAll('_', ' ')}` : ''}</small></div></button>)}</div>)}
              {related?.truncated && <p>More relationships exist. Narrow the relationship types to continue.</p>}
            </section>
            <section className="search-history"><header><strong>Recent history</strong><small>{history.length}</small></header>
              {history.slice(0, 6).map((item) => <div key={item.id}><i /><span><strong>{item.action.replaceAll('.', ' ')}</strong><small>{formatDate(item.created_at)}</small></span></div>)}
              {!history.length && <p>No recorded changes yet.</p>}
            </section>
          </aside>}
        </div>
        <footer className="enterprise-search-footer"><span><kbd>↑</kbd><kbd>↓</kbd> browse</span><span><kbd>enter</kbd> open</span><span><kbd>esc</kbd> close</span>
          <span>Search only returns objects you are allowed to view.</span></footer>
      </section>
    </div>}
  </>;
}
