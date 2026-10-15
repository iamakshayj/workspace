import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import NodeAttachments from './NodeAttachments';

const attachment = {
  id: 'attachment-1', filename: 'requirements.pdf', size_bytes: 2048,
};

afterEach(() => jest.restoreAllMocks());

test('admins can upload, download, and remove node attachments', async () => {
  const onUpload = jest.fn().mockResolvedValue(undefined);
  const onDelete = jest.fn().mockResolvedValue(undefined);
  jest.spyOn(window, 'confirm').mockReturnValue(true);
  render(<NodeAttachments
    projectId="project-1"
    nodeId="node-1"
    attachments={[attachment]}
    canManage
    onUpload={onUpload}
    onDelete={onDelete}
  />);

  const file = new File(['content'], 'design.txt', { type: 'text/plain' });
  fireEvent.change(screen.getByLabelText(/attach file to step/i), { target: { files: [file] } });
  await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file, 'node-1'));

  expect(screen.getByRole('link', { name: /requirements.pdf/i })).toHaveAttribute(
    'href', expect.stringContaining('/projects/project-1/attachments/attachment-1'),
  );
  const removeButton = screen.getByRole('button', { name: /remove requirements.pdf/i });
  await waitFor(() => expect(removeButton).toBeEnabled());
  fireEvent.click(removeButton);
  await waitFor(() => expect(onDelete).toHaveBeenCalledWith('attachment-1'));
});

test('basic users can download attachments without management controls', () => {
  render(<NodeAttachments
    projectId="project-1"
    nodeId="node-1"
    attachments={[attachment]}
    canManage={false}
  />);

  expect(screen.getByRole('link', { name: /requirements.pdf/i })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /add file/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /remove requirements.pdf/i })).not.toBeInTheDocument();
});

test('rejects files larger than 10 MB before uploading', () => {
  const onUpload = jest.fn();
  render(<NodeAttachments projectId="project-1" nodeId="node-1" canManage onUpload={onUpload} />);
  const file = new File(['x'], 'too-large.bin');
  Object.defineProperty(file, 'size', { value: 10 * 1024 * 1024 + 1 });

  fireEvent.change(screen.getByLabelText(/attach file to step/i), { target: { files: [file] } });

  expect(screen.getByRole('alert')).toHaveTextContent(/10 MB or smaller/i);
  expect(onUpload).not.toHaveBeenCalled();
});
