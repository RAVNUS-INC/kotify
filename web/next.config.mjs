import createBundleAnalyzer from '@next/bundle-analyzer';

const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';

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
