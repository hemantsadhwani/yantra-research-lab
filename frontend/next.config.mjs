/** @type {import('next').NextConfig} */
// STATIC_EXPORT=1 builds the static site for S3 + CloudFront (frontend/deploy_aws.sh).
// Otherwise a self-contained server (.next/standalone) for the Docker image in frontend/Dockerfile.
const isStatic = process.env.STATIC_EXPORT === "1";

const nextConfig = {
  reactStrictMode: true,
  ...(isStatic
    ? { output: "export", trailingSlash: true, images: { unoptimized: true } }
    : { output: "standalone" }),
};

export default nextConfig;
