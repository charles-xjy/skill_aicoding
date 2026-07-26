import { Client } from "@langchain/langgraph-sdk";

// 支持 NEXT_PUBLIC_API_URL=/api 这类相对地址，局域网访问时自动解析到当前前端域名。
export function resolveApiUrl(apiUrl: string): string {
  if (!apiUrl || typeof window === "undefined") return apiUrl;

  const base = window.location.origin;
  if (!/^https?:\/\//i.test(apiUrl)) {
    return apiUrl.startsWith("/") ? `${base}${apiUrl}` : `${base}/${apiUrl}`;
  }

  const url = new URL(apiUrl);
  const browserHost = window.location.hostname;
  const loopbackHosts = new Set(["localhost", "127.0.0.1", "::1"]);

  // 0.0.0.0 is a bind address, not a browser destination. Likewise, when the
  // UI is opened over the LAN, localhost points to the visitor's own device.
  if (
    url.hostname === "0.0.0.0" ||
    (loopbackHosts.has(url.hostname) && !loopbackHosts.has(browserHost))
  ) {
    url.hostname = browserHost;
  }

  return url.toString().replace(/\/$/, "");
}

export function createClient(
  apiUrl: string,
  apiKey: string | undefined,
  authScheme: string | undefined,
) {
  return new Client({
    apiKey,
    apiUrl: resolveApiUrl(apiUrl),
    ...(authScheme && {
      defaultHeaders: {
        "X-Auth-Scheme": authScheme,
      },
    }),
  });
}
