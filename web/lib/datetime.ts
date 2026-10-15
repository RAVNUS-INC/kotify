/**
 * 표에 쓰는 날짜·시각 — 서버가 주는 KST 기준 문자열("2026-10-16 00:10", "2026-10-16T20:22:02")을
 * 올해면 "10월 16일 20:22", 다른 해면 "2025. 3. 2. 20:22" 로 바꾼다. 시간대 변환은 하지 않는다
 * (값이 이미 KST). 형식이 맞지 않으면 원문을 그대로 돌려준다.
 * currentYear 는 테스트·서버 렌더용으로 넘길 수 있고, 생략하면 실행 환경의 올해를 쓴다.
 */
export function formatDateTime(value: string, currentYear = new Date().getFullYear()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(value.trim());
  if (!m) return value;
  const [, y, mo, d, hh, mm] = m;
  const month = Number(mo);
  const day = Number(d);
  const time = `${hh}:${mm}`;
  if (Number(y) === currentYear) return `${month}월 ${day}일 ${time}`;
  return `${Number(y)}. ${month}. ${day}. ${time}`;
}
