import { Fragment } from 'react';

export type HighlightTextProps = {
  text: string;
  q: string;
  /** case-insensitive (기본 true) */
  ci?: boolean;
};

/**
 * q와 매칭되는 모든 부분 문자열을 <mark>로 감싼다.
 * <mark> 스타일은 globals.css의 전역 mark 규칙 (brand 12% bg + brand text).
 */
export function HighlightText({ text, q, ci = true }: HighlightTextProps) {
  const query = q.trim();
  if (!query) return <>{text}</>;

  const needle = ci ? query.toLowerCase() : query;
  const haystack = ci ? text.toLowerCase() : text;

  const parts: Array<{ text: string; highlight: boolean }> = [];
  let i = 0;
  while (i < text.length) {
    const idx = haystack.indexOf(needle, i);
    if (idx < 0) {
      parts.push({ text: text.slice(i), highlight: false });
      break;
    }
    if (idx > i) parts.push({ text: text.slice(i, idx), highlight: false });
    parts.push({ text: text.slice(idx, idx + query.length), highlight: true });
    i = idx + query.length;
  }

  return (
    <>
      {parts.map((p, j) => (
        <Fragment key={j}>
          {p.highlight ? <mark>{p.text}</mark> : p.text}
        </Fragment>
      ))}
    </>
  );
}
