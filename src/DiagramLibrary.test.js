import { fireEvent, render, screen } from '@testing-library/react';
import DiagramLibrary from './DiagramLibrary';

test('offers basic, BPMN, and enterprise diagram objects', () => {
  const onAdd = jest.fn();
  render(<DiagramLibrary open onClose={jest.fn()} onAdd={onAdd} />);

  expect(screen.getByText('Basics')).toBeInTheDocument();
  expect(screen.getByText('BPMN')).toBeInTheDocument();
  expect(screen.getByText('Enterprise')).toBeInTheDocument();
  expect(screen.getByText('UML & data')).toBeInTheDocument();
  expect(screen.getByText('Maps & organization')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add free text/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add exclusive gateway/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add database/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add uml actor/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /add mind-map topic/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /add timer event/i }));
  expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({
    shape: 'ellipse', symbol: 'bpmn_timer', width: 104, height: 104,
  }));
});
