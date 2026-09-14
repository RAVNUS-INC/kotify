/**
 * 권한 부족(403) 안내 — 문구와 middleware 용 독립 HTML.
 *
 * Next 14 는 middleware rewrite 에 지정한 상태 코드를 앱 라우터 페이지 렌더에
 * 넘기지 않는다(본문을 직접 담은 응답만 상태 코드가 유지됨). 그래서 실제 HTTP
 * 403 을 내려주려면 middleware 가 이 HTML 을 본문으로 응답한다. 앱 CSS 를 쓸 수
 * 없어 ErrorPage 모양을 토큰 값으로 인라인 재현한다. Edge runtime 용 순수 TS.
 */

export const FORBIDDEN_TITLE = '접근 권한이 없습니다';
export const FORBIDDEN_DESCRIPTION =
  '이 페이지를 볼 권한이 없습니다. 접근이 필요하면 관리자에게 권한을 요청하세요.';

export function forbiddenHtml(): string {
  return `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${FORBIDDEN_TITLE} · Kotify</title>
<style>
  body{margin:0;background:#fff;color:#0a0a0a;font-family:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',system-ui,sans-serif}
  main{display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}
  .box{display:flex;max-width:28rem;flex-direction:column;align-items:center;gap:16px;text-align:center}
  .icon{display:flex;width:80px;height:80px;align-items:center;justify-content:center;border-radius:9999px;background:#fffbeb;color:#b45309}
  .code{font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:#a0a0a0}
  h1{margin:0;font-size:24px;font-weight:600;letter-spacing:-.01em}
  p{margin:0;font-size:14px;line-height:1.6;color:#717171}
  a{margin-top:8px;display:inline-flex;height:36px;align-items:center;border:1px solid #e0e0e0;border-radius:6px;padding:0 12px;font-size:14px;font-weight:500;color:#0a0a0a;text-decoration:none}
  a:hover{background:#fafafa}
</style>
</head>
<body>
<main>
  <div class="box">
    <div class="icon" aria-hidden="true">
      <svg width="32" height="32" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h8v6H4zM6 7V5a2 2 0 114 0v2"/></svg>
    </div>
    <div class="code">Error 403</div>
    <h1 role="alert">${FORBIDDEN_TITLE}</h1>
    <p>${FORBIDDEN_DESCRIPTION}</p>
    <a href="/">홈으로</a>
  </div>
</main>
</body>
</html>`;
}
