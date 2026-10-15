import { describe, expect, it } from 'vitest';

import {
  counterpart,
  dispositionLabel,
  fmtKstDateTime,
  formatCallTime,
  formatDuration,
  hasOpenFax,
  isValidFaxNumber,
} from './pbx-format';

describe('formatDuration', () => {
  it.each([
    [0, '0:00'],
    [9, '0:09'],
    [75, '1:15'],
    [3661, '1:01:01'],
    [-5, '0:00'],
  ])('%s초 → %s', (sec, text) => {
    expect(formatDuration(sec)).toBe(text);
  });
});

describe('formatCallTime', () => {
  it('서버가 준 KST 시각을 그대로 자른다 (브라우저 시간대 무관)', () => {
    expect(formatCallTime('2026-10-15T09:05:00+09:00')).toBe('2026-10-15 09:05');
    expect(formatCallTime('')).toBe('');
  });
});

describe('fmtKstDateTime', () => {
  it('UTC ISO 를 KST 로 바꾸고 날짜가 넘어가도 맞다', () => {
    expect(fmtKstDateTime('2026-10-15T16:30:00+00:00')).toBe('2026-10-16 01:30');
    expect(fmtKstDateTime('nope')).toBe('');
    expect(fmtKstDateTime(null)).toBe('');
  });
});

describe('counterpart', () => {
  it('수신은 건 번호, 발신은 받은 번호가 고객이다', () => {
    expect(counterpart({ direction: 'in', from: 'A', to: '101' })).toBe('A');
    expect(counterpart({ direction: 'out', from: '101', to: 'B' })).toBe('B');
  });
});

describe('dispositionLabel', () => {
  it('PBX 원문을 한국어로, 모르는 값은 그대로', () => {
    expect(dispositionLabel('ANSWERED')).toBe('통화');
    expect(dispositionLabel('Answered Elsewhere')).toBe('다른 곳에서 받음');
    expect(dispositionLabel('WEIRD')).toBe('WEIRD');
    expect(dispositionLabel('')).toBe('—');
  });
});

describe('isValidFaxNumber', () => {
  it.each([
    ['02-0000-0000', true],
    ['031-000-0000', true],
    ['010-0000-0000', true],
    ['+82 2 0000 0000', true],
    ['1234', false],
    ['10000000000', false],
  ])('%s → %s', (raw, ok) => {
    expect(isValidFaxNumber(raw)).toBe(ok);
  });
});

describe('hasOpenFax', () => {
  it('준비·보내는 중만 새로고침 대상', () => {
    expect(hasOpenFax([{ status: 'SENT' }, { status: 'UNKNOWN' }])).toBe(false);
    expect(hasOpenFax([{ status: 'SUBMITTED' }])).toBe(true);
  });
});
