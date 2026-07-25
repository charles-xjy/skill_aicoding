import { Client } from "@langchain/langgraph-sdk";

// 支持 NEXT_PUBLIC_API_URL=/api 这类相对地址，局域网访问时自动解析到当前前端域名。
export function resolveApiUrl(apiUrl: string): string {
  if (!apiUrl || /^https?:\/\//i.test(apiUrl)) return apiUrl;
  if (typeof window === "undefined") return apiUrl;
  const base = window.location.origin;
  return apiUrl.startsWith("/") ? `${base}${apiUrl}` : `${base}/${apiUrl}`;
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
