import React, {
  createContext,
  useContext,
  ReactNode,
  useState,
  useEffect,
  useRef,
} from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import { type Message } from "@langchain/langgraph-sdk";
import {
  uiMessageReducer,
  isUIMessage,
  isRemoveUIMessage,
  type UIMessage,
  type RemoveUIMessage,
} from "@langchain/langgraph-sdk/react-ui";
import { useQueryState } from "nuqs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { LangGraphLogoSVG } from "@/components/icons/langgraph";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ArrowRight } from "lucide-react";
import { PasswordInput } from "@/components/ui/password-input";
import { getApiKey } from "@/lib/api-key";
import { useThreads } from "./Thread";
import { resolveApiUrl } from "./client";
import { toast } from "sonner";

export type AgentActivityEvent = {
  type: "agent_activity";
  task_id: string | number;
  agent: string;
  stage: "start" | "output" | "complete" | "retry" | "error";
  node?: string;
  input?: string;
  content?: string;
};

export type AgentActivity = {
  agent: string;
  input: string;
  entries: Array<{
    stage: AgentActivityEvent["stage"];
    node: string;
    content: string;
  }>;
};

export type StateType = { messages: Message[]; ui?: UIMessage[] };

const useTypedStream = useStream<
  StateType,
  {
    UpdateType: {
      messages?: Message[] | Message | string;
      ui?: (UIMessage | RemoveUIMessage)[] | UIMessage | RemoveUIMessage;
      context?: Record<string, unknown>;
    };
    CustomEventType: UIMessage | RemoveUIMessage | AgentActivityEvent;
  }
>;

type StreamContextType = ReturnType<typeof useTypedStream> & {
  agentActivities: Record<string, AgentActivity>;
};
const StreamContext = createContext<StreamContextType | undefined>(undefined);

function isAgentActivityEvent(event: unknown): event is AgentActivityEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "agent_activity" &&
    "task_id" in event
  );
}

async function sleep(ms = 4000) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function checkGraphStatus(
  apiUrl: string,
  apiKey: string | null,
  authScheme?: string,
): Promise<boolean> {
  try {
    const headers = new Headers();
    if (apiKey) headers.set("X-Api-Key", apiKey);
    if (authScheme) headers.set("X-Auth-Scheme", authScheme);

    const res = await fetch(`${apiUrl}/info`, {
      headers,
    });

    return res.ok;
  } catch (e) {
    console.error(e);
    return false;
  }
}

const StreamSessionInner = ({
  children,
  apiKey,
  apiUrl,
  assistantId,
  authScheme,
  isCreatingRef,
}: {
  children: ReactNode;
  apiKey: string | null;
  apiUrl: string;
  assistantId: string;
  authScheme?: string;
  isCreatingRef: React.MutableRefObject<boolean>;
}) => {
  const [threadId, setThreadId] = useQueryState("threadId");
  const { getThreads, setThreads } = useThreads();
  const [agentActivities, setAgentActivities] = useState<
    Record<string, AgentActivity>
  >({});

  const streamValue = useTypedStream({
    apiUrl,
    apiKey: apiKey ?? undefined,
    assistantId,
    ...(authScheme && {
      defaultHeaders: {
        "X-Auth-Scheme": authScheme,
      },
    }),
    threadId: threadId ?? null,
    fetchStateHistory: true,
    onCustomEvent: (event, options) => {
      if (isAgentActivityEvent(event)) {
        const taskId = String(event.task_id);
        setAgentActivities((previous) => {
          if (event.stage === "start") {
            return {
              ...previous,
              [taskId]: {
                agent: event.agent,
                input: event.input ?? "",
                entries: [],
              },
            };
          }

          const current = previous[taskId] ?? {
            agent: event.agent,
            input: event.input ?? "",
            entries: [],
          };
          const content = event.content?.trim() ?? "";
          if (!content) return previous;

          const lastEntry = current.entries[current.entries.length - 1];
          if (
            lastEntry?.stage === event.stage &&
            lastEntry.node === (event.node ?? "") &&
            lastEntry.content === content
          ) {
            return previous;
          }

          return {
            ...previous,
            [taskId]: {
              ...current,
              entries: [
                ...current.entries,
                {
                  stage: event.stage,
                  node: event.node ?? "",
                  content,
                },
              ],
            },
          };
        });
        return;
      }

      if (isUIMessage(event) || isRemoveUIMessage(event)) {
        options.mutate((prev) => {
          const ui = uiMessageReducer(prev.ui ?? [], event);
          return { ...prev, ui };
        });
      }
    },
    onThreadId: (id) => {
      isCreatingRef.current = true;
      setThreadId(id);
      sleep().then(() => getThreads().then(setThreads).catch(console.error));
    },
  });

  useEffect(() => {
    checkGraphStatus(apiUrl, apiKey, authScheme).then((ok) => {
      if (!ok) {
        toast.error("无法连接到 LangGraph 服务", {
          description: () => (
            <p>
              Please ensure your graph is running at <code>{apiUrl}</code> and
              your API key is correctly set (if connecting to a deployed graph).
            </p>
          ),
          duration: 10000,
          richColors: true,
          closeButton: true,
        });
      }
    });
  }, [apiKey, apiUrl, authScheme]);

  return (
    <StreamContext.Provider value={{ ...streamValue, agentActivities }}>
      {children}
    </StreamContext.Provider>
  );
};

