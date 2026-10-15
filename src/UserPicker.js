import React, { useEffect, useId, useMemo, useRef, useState } from 'react';

const RESULT_LIMIT = 50;

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function searchableText(user) {
  return [user.display_name, user.email, user.handle, user.role, user.job_title]
    .filter(Boolean).join(' ').toLocaleLowerCase();
}

function userSubtitle(user) {
  if (user.email) return user.email;
  if (user.handle) return `@${user.handle}`;
  return user.job_title || user.role || 'Workspace member';
}

function UserPicker({
  users = [],
  value,
  onChange,
  label,
  ariaLabel,
  placeholder,
  emptyLabel,
  multiple = false,
  requiredIds = [],
  disabled = false,
}) {
  const pickerId = useId();
  const rootRef = useRef(null);
  const searchRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const selectedIds = useMemo(() => (multiple ? value || [] : value ? [value] : []), [multiple, value]);
  const required = useMemo(() => new Set(requiredIds), [requiredIds]);
  const sortedUsers = useMemo(() => [...users]
    .filter((user) => user?.id)
    .sort((first, second) => (first.display_name || '').localeCompare(second.display_name || '')),
  [users]);
  const selectedUsers = useMemo(() => sortedUsers.filter((user) => selectedIds.includes(user.id)),
    [selectedIds, sortedUsers]);
  const matchingUsers = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized ? sortedUsers.filter((user) => searchableText(user).includes(normalized)) : sortedUsers;
  }, [query, sortedUsers]);
  const visibleUsers = matchingUsers.slice(0, RESULT_LIMIT);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutsideClick = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') {
        setOpen(false);
        rootRef.current?.querySelector('[role="combobox"]')?.focus();
      }
    };
    document.addEventListener('mousedown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    searchRef.current?.focus();
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const choose = (userId) => {
    if (multiple) {
      if (selectedIds.includes(userId)) {
        if (!required.has(userId)) onChange(selectedIds.filter((id) => id !== userId));
      } else {
        onChange([...selectedIds, userId]);
      }
      return;
    }
    onChange(userId);
    setOpen(false);
    setQuery('');
  };

  const triggerCopy = multiple
    ? selectedUsers.length ? `${selectedUsers.length} selected` : (placeholder || 'Select people')
    : selectedUsers[0]?.display_name || emptyLabel || placeholder || 'Select a person';

  return <div className={`user-picker-field ${disabled ? 'disabled' : ''}`}>
    {label && <span className="user-picker-label">{label}</span>}
    <div className={`user-picker ${open ? 'open' : ''}`} ref={rootRef}>
      <button type="button" className="user-picker-trigger" role="combobox"
        aria-label={ariaLabel || label} aria-expanded={open} aria-controls={`${pickerId}-options`}
        disabled={disabled} onClick={() => { setOpen((current) => !current); setQuery(''); }}>
        <span className="user-picker-trigger-copy">
          {selectedUsers.length > 0 && <span className="user-picker-avatar-stack" aria-hidden="true">
            {selectedUsers.slice(0, 3).map((user) => <i key={user.id} style={{ '--avatar-color': user.color || '#667085' }}>{initials(user.display_name)}</i>)}
          </span>}
          <span><strong>{triggerCopy}</strong>{!multiple && selectedUsers[0] && <small>{userSubtitle(selectedUsers[0])}</small>}</span>
        </span>
        <span className="user-picker-chevron" aria-hidden="true">⌄</span>
      </button>
      {open && <div className="user-picker-menu">
        <label className="user-picker-search"><span aria-hidden="true">⌕</span>
          <input ref={searchRef} type="search" value={query}
            aria-label={`Search ${ariaLabel || label || 'workspace members'}`}
            onChange={(event) => setQuery(event.target.value)} placeholder="Search name, email, or username…" />
        </label>
        <div className="user-picker-results" id={`${pickerId}-options`} role="listbox" aria-multiselectable={multiple || undefined}>
          {!multiple && emptyLabel && <button type="button" role="option" aria-selected={!value}
            className={`user-picker-option empty ${!value ? 'selected' : ''}`}
            onClick={() => choose('')}><span className="user-picker-empty-avatar">—</span><span><strong>{emptyLabel}</strong><small>Clear assignment</small></span>{!value && <b>✓</b>}</button>}
          {visibleUsers.map((user) => {
            const selected = selectedIds.includes(user.id);
            const locked = multiple && selected && required.has(user.id);
            return <button type="button" role="option" aria-selected={selected} aria-disabled={locked || undefined}
              className={`user-picker-option ${selected ? 'selected' : ''} ${locked ? 'locked' : ''}`}
              key={user.id} onClick={() => choose(user.id)}>
              <span className="user-picker-avatar" style={{ '--avatar-color': user.color || '#667085' }}>{initials(user.display_name)}</span>
              <span><strong>{user.display_name}</strong><small>{userSubtitle(user)}{locked ? ' · Required' : ''}</small></span>
              {selected && <b>✓</b>}
            </button>;
          })}
          {matchingUsers.length === 0 && <div className="user-picker-empty-result"><strong>No people found</strong><span>Try a name, email, username, or role.</span></div>}
        </div>
        <footer><span>{matchingUsers.length > RESULT_LIMIT
          ? `Showing ${RESULT_LIMIT} of ${matchingUsers.length} · Search to narrow`
          : `${matchingUsers.length} ${matchingUsers.length === 1 ? 'person' : 'people'}`}</span>
          {multiple && <button type="button" onClick={() => { setOpen(false); setQuery(''); }}>Done</button>}</footer>
      </div>}
    </div>
  </div>;
}

export function UserSelect(props) {
  return <UserPicker {...props} multiple={false} />;
}

export function UserMultiSelect(props) {
  return <UserPicker {...props} multiple />;
}
