import { describe, expect, it } from 'vitest';

import { computeEstimate } from './ComposeForm';

describe('computeEstimate', () => {
  it('첨부 없는 단문(≤90B)은 RCS 17원 (기본 모드)', () => {
    const e = computeEstimate('안녕하세요', 10, false);
    expect(e.channel).toBe('SMS');
    expect(e.perUnit).toBe(17);
    expect(e.cost).toBe(170);
  });

  it('첨부 없는 장문(>90B)은 LMS 27원', () => {
    const e = computeEstimate('a'.repeat(100), 10, false);
    expect(e.channel).toBe('LMS');
    expect(e.perUnit).toBe(27);
  });

  it('첨부(이미지) 있으면 MMS 85원', () => {
    const e = computeEstimate('이미지 캠페인', 10, true);
    expect(e.channel).toBe('MMS');
    expect(e.perUnit).toBe(85);
    expect(e.cost).toBe(850);
  });

  it('첨부가 바이트 길이보다 우선 — 짧은 캡션 이미지도 MMS 85 (17원 과소추정 회귀 방지)', () => {
    const e = computeEstimate('여름 세일', 100, true);
    expect(e.perUnit).toBe(85);
    expect(e.cost).toBe(8500);
  });

  it('일반(sms) 모드 단문은 SMS 9원 (RCS 17 대비 절감)', () => {
    const e = computeEstimate('안녕하세요', 10, false, 'sms');
    expect(e.channel).toBe('SMS');
    expect(e.perUnit).toBe(9);
    expect(e.cost).toBe(90);
  });

  it('장문·이미지는 전송 방식과 무관하게 동일 단가 (27 / 85)', () => {
    expect(computeEstimate('a'.repeat(100), 10, false, 'sms').perUnit).toBe(27);
    expect(computeEstimate('a'.repeat(100), 10, false, 'rcs').perUnit).toBe(27);
    expect(computeEstimate('x', 10, true, 'sms').perUnit).toBe(85);
    expect(computeEstimate('x', 10, true, 'rcs').perUnit).toBe(85);
  });
});
