// @vitest-environment node
import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FORBIDDEN_TITLE } from '@/lib/forbidden-page';
import { middleware } from './middleware';

function request(path: string, session?: string): NextRequest {
  const headers = new Headers();
  if (session) headers.set('cookie', `sms_session=${session}`);
  return new NextRequest(new URL(path, 'http://localhost:3000'), { headers });
}

function mockAuthMe(response: Response | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function meResponse(roles: string[]): Response {
  return Response.json({ data: { user: { sub: 's', roles } } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('middleware', () => {
  it('세션 쿠키가 없으면 /login 으로 보낸다', async () => {
    const res = await middleware(request('/audit'));
    expect(res.status).toBe(307);
    expect(new URL(res.headers.get('location')!).pathname).toBe('/login');
  });

  it('역할 제한이 없는 경로는 /auth/me 를 호출하지 않는다', async () => {
    const fetchMock = mockAuthMe(meResponse(['viewer']));
    const res = await middleware(request('/numbers', 'abc'));
    expect(res.headers.get('x-middleware-next')).toBe('1');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('역할이 충분하면 통과시킨다', async () => {
    const fetchMock = mockAuthMe(meResponse(['admin']));
    const res = await middleware(request('/audit', 'abc'));
    expect(res.headers.get('x-middleware-next')).toBe('1');
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).cookie).toBe('sms_session=abc');
  });

  it.each([
    ['/audit', ['viewer']],
    ['/settings/org', ['sender']],
    ['/send/new', ['viewer']],
  ])('%s 에 역할(%s)이 모자라면 403 안내 HTML 을 응답한다', async (path, roles) => {
    mockAuthMe(meResponse(roles));
    const res = await middleware(request(path, 'abc'));
    expect(res.status).toBe(403);
    expect(res.headers.get('content-type')).toContain('text/html');
    expect(await res.text()).toContain(FORBIDDEN_TITLE);
  });

  it('세션이 무효(401)면 원래 경로를 담아 /login 으로 보낸다', async () => {
    mockAuthMe(new Response(null, { status: 401 }));
    const res = await middleware(request('/audit', 'expired'));
    const location = new URL(res.headers.get('location')!);
    expect(location.pathname).toBe('/login');
    expect(location.searchParams.get('from')).toBe('/audit');
  });

  it.each([
    ['네트워크 오류', new Error('fetch failed')],
    ['5xx', new Response(null, { status: 502 })],
  ])('백엔드 %s 로 판단할 수 없으면 거짓 403 대신 통과시킨다', async (_label, response) => {
    mockAuthMe(response);
    const res = await middleware(request('/settings/org', 'abc'));
    expect(res.status).not.toBe(403);
    expect(res.headers.get('x-middleware-next')).toBe('1');
  });
});