const StreamSession = ({
  children,
  apiKey,
  apiUrl,
  assistantId,
  authScheme,
}: {
  children: ReactNode;
  apiKey: string | null;
  apiUrl: string;
  assistantId: string;
  authScheme?: string;
}) => {
  const [threadId] = useQueryState("threadId");
  const [sessionKey, setSessionKey] = useState(0);
  const prevThreadIdRef = useRef(threadId);
  const isCreatingRef = useRef(false);

  useEffect(() => {
    if (threadId !== prevThreadIdRef.current) {
      if (!isCreatingRef.current && threadId !== null) {
        setSessionKey((k) => k + 1);
      }
      prevThreadIdRef.current = threadId;
      isCreatingRef.current = false;
    }
  }, [threadId]);

  return (
    <StreamSessionInner
      key={sessionKey}
      apiKey={apiKey}
      apiUrl={apiUrl}
      assistantId={assistantId}
      authScheme={authScheme}
      isCreatingRef={isCreatingRef}
    >
      {children}
    </StreamSessionInner>
  );
};

// Default values for the form
const DEFAULT_API_URL = "http://localhost:2024";
const DEFAULT_ASSISTANT_ID = "agent";
const AGENT_BUILDER_AUTH_SCHEME = "langsmith-api-key";

export const StreamProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  // Get environment variables
  const envApiUrl: string | undefined = process.env.NEXT_PUBLIC_API_URL;
  const envAssistantId: string | undefined =
    process.env.NEXT_PUBLIC_ASSISTANT_ID;
  const envAuthScheme: string | undefined = process.env.NEXT_PUBLIC_AUTH_SCHEME;

  // Use URL params with env var fallbacks
  const [apiUrl, setApiUrl] = useQueryState("apiUrl", {
    defaultValue: envApiUrl || "",
  });
  const [assistantId, setAssistantId] = useQueryState("assistantId", {
    defaultValue: envAssistantId || "",
  });
  const [authScheme, setAuthScheme] = useQueryState("authScheme", {
    defaultValue: envAuthScheme || "",
  });
  const [isAgentBuilder, setIsAgentBuilder] = useState(
    () =>
      (authScheme || envAuthScheme || "").toLowerCase() ===
      AGENT_BUILDER_AUTH_SCHEME,
  );

  // For API key, use localStorage with env var fallback
  const [apiKey, _setApiKey] = useState(() => {
    const storedKey = getApiKey();
    return storedKey || "";
  });

  const setApiKey = (key: string) => {
    window.localStorage.setItem("lg:chat:apiKey", key);
    _setApiKey(key);
  };

  // Determine final values to use, prioritizing URL params then env vars
  const finalApiUrl = resolveApiUrl(apiUrl || envApiUrl || "");
  const finalAssistantId = assistantId || envAssistantId;
  const finalAuthScheme = authScheme || envAuthScheme || "";

  // Show the form if we: don't have an API URL, or don't have an assistant ID
  if (!finalApiUrl || !finalAssistantId) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center p-4">
        <div className="animate-in fade-in-0 zoom-in-95 bg-background flex max-w-3xl flex-col rounded-lg border shadow-lg">
          <div className="mt-14 flex flex-col gap-2 border-b p-6">
            <div className="flex flex-col items-start gap-2">
              <LangGraphLogoSVG className="h-7" />
              <h1 className="text-xl font-semibold tracking-tight">
                城市治理智能体
              </h1>
            </div>
            <p className="text-muted-foreground">
              欢迎使用城市治理智能体！开始前，请输入部署地址以及 assistant /
              graph ID。
            </p>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();

              const form = e.target as HTMLFormElement;
              const formData = new FormData(form);
              const apiUrl = formData.get("apiUrl") as string;
              const assistantId = formData.get("assistantId") as string;
              const apiKey = formData.get("apiKey") as string;

              setApiUrl(apiUrl);
              setApiKey(apiKey);
              setAssistantId(assistantId);
              setAuthScheme(isAgentBuilder ? AGENT_BUILDER_AUTH_SCHEME : "");

              form.reset();
            }}
            className="bg-muted/50 flex flex-col gap-6 p-6"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="apiUrl">
                服务地址<span className="text-rose-500">*</span>
              </Label>
              <p className="text-muted-foreground text-sm">
                LangGraph 服务的访问地址，可以是本地服务或生产环境地址。
              </p>
              <Input
                id="apiUrl"
                name="apiUrl"
                className="bg-background"
                defaultValue={apiUrl || DEFAULT_API_URL}
                required
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="assistantId">
                助手 / 图 ID<span className="text-rose-500">*</span>
              </Label>
              <p className="text-muted-foreground text-sm">
                用于读取历史对话和执行请求的图或助手 ID，也可以填写图名称。
              </p>
              <Input
                id="assistantId"
                name="assistantId"
                className="bg-background"
                defaultValue={assistantId || DEFAULT_ASSISTANT_ID}
                required
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="apiKey">LangSmith API 密钥</Label>
              <p className="text-muted-foreground text-sm">
                使用本地 LangGraph 服务时<strong>无需填写</strong>。该值只保存在
                浏览器本地存储中，用于验证发送到 LangGraph 服务的请求。
              </p>
              <PasswordInput
                id="apiKey"
                name="apiKey"
                defaultValue={apiKey ?? ""}
                className="bg-background"
                placeholder="lsv2_pt_..."
              />
            </div>

            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="agentBuilderEnabled">
                    使用 Agent Builder 构建
                  </Label>
                  <p className="text-muted-foreground text-sm">
                    如果服务由 Agent Builder 部署，请启用此选项。
                  </p>
                </div>
                <Switch
                  id="agentBuilderEnabled"
                  checked={isAgentBuilder}
                  onCheckedChange={setIsAgentBuilder}
                />
              </div>
            </div>

            <div className="mt-2 flex justify-end">
              <Button
                type="submit"
                size="lg"
              >
                继续
                <ArrowRight className="size-5" />
              </Button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <StreamSession
      apiKey={apiKey}
      apiUrl={finalApiUrl}
      assistantId={finalAssistantId}
      authScheme={finalAuthScheme || undefined}
    >
      {children}
    </StreamSession>
  );
};

// Create a custom hook to use the context
export const useStreamContext = (): StreamContextType => {
  const context = useContext(StreamContext);
  if (context === undefined) {
    throw new Error("useStreamContext must be used within a StreamProvider");
  }
  return context;
};

export default StreamContext;
