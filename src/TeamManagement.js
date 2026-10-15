import React, { useEffect, useState } from 'react';
import { useAuth } from './AuthProvider';
import {
  cancelWorkspaceInvitation,
  getWorkspaceTeam,
  inviteWorkspaceMember,
  updateWorkspaceMemberRole,
} from './entityService';

const EMPTY_CONTACT = { display_name: '', email: '', job_title: '', role: 'basic' };

function roleLabel(role) {
  return role === 'admin' ? 'Admin' : role === 'guest' ? 'Guest' : 'Basic user';
}

export default function TeamManagement() {
  const { refresh } = useAuth();
  const [workspace, setWorkspace] = useState(null);
  const [members, setMembers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [contact, setContact] = useState(EMPTY_CONTACT);
  const [state, setState] = useState('loading');
  const [action, setAction] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [setupUrl, setSetupUrl] = useState('');

  const load = () => {
    setState('loading');
    setError('');
    getWorkspaceTeam()
      .then((result) => {
        setWorkspace(result.workspace);
        setMembers(result.workspace_members);
        setInvitations(result.workspace_invitations);
        setState('ready');
      })
      .catch((requestError) => { setError(requestError.message); setState('error'); });
  };

  useEffect(load, []);

  const invite = async (event) => {
    event.preventDefault();
    setAction('invite'); setError(''); setSuccess(''); setSetupUrl('');
    try {
      const invitation = await inviteWorkspaceMember(contact);
      setInvitations((current) => [invitation, ...current.filter((item) => item.id !== invitation.id)]);
      setContact(EMPTY_CONTACT);
      setSetupUrl(invitation.setup_url || '');
      setSuccess(invitation.delivery_status === 'sent'
        ? `Invitation emailed to ${invitation.email}.`
        : invitation.delivery_status === 'logged'
          ? `Invitation created for ${invitation.email}.`
          : `Contact created, but the setup email could not be delivered.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setAction('');
    }
  };

  const changeRole = async (member, role) => {
    setAction(`role-${member.id}`); setError(''); setSuccess('');
    try {
      const updated = await updateWorkspaceMemberRole(member.id, role);
      setMembers((current) => current.map((item) => item.id === updated.id ? updated : item));
      if (updated.is_current_user) await refresh();
      setSuccess(`${updated.display_name} is now ${roleLabel(updated.role)}.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setAction('');
    }
  };

  const cancelInvite = async (invitation) => {
    setAction(`cancel-${invitation.id}`); setError(''); setSuccess('');
    try {
      await cancelWorkspaceInvitation(invitation.id);
      setInvitations((current) => current.filter((item) => item.id !== invitation.id));
      setSuccess(`Invitation for ${invitation.email} canceled.`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setAction('');
    }
  };

  if (state === 'loading') return <div className="team-loading"><span className="spinner dark" /> Loading entity…</div>;
  if (state === 'error') return <div className="auth-error" role="alert">{error}</div>;

  return <div className="team-management">
    <section className="entity-identity-card">
      <span className="entity-mark">E</span><span><small>Entity</small><strong>{workspace.name}</strong>
        <em>Managed by the Workspace platform owner</em></span>
    </section>

    <section className="team-section">
      <div className="settings-section-heading"><strong>Invite a contact</strong>
        <small>Create a pending contact and email secure setup instructions.</small></div>
      <form className="invite-contact-form" onSubmit={invite}>
        <label>Full name<input required minLength="2" maxLength="100" value={contact.display_name}
          onChange={(event) => setContact((current) => ({ ...current, display_name: event.target.value }))} placeholder="Taylor Morgan" /></label>
        <label>Email address<input required type="email" value={contact.email}
          onChange={(event) => setContact((current) => ({ ...current, email: event.target.value }))} placeholder="taylor@company.com" /></label>
        <label><span className="invite-label-heading">Job title <small>Optional</small></span>
          <input maxLength="120" value={contact.job_title}
            onChange={(event) => setContact((current) => ({ ...current, job_title: event.target.value }))} placeholder="Operations manager" /></label>
        <label>Workspace role<select value={contact.role}
          onChange={(event) => setContact((current) => ({ ...current, role: event.target.value }))}>
          <option value="basic">Basic user — view workflows</option>
          <option value="guest">Guest — invited project access only</option>
          <option value="admin">Admin — manage workspace</option>
        </select></label>
        <div className="role-explainer"><strong>{roleLabel(contact.role)}</strong><span>{contact.role === 'admin'
          ? 'Can create and edit workflows, invite contacts, and manage roles.'
          : contact.role === 'guest' ? 'Can access only projects explicitly shared with them.' : 'Can securely view every existing workflow in this entity.'}</span></div>
        <button className="button primary" disabled={action === 'invite'}>{action === 'invite' ? 'Sending invitation…' : 'Create contact & send invite'}</button>
      </form>
      {setupUrl && <div className="setup-link-card"><span><strong>Account setup link</strong><small>Share this secure link directly with the contact. It expires automatically.</small></span>
        <div><input aria-label="Account setup link" value={setupUrl} readOnly onFocus={(event) => event.target.select()} />
          <button type="button" className="button secondary" onClick={() => navigator.clipboard?.writeText(setupUrl)}>Copy link</button></div></div>}
    </section>

    {(error || success) && <div className={error ? 'auth-error' : 'team-success'} role={error ? 'alert' : 'status'}>{error || success}</div>}

    <section className="team-section">
      <div className="settings-section-heading"><strong>Active contacts</strong>
        <small>{members.length} active {members.length === 1 ? 'contact' : 'contacts'} in {workspace.name}.</small></div>
      <div className="contact-list">
        {members.map((member) => <article className="contact-row" key={member.id}>
          <span className="contact-avatar">{member.display_name.slice(0, 1).toUpperCase()}</span>
          <span className="contact-identity"><strong>{member.display_name}{member.is_current_user && <em>You</em>}</strong><small>{member.email}</small></span>
          <select aria-label={`Role for ${member.display_name}`} value={member.role}
            disabled={action === `role-${member.id}`} onChange={(event) => changeRole(member, event.target.value)}>
            <option value="admin">Admin</option><option value="basic">Basic user</option><option value="guest">Guest</option>
          </select>
        </article>)}
      </div>
    </section>

    {invitations.length > 0 && <section className="team-section">
      <div className="settings-section-heading"><strong>Pending invitations</strong><small>Contacts who still need to set a password.</small></div>
      <div className="contact-list">
        {invitations.map((invitation) => <article className="contact-row pending" key={invitation.id}>
          <span className="contact-avatar">{invitation.display_name.slice(0, 1).toUpperCase()}</span>
          <span className="contact-identity"><strong>{invitation.display_name}<em>Pending</em></strong>
            <small>{invitation.email} · {roleLabel(invitation.role)}</small></span>
          <button type="button" className="text-danger" disabled={action === `cancel-${invitation.id}`}
            onClick={() => cancelInvite(invitation)}>Cancel</button>
        </article>)}
      </div>
    </section>}
  </div>;
}
