import { describe, expect, it } from 'vitest';

import { canAccessPath, requiredRoles } from './access';

describe('requiredRoles', () => {
  it.each([
    ['/settings', ['admin']],
    ['/settings/org', ['admin']],
    ['/audit', ['admin']],
    ['/send/new', ['sender', 'admin', 'owner']],
  ])('%s 는 역할 제한이 있다', (path, roles) => {
    expect(requiredRoles(path)).toEqual(roles);
  });

  it.each(['/', '/numbers', '/chat', '/settingsfoo', '/auditlog', '/sender'])(
    '%s 는 제한이 없다 (접두어가 경로 구간 단위로만 일치)',
    (path) => {
      expect(requiredRoles(path)).toBeNull();
    },
  );
});

describe('canAccessPath', () => {
  it('제한 경로는 허용 역할 중 하나가 있어야 한다', () => {
    expect(canAccessPath('/audit', ['viewer'])).toBe(false);
    expect(canAccessPath('/audit', ['viewer', 'admin'])).toBe(true);
    expect(canAccessPath('/send/new', ['viewer'])).toBe(false);
    expect(canAccessPath('/send/new', ['sender'])).toBe(true);
  });

  it('제한 없는 경로는 역할이 없어도 허용된다', () => {
    expect(canAccessPath('/numbers', [])).toBe(true);
  });
});
