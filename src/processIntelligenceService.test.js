import { eventsFromCsv, parseCsv } from './processIntelligenceService';

test('parses quoted CSV event logs into normalized process events', () => {
  const rows = parseCsv('case_id,activity,timestamp,status,cost\n1,"Review, legal",2026-08-29T10:00:00Z,completed,4.25\n');
  expect(rows[1][1]).toBe('Review, legal');

  expect(eventsFromCsv('case_id,activity,timestamp,status,cost\n1,"Review, legal",2026-08-29T10:00:00Z,completed,4.25\n')).toEqual([{
    case_id: '1',
    activity: 'Review, legal',
    occurred_at: '2026-08-29T10:00:00.000Z',
    status: 'completed',
    cost: 4.25,
  }]);
});

test('rejects event logs without the required process columns', () => {
  expect(() => eventsFromCsv('name,date\nReview,2026-08-29')).toThrow(/case_id, activity, and timestamp/i);
});
