import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  SURF_MCP_CONTAINER: DurableObjectNamespace;
  MCP_PATH_TOKEN: string;
}

export class SurfMcpContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "30m";
  enableInternet = true;
}

function hidden(): Response {
  return new Response("Not found", { status: 404 });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const expected = env.MCP_PATH_TOKEN && `/mcp/${env.MCP_PATH_TOKEN}`;

    if (!expected || url.pathname !== expected) {
      return hidden();
    }

    url.pathname = "/mcp";
    url.search = "";
    const upstream = new Request(url.toString(), request);
    return getContainer(env.SURF_MCP_CONTAINER, "primary").fetch(upstream);
  },
};
