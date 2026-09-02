// Railway's healthcheck probes /health on every service; the api answers with
// its own liveness report, and this keeps the web container from being marked
// dead while serving fine.
export function GET() {
  return Response.json({ status: "ok" });
}
