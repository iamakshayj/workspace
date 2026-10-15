import React, { useEffect, useState } from 'react';
import {
  addSamlCertificate, changeSamlCertificate, createDomainChallenge, createIdentityProvider, createSamlProvider,
  createScimToken, inspectSamlMetadata, listIdentityProviders, listScimTokens, revokeScimToken,
  SCIM_BASE_URL, testIdentityProvider, testSamlProvider, updateIdentityProvider, updateSamlProvider,
  verifyIdentityDomain,
} from './identityService';
import { API_BASE_URL } from './apiClient';

const EMPTY_PROVIDER = {
  protocol: 'oidc',
  name: '', issuer_url: '', client_id: '', client_secret: '', scopes: ['openid', 'profile', 'email'],
  enabled: false, enforce_sso: false, jit_enabled: true, default_role: 'basic', allow_admin_password_fallback: true,
};

const EMPTY_SAML_PROVIDER = {
  protocol: 'saml', name: '', metadata_url: '', idp_entity_id: '', sso_url: '', slo_url: '', x509_certificate: '', sp_entity_id: '', email_attribute: '', sign_authn_requests: true,
  enabled: false, enforce_sso: false, jit_enabled: true, default_role: 'basic', allow_admin_password_fallback: true,
};

function editableProvider(provider) {
  if (provider.protocol === 'saml') return {
    name: provider.name, idp_entity_id: provider.idp_entity_id, sso_url: provider.sso_url, slo_url: provider.slo_url || '',
    x509_certificate: '', sp_entity_id: provider.sp_entity_id, email_attribute: provider.email_attribute || '',
    sign_authn_requests: provider.sign_authn_requests,
    enabled: provider.enabled, enforce_sso: provider.enforce_sso, jit_enabled: provider.jit_enabled,
    default_role: provider.default_role, allow_admin_password_fallback: provider.allow_admin_password_fallback,
  };
  return { ...provider, client_secret: '', domains: undefined, has_client_secret: undefined, created_at: undefined, updated_at: undefined, protocol: undefined, id: undefined };
}

