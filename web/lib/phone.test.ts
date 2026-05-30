import { describe, expect, it } from 'vitest';

import { formatPhone } from './phone';

describe('formatPhone', () => {
  it('휴대폰 11자리 → 010-1234-5678', () => {
    expect(formatPhone('01012345678')).toBe('010-1234-5678');
  });

  it('이미 하이픈/점이 있어도 동일하게 재포맷', () => {
    expect(formatPhone('010-1234-5678')).toBe('010-1234-5678');
    expect(formatPhone('010.1234.5678')).toBe('010-1234-5678');
    expect(formatPhone(' 010 1234 5678 ')).toBe('010-1234-5678');
  });

  it('휴대폰 10자리(011) → 011-123-4567', () => {
    expect(formatPhone('0111234567')).toBe('011-123-4567');
  });

  it('서울 02 → 02-1234-5678 / 02-123-4567', () => {
    expect(formatPhone('0212345678')).toBe('02-1234-5678');
    expect(formatPhone('021234567')).toBe('02-123-4567');
  });

  it('대표번호 8자리 → 1588-1234', () => {
    expect(formatPhone('15881234')).toBe('1588-1234');
  });

  it('지역번호 031 → 자리수별 포맷', () => {
    expect(formatPhone('0311234567')).toBe('031-123-4567');
    expect(formatPhone('03112345678')).toBe('031-1234-5678');
  });

  it('빈 값/null/undefined → 빈 문자열', () => {
    expect(formatPhone('')).toBe('');
    expect(formatPhone(null)).toBe('');
    expect(formatPhone(undefined)).toBe('');
  });

  it('규칙에 안 맞으면 숫자만 반환', () => {
    expect(formatPhone('123')).toBe('123');
    expect(formatPhone('abc')).toBe('');
  });
});
