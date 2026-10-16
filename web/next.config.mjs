import createBundleAnalyzer from '@next/bundle-analyzer';

// 기본값은 production 경로(kotify.service가 8080에 바인딩). dev는 .env.local에서
// FASTAPI_URL=http://localhost:8000 등으로 override. next.config.mjs 는 빌드 타임에
// 평가되어 rewrites destination에 baked되므로, 올바른 기본값을 두는 게 중요.
const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://127.0.0.1:8080';

const withBundleAnalyzer = createBundleAnalyzer({
  // ANALYZE=true 로 실행하면 .next/analyze/*.html 리포트 생성
  enabled: process.env.ANALYZE === 'true',
  openAnalyzer: false,
});

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Phase 11: standalone 빌드로 배포 용량 최소화 + node server.js 단독 실행.
  // ct-bootstrap.sh가 .next/standalone 을 실행 대상으로 하고, 별도로
  // .next/static 과 public/ 디렉토리를 그 안에 복사한다.
  output: 'standalone',
  experimental: {
    typedRoutes: true,
    // /api rewrite 프록시가 FastAPI 응답을 기다리는 시간. 기본 30초(next/dist/server/lib/router-utils/
    // proxy-request.js)는 캠페인 발송(POST /campaigns)에 짧다 — 1,000명은 10명씩 100번 msghub 를
    // 순서대로 부르고, 29002·[재전송] 코드면 청크마다 5초 기다려 한 번 더 보낸다. 넘기면 브라우저는 500 을
    // 받는데 백엔드는 계속 보내 사용자가 다시 누르게 된다. 앞단 프록시(NPM)의 읽기 시간 제한(기본 60초)도
    // 이보다 짧으면 그쪽이 먼저 끊는다 — deploy/README "발송 요청 시간 제한" 참고.
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${FASTAPI_URL}/:path*`,
      },
    ];
  },
};

export default withBundleAnalyzer(nextConfig);