export default function IdentityManagement() {
  const [providers, setProviders] = useState([]);
  const [tokens, setTokens] = useState([]);
  const [providerForm, setProviderForm] = useState(null);
  const [domain, setDomain] = useState('');
  const [challenge, setChallenge] = useState(null);
  const [newToken, setNewToken] = useState(null);
  const [certificateForm, setCertificateForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = async () => {
    try {
      const [nextProviders, nextTokens] = await Promise.all([listIdentityProviders(), listScimTokens()]);
      setProviders(nextProviders); setTokens(nextTokens);
    } catch (requestError) { setError(requestError.message); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const perform = async (action) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const saveProvider = (event) => {
    event.preventDefault();
    perform(async () => {
      if (providerForm.protocol === 'saml') await createSamlProvider({ ...providerForm, protocol: undefined, metadata_url: undefined });
      else await createIdentityProvider({ ...providerForm, protocol: undefined });
      setProviderForm(null); await load();
      setNotice('Provider saved. Test it and verify a domain before enforcing SSO.');
    });
  };

  const updateProvider = (provider, changes) => perform(async () => {
    const next = { ...editableProvider(provider), ...changes };
    if (provider.protocol === 'saml') await updateSamlProvider(provider.id, next);
    else await updateIdentityProvider(provider.id, next);
    await load();
  });

  const testProvider = (provider) => perform(async () => {
    if (provider.protocol === 'saml') await testSamlProvider(provider.id);
    else await testIdentityProvider(provider.id);
    setNotice(`${provider.name} configuration is valid.`);
  });

  const importMetadata = () => perform(async () => {
    const result = await inspectSamlMetadata(providerForm.metadata_url);
    setProviderForm((current) => ({
      ...current, idp_entity_id: result.idp_entity_id, sso_url: result.sso_url, slo_url: result.slo_url || '',
      x509_certificate: result.certificates[0]?.x509_certificate || current.x509_certificate,
    }));
    setNotice(`Metadata inspected. ${result.certificates.length} valid signing certificate${result.certificates.length === 1 ? '' : 's'} found.`);
  });

  const saveCertificate = (event) => {
    event.preventDefault();
    perform(async () => {
      await addSamlCertificate(certificateForm.providerId, certificateForm.pem);
      setCertificateForm(null); await load(); setNotice('Signing certificate added for a safe overlap period.');
    });
  };

  return <section className="identity-management">
    <header><div><strong>Enterprise SSO</strong><small>Connect OpenID Connect or SAML 2.0, then verify the company domains allowed to sign in.</small></div><div className="identity-provider-buttons"><button className="button secondary" onClick={() => setProviderForm({ ...EMPTY_PROVIDER })}>+ OpenID Connect</button><button className="button secondary" onClick={() => setProviderForm({ ...EMPTY_SAML_PROVIDER })}>+ SAML</button></div></header>
    {providerForm && <form className="identity-provider-form" onSubmit={saveProvider}>
      <strong>New {providerForm.protocol === 'saml' ? 'SAML 2.0' : 'OpenID Connect'} connection</strong>
      <div className="security-policy-grid">
        <label>Provider name<input required value={providerForm.name} onChange={(event) => setProviderForm({ ...providerForm, name: event.target.value })} placeholder="Company identity" /></label>
        {providerForm.protocol === 'saml' ? <>
          <label className="identity-metadata-field">Identity provider metadata URL <small>Optional</small><span><input type="url" value={providerForm.metadata_url} onChange={(event) => setProviderForm({ ...providerForm, metadata_url: event.target.value })} placeholder="https://idp.company.com/metadata.xml" /><button type="button" disabled={!providerForm.metadata_url || busy} onClick={importMetadata}>Inspect and fill</button></span></label>
          <label>Identity provider entity ID<input required value={providerForm.idp_entity_id} onChange={(event) => setProviderForm({ ...providerForm, idp_entity_id: event.target.value })} placeholder="https://idp.company.com/metadata" /></label>
          <label>Sign-on URL<input required type="url" value={providerForm.sso_url} onChange={(event) => setProviderForm({ ...providerForm, sso_url: event.target.value })} placeholder="https://idp.company.com/sso/saml" /></label>
          <label>Single Logout URL <small>Optional</small><input type="url" value={providerForm.slo_url} onChange={(event) => setProviderForm({ ...providerForm, slo_url: event.target.value })} placeholder="https://idp.company.com/saml/logout" /></label>
          <label>Email attribute <small>Optional</small><input value={providerForm.email_attribute} onChange={(event) => setProviderForm({ ...providerForm, email_attribute: event.target.value })} placeholder="Defaults to common email claims" /></label>
          <label className="identity-certificate-field">X.509 signing certificate<textarea required rows="6" value={providerForm.x509_certificate} onChange={(event) => setProviderForm({ ...providerForm, x509_certificate: event.target.value })} placeholder="-----BEGIN CERTIFICATE-----" /></label>
          <label className="identity-signing-toggle"><input type="checkbox" checked={providerForm.sign_authn_requests} onChange={(event) => setProviderForm({ ...providerForm, sign_authn_requests: event.target.checked })} /> Sign authentication requests</label>
        </> : <>
          <label>Issuer URL<input required type="url" value={providerForm.issuer_url} onChange={(event) => setProviderForm({ ...providerForm, issuer_url: event.target.value })} placeholder="https://login.company.com" /></label>
          <label>Client ID<input required value={providerForm.client_id} onChange={(event) => setProviderForm({ ...providerForm, client_id: event.target.value })} /></label>
          <label>Client secret<input required type="password" autoComplete="new-password" value={providerForm.client_secret} onChange={(event) => setProviderForm({ ...providerForm, client_secret: event.target.value })} /></label>
        </>}
      </div>
      <div><button type="button" className="button secondary" onClick={() => setProviderForm(null)}>Cancel</button><button className="button primary" disabled={busy}>Save provider</button></div>
    </form>}
    <div className="identity-provider-list">{providers.map((provider) => <article key={provider.id}><header><div><strong>{provider.name} <em className="identity-protocol">{provider.protocol === 'saml' ? 'SAML 2.0' : 'OIDC'}</em></strong><small>{provider.protocol === 'saml' ? provider.idp_entity_id : provider.issuer_url}</small></div><span className={provider.enabled ? 'enabled' : ''}>{provider.enabled ? 'Active' : 'Inactive'}</span></header>{provider.protocol === 'saml' && <><div className="identity-metadata"><span>Service provider metadata</span><code>{`${API_BASE_URL}/api/v1/auth/sso/${provider.id}/metadata`}</code><button onClick={() => navigator.clipboard?.writeText(`${API_BASE_URL}/api/v1/auth/sso/${provider.id}/metadata`)}>Copy</button></div><div className="identity-certificates"><header><span><strong>IdP signing certificates</strong><small>Keep old and new certificates active during rotation.</small></span><button onClick={() => setCertificateForm({ providerId: provider.id, providerName: provider.name, pem: '' })}>+ Certificate</button></header>{provider.signing_certificates.map((certificate) => <div key={certificate.id}><code>{certificate.fingerprint_sha256.match(/.{1,4}/g)?.join(' ')}</code><span><em className={certificate.status}>{certificate.status}</em><small>Expires {new Date(certificate.valid_until).toLocaleDateString()}</small></span>{certificate.status === 'active' && <button onClick={() => perform(async () => { await changeSamlCertificate(provider.id, certificate.id, 'retire'); await load(); })}>Retire</button>}{certificate.status === 'retiring' && <><button onClick={() => perform(async () => { await changeSamlCertificate(provider.id, certificate.id, 'activate'); await load(); })}>Reactivate</button><button className="danger" onClick={() => perform(async () => { await changeSamlCertificate(provider.id, certificate.id, 'revoke'); await load(); })}>Revoke</button></>}</div>)}</div></>}<div className="identity-provider-actions"><button onClick={() => testProvider(provider)}>Validate configuration</button><label><input type="checkbox" checked={provider.enabled} onChange={(event) => updateProvider(provider, { enabled: event.target.checked })} /> Enabled</label><label><input type="checkbox" checked={provider.enforce_sso} disabled={!provider.domains.some((item) => item.status === 'verified')} onChange={(event) => updateProvider(provider, { enforce_sso: event.target.checked })} /> Enforce SSO</label><label><input type="checkbox" checked={provider.jit_enabled} onChange={(event) => updateProvider(provider, { jit_enabled: event.target.checked })} /> Just-in-time accounts</label>{provider.protocol === 'saml' && <label><input type="checkbox" checked={provider.sign_authn_requests} onChange={(event) => updateProvider(provider, { sign_authn_requests: event.target.checked })} /> Sign requests</label>}</div><div className="identity-domain-row"><input aria-label={`Domain for ${provider.name}`} value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="company.com" /><button disabled={!domain || busy} onClick={() => perform(async () => { const result = await createDomainChallenge(provider.id, domain); setChallenge({ ...result, provider_id: provider.id }); setDomain(''); await load(); })}>Add domain</button></div>{provider.domains.map((item) => <div className="identity-domain" key={item.domain}><span><strong>{item.domain}</strong><small>{item.status === 'verified' ? `Verified ${new Date(item.verified_at).toLocaleDateString()}` : 'Publish the verification file, then verify'}</small></span><em className={item.status}>{item.status}</em>{item.status !== 'verified' && <button onClick={() => perform(async () => { await verifyIdentityDomain(provider.id, item.domain); await load(); setNotice(`${item.domain} is verified.`); })}>Verify</button>}</div>)}</article>)}{!providers.length && !providerForm && <p className="security-help">No identity provider configured. Password sign-in remains available.</p>}</div>
    {certificateForm && <form className="identity-provider-form" onSubmit={saveCertificate}><strong>Add a signing certificate for {certificateForm.providerName}</strong><p className="security-help">Add the replacement before retiring the old certificate. Both remain valid during the overlap.</p><label className="identity-certificate-field">X.509 certificate<textarea required rows="6" value={certificateForm.pem} onChange={(event) => setCertificateForm({ ...certificateForm, pem: event.target.value })} placeholder="-----BEGIN CERTIFICATE-----" /></label><div><button type="button" className="button secondary" onClick={() => setCertificateForm(null)}>Cancel</button><button className="button primary" disabled={busy}>Add certificate</button></div></form>}
    {challenge && <div className="identity-secret-once"><strong>Publish this verification token</strong><p>Create the text file below with exactly this content. The token is shown only now.</p><code>{challenge.challenge_token}</code><small>{challenge.verification_url}</small><button onClick={() => navigator.clipboard?.writeText(challenge.challenge_token)}>Copy token</button></div>}

    <header className="identity-scim-heading"><div><strong>SCIM provisioning</strong><small>Create a scoped bearer token for your identity provider. Tokens are shown only once.</small></div><button className="button secondary" onClick={() => perform(async () => { setNewToken(await createScimToken({ name: `Provisioning ${new Date().toLocaleDateString()}`, expires_in_days: 365, scopes: ['users:read', 'users:write', 'groups:read', 'groups:write'] })); await load(); })}>+ SCIM token</button></header>
    {newToken && <div className="identity-secret-once"><strong>Copy the SCIM bearer token now</strong><code>{newToken.token}</code><small>Base URL: {SCIM_BASE_URL}</small><button onClick={() => navigator.clipboard?.writeText(newToken.token)}>Copy token</button></div>}
    <div className="identity-token-list">{tokens.map((token) => <div key={token.id}><span><strong>{token.name}</strong><small>{token.scopes.join(' · ')} · {token.last_used_at ? `Last used ${new Date(token.last_used_at).toLocaleString()}` : 'Never used'}</small></span><em>{token.revoked_at ? 'Revoked' : token.expires_at ? `Expires ${new Date(token.expires_at).toLocaleDateString()}` : 'No expiry'}</em>{!token.revoked_at && <button onClick={() => perform(async () => { await revokeScimToken(token.id); await load(); })}>Revoke</button>}</div>)}</div>
    {notice && <div className="notice success">{notice}</div>}{error && <div className="auth-error" role="alert">{error}</div>}
  </section>;
}
