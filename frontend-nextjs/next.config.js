/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'ap.rdcpix.com',
      },
      {
        protocol: 'https',
        hostname: '*.rdcpix.com',
      },
    ],
  },
}

module.exports = nextConfig
