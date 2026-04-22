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
