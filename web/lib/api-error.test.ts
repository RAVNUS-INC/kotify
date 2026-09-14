import { describe, expect, it } from 'vitest';

import { ApiError, parseApiErrorDigest } from './api-error';

describe('ApiError digest', () => {
  it('상태·코드를 digest 에 싣고 다시 읽을 수 있다', () => {
    const err = new ApiError(403, 'forbidden', '권한이 없습니다.');
    expect(parseApiErrorDigest(err.digest)).toEqual({ status: 403, code: 'forbidden' });
  });

  it.each([undefined, '', '3194136073', 'NEXT_REDIRECT;replace;/login', 'KOTIFY_API::x'])(
    'ApiError 가 아닌 digest(%s)는 null',
    (digest) => {
      expect(parseApiErrorDigest(digest)).toBeNull();
    },
  );
});
