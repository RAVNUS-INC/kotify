import { describe, expect, it } from 'vitest';
import { formatDateTime } from './datetime';

describe('formatDateTime', () => {
  it('올해 날짜는 연도 없이 "월 일 시:분"', () => {
    expect(formatDateTime('2026-10-16 00:10', 2026)).toBe('10월 16일 00:10');
  });

  it('예약 시각의 ISO 형식(T 구분, 초 포함)도 같은 모양으로', () => {
    expect(formatDateTime('2026-10-16T20:22:02', 2026)).toBe('10월 16일 20:22');
  });

  it('다른 해는 연도를 붙인다', () => {
    expect(formatDateTime('2025-03-02 09:05', 2026)).toBe('2025. 3. 2. 09:05');
  });

  it('형식이 다르면 원문 그대로', () => {
    expect(formatDateTime('—', 2026)).toBe('—');
    expect(formatDateTime('어제', 2026)).toBe('어제');
  });
});
