/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  // The Docker image bakes the built static export into backend/awsco/static/
  // and FastAPI serves it on the same origin, so no rewrites needed in prod.
};

export default nextConfig;
