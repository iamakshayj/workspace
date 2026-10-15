import { deleteAttachment, listAttachments, uploadAttachment } from './attachmentService';

afterEach(() => jest.restoreAllMocks());

test('lists and uploads authenticated node attachments', async () => {
  const file = new File(['policy'], 'policy.pdf', { type: 'application/pdf' });
  global.fetch = jest.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve([]) })
    .mockResolvedValueOnce({ ok: true, status: 201, json: () => Promise.resolve({
      attachment: { id: 'attachment-1' },
      upload: { method: 'PUT', url: '/api/v1/storage/uploads/attachment-1?token=signed', headers: { 'Content-Type': 'application/pdf' } },
    }) })
    .mockResolvedValueOnce({ ok: true, status: 204, json: () => Promise.resolve({}) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ id: 'attachment-1', scan_status: 'clean' }) })
    .mockResolvedValueOnce({ ok: true, status: 204, json: () => Promise.resolve({}) });

  await expect(listAttachments('project-1')).resolves.toEqual([]);
  await expect(uploadAttachment('project-1', 'approval', file)).resolves.toEqual({ id: 'attachment-1', scan_status: 'clean' });
  await expect(deleteAttachment('project-1', 'attachment-1')).resolves.toBeNull();

  expect(global.fetch.mock.calls[0][1]).toEqual(expect.objectContaining({ credentials: 'include' }));
  expect(global.fetch.mock.calls[1][0]).toMatch(/attachments\/uploads$/);
  expect(global.fetch.mock.calls[1][1]).toEqual(expect.objectContaining({
    method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
  }));
  expect(JSON.parse(global.fetch.mock.calls[1][1].body)).toEqual(expect.objectContaining({
    filename: 'policy.pdf', node_id: 'approval', size_bytes: 6,
  }));
  expect(global.fetch.mock.calls[2][1]).toEqual(expect.objectContaining({ method: 'PUT', body: file }));
  expect(global.fetch.mock.calls[3][0]).toMatch(/attachment-1\/complete$/);
  expect(global.fetch.mock.calls[4][1]).toEqual(expect.objectContaining({ method: 'DELETE' }));
});
