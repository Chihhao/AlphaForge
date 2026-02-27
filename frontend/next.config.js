/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.INTERNAL_API_URL || 'http://alphaforge-backend:8000'}/:path*`, // Proxy to Backend container root (which no longer has /api prefix)
      },
    ]
  },
}

module.exports = nextConfig
