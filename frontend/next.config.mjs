/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server (.next/standalone) for the Docker image in frontend/Dockerfile.
  // Vercel ignores this setting, so the public deploy is unchanged.
  output: "standalone",
};

export default nextConfig;
