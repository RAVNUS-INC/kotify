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
