import { fireEvent, render, screen } from '@testing-library/react';
import React, { useState } from 'react';
import { UserMultiSelect, UserSelect } from './UserPicker';

const users = Array.from({ length: 80 }, (_, index) => ({
  id: `user-${index}`,
  display_name: index === 79 ? 'Zara Specialist' : `Member ${String(index).padStart(2, '0')}`,
  email: index === 79 ? 'zara@example.com' : `member${index}@example.com`,
  handle: index === 79 ? 'zara-specialist' : `member-${index}`,
  role: index % 2 ? 'basic' : 'admin',
  color: '#5B4BE7',
}));

function SingleHarness() {
  const [value, setValue] = useState('');
  return <UserSelect label="Assignee" ariaLabel="Test assignee" users={users} value={value}
    onChange={setValue} emptyLabel="Unassigned" />;
}

function MultiHarness() {
  const [value, setValue] = useState(['user-0']);
  return <UserMultiSelect label="Members" ariaLabel="Test members" users={users} value={value}
    onChange={setValue} requiredIds={['user-0']} />;
}

test('searches a large user list by email and selects one result', () => {
  render(<SingleHarness />);
  fireEvent.click(screen.getByRole('combobox', { name: /test assignee/i }));

  expect(screen.getByText(/Showing 50 of 80/i)).toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox', { name: /search test assignee/i }), {
    target: { value: 'zara@example.com' },
  });
  fireEvent.click(screen.getByRole('option', { name: /Zara Specialist/i }));

  expect(screen.getByRole('combobox', { name: /test assignee/i })).toHaveTextContent('Zara Specialist');
  expect(screen.queryByRole('searchbox', { name: /search test assignee/i })).not.toBeInTheDocument();
});

test('supports searchable multi-selection while keeping required people selected', () => {
  render(<MultiHarness />);
  fireEvent.click(screen.getByRole('combobox', { name: /test members/i }));
  fireEvent.change(screen.getByRole('searchbox', { name: /search test members/i }), {
    target: { value: 'member0@example.com' },
  });
  const requiredOption = screen.getByRole('option', { name: /Member 00/i });
  fireEvent.click(requiredOption);
  expect(requiredOption).toHaveAttribute('aria-selected', 'true');
  expect(requiredOption).toHaveAttribute('aria-disabled', 'true');

  fireEvent.change(screen.getByRole('searchbox', { name: /search test members/i }), {
    target: { value: 'zara-specialist' },
  });
  fireEvent.click(screen.getByRole('option', { name: /Zara Specialist/i }));
  fireEvent.click(screen.getByRole('button', { name: /done/i }));
  expect(screen.getByRole('combobox', { name: /test members/i })).toHaveTextContent('2 selected');
});
