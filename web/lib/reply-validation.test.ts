import { beforeEach, describe, expect, it, vi } from 'vitest';

import { validateReplyClient } from './reply-validation';
import { apiSend } from './csrf-client';

vi.mock('./csrf-client', () => ({ apiSend: vi.fn() }));

beforeEach(() => vi.mocked(apiSend).mockReset());

describe('validateReplyClient', () => {
  it('검증 전용 엔드포인트에 본문과 취소 신호를 전달하고 서버 바이트 수를 사용한다', async () => {
    const data = { byteLength: 90, maxBytes: 90, valid: true, error: null };
    vi.mocked(apiSend).mockResolvedValue(new Response(JSON.stringify({ data })));
    const controller = new AbortController();

    await expect(validateReplyClient('가'.repeat(45), controller.signal)).resolves.toEqual(data);
    expect(apiSend).toHaveBeenCalledWith('/api/threads/validate-reply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '가'.repeat(45) }), signal: controller.signal,
    });
  });

  it('지원하지 않는 문자의 null 바이트와 검증 오류를 그대로 반환한다', async () => {
    const data = { byteLength: null, maxBytes: 90, valid: false, error: '지원되지 않는 문자' };
    vi.mocked(apiSend).mockResolvedValue(new Response(JSON.stringify({ data })));
    await expect(validateReplyClient('🙂')).resolves.toEqual(data);
  });

  it.each([
    { body: { error: { message: '로그인이 필요합니다' } }, status: 401, message: '로그인이 필요합니다' },
    { body: { detail: { message: '권한이 없습니다' } }, status: 403, message: '권한이 없습니다' },
    { body: {}, status: 503, message: 'HTTP 503' },
  ])('실패 응답은 성공한 검증으로 처리하지 않는다: $status', async ({ body, status, message }) => {
    vi.mocked(apiSend).mockResolvedValue(new Response(JSON.stringify(body), { status }));
    await expect(validateReplyClient('본문')).rejects.toThrow(message);
  });

  it.each([
    null,
    {},
    { data: { byteLength: null, maxBytes: 90, valid: true, error: null } },
    { data: { byteLength: 91, maxBytes: 90, valid: true, error: null } },
    { data: { byteLength: 3, valid: true, error: null } },
  ])('잘못된 성공 응답도 발송을 허용하지 않는다: %j', async (body) => {
    vi.mocked(apiSend).mockResolvedValue(new Response(JSON.stringify(body)));
    await expect(validateReplyClient('본문')).rejects.toThrow('길이 확인 응답이 올바르지 않습니다');
  });

  it('프록시가 JSON 대신 오류 페이지를 반환해도 HTTP 실패를 안내한다', async () => {
    vi.mocked(apiSend).mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 }));
    await expect(validateReplyClient('본문')).rejects.toThrow('HTTP 502');
  });
});
