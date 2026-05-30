/**
 * 표시용 한국 전화번호 포맷터.
 *
 * DB 에는 숫자만 저장(백엔드 normalize_phone)하지만, 화면에서는 하이픈을 넣어
 * 가독성을 높인다. 입력에 하이픈/공백/점이 섞여 있어도 숫자만 추출 후 규칙에 맞춰
 * 재포맷하므로, 저장값이 어떤 형식이든 표기는 항상 일관된다.
 *
 * 한국 번호 규칙에 맞지 않으면(국제번호·비정형 등) 추출한 숫자만 반환해 최소한의
 * 일관성을 유지한다(하이픈이 어중간하게 남지 않게).
 */
export function formatPhone(raw: string | null | undefined): string {
  if (!raw) return '';
  const d = raw.replace(/\D/g, '');
  if (!d) return '';

  // 휴대폰 01[016789] — 11자리(010-1234-5678) / 10자리(011-123-4567)
  if (/^01[016789]/.test(d)) {
    if (d.length === 11) return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
    if (d.length === 10) return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
  }

  // 서울 02 — 10자리(02-1234-5678) / 9자리(02-123-4567)
  if (d.startsWith('02')) {
    if (d.length === 10) return `${d.slice(0, 2)}-${d.slice(2, 6)}-${d.slice(6)}`;
    if (d.length === 9) return `${d.slice(0, 2)}-${d.slice(2, 5)}-${d.slice(5)}`;
  }

  // 대표번호 15xx/16xx/18xx (8자리, 지역 구분 없음) — 1588-1234
  if (d.length === 8 && /^1[5-9]/.test(d)) {
    return `${d.slice(0, 4)}-${d.slice(4)}`;
  }

  // 그 외 지역번호/070/050 등 0XX 국번 (3자리) — 10~11자리
  if (/^0(3[1-3]|4[1-4]|5[0-5]|6[1-4]|70)/.test(d)) {
    if (d.length === 11) return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
    if (d.length === 10) return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
  }

  // 규칙 미상 — 숫자만 반환(일관성 우선)
  return d;
}
