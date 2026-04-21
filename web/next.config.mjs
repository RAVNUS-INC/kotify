/** @type {import('next').NextConfig} */
const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';

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

export default nextConfig;
