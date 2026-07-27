import { v4 as uuidv4 } from "uuid";
import { Fragment, ReactNode, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { AgentActivity, useStreamContext } from "@/providers/Stream";
import { useState, FormEvent } from "react";
import { Button } from "../ui/button";
import { Checkpoint, Message } from "@langchain/langgraph-sdk";
import { AssistantMessage, AssistantMessageLoading } from "./messages/ai";
import { HumanMessage } from "./messages/human";
import { AgentOutputCard } from "./agent-output-card";
import {
  DO_NOT_RENDER_ID_PREFIX,
  ensureToolCallsHaveResponses,
} from "@/lib/ensure-tool-responses";
import { LangGraphLogoSVG } from "../icons/langgraph";
import { TooltipIconButton } from "./tooltip-icon-button";
import {
  ArrowDown,
  CheckCircle2,
  Circle,
  LoaderCircle,
  PanelRightOpen,
  PanelRightClose,
  SquarePen,
  XCircle,
  XIcon,
  Plus,
} from "lucide-react";

// ── 任务进度组件 ──────────────────────────────────────────────────────────────
interface TaskItem {
  id: number;
  description: string;
  query?: string;
  agent: string;
  status: "pending" | "in_progress" | "completed" | "error";
  result?: string | null;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "in_progress")
    return (
      <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-amber-500" />
    );
  if (status === "completed")
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />;
  if (status === "error")
    return <XCircle className="h-4 w-4 shrink-0 text-red-500" />;
  return <Circle className="text-foreground/25 h-4 w-4 shrink-0" />;
}

function TaskPlanView({
  tasks,
  activities,
}: {
  tasks: TaskItem[];
  activities: Record<string, AgentActivity>;
}) {
  const done = tasks.filter((t) => t.status === "completed").length;

  const getTaskInput = (task: TaskItem) =>
    task.agent === "search_agent" && task.query?.trim()
      ? task.query.trim()
      : task.description.trim();

  const getTaskOutput = (task: TaskItem) => {
    const result = task.result?.trim();
    if (!result) return "";

    const match = result.match(/^【\w+ 执行结果】\n([\s\S]*)$/);
    if (!match) return result;

    const payload = match[1].trim();
    const input = getTaskInput(task);
    return payload.startsWith(`${input}\n`)
      ? payload.slice(input.length).trim()
      : payload;
  };

  const getActivityOutput = (task: TaskItem) => {
    const entries = activities[String(task.id)]?.entries ?? [];
    const completed = [...entries]
      .reverse()
      .find((entry) => entry.stage === "complete");
    if (completed) return completed.content;

    return entries
      .map((entry) => {
        const label =
          entry.stage === "retry"
            ? "执行重试"
            : entry.stage === "error"
              ? "执行错误"
              : entry.node === "tools"
                ? "工具输出"
                : "当前输出";
        return `### ${label}\n${entry.content}`;
      })
      .join("\n\n");
  };

  return (
    <div className="border-border/50 bg-muted/20 rounded-xl border px-4 py-3 text-sm">
      <p className="text-foreground/50 mb-2 text-xs font-semibold tracking-wide uppercase">
        任务进度 {done}/{tasks.length}
      </p>
      <div className="flex flex-col gap-1.5">
        {tasks.map((t) => {
          const showAgentCard =
            t.status !== "pending" &&
            (t.agent === "search_agent" || t.agent === "image_agent");

          if (showAgentCard) {
            const input = getTaskInput(t);
            return (
              <AgentOutputCard
                key={t.id}
                agentName={t.agent}
                title={input.split("\n")[0]}
                input={input}
                content={getTaskOutput(t) || getActivityOutput(t)}
                status={t.status}
              />
            );
          }

          return (
            <div
              key={t.id}
              className="flex items-center gap-2"
            >
              <StatusIcon status={t.status} />
              <span
                className={cn(
                  "flex-1 truncate",
                  t.status === "completed"
                    ? "text-foreground/40"
                    : "text-foreground/80",
                )}
              >
                {t.id}.&nbsp;{t.description.split("\n")[0].slice(0, 60)}
              </span>
              <span className="text-foreground/30 shrink-0 text-xs">
                [{t.agent}]
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
import { useQueryState, parseAsBoolean } from "nuqs";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import ThreadHistory from "./history";
import { toast } from "sonner";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { GitHubSVG } from "../icons/github";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";
import { useFileUpload } from "@/hooks/use-file-upload";
import { ContentBlocksPreview } from "./ContentBlocksPreview";
import {
  useArtifactOpen,
  ArtifactContent,
  ArtifactTitle,
  useArtifactContext,
} from "./artifact";

function StickyToBottomContent(props: {
  content: ReactNode;
  footer?: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const context = useStickToBottomContext();
  return (
    <div
      ref={context.scrollRef}
      style={{ width: "100%", height: "100%" }}
      className={props.className}
    >
      <div
        ref={context.contentRef}
        className={props.contentClassName}
      >
        {props.content}
      </div>

      {props.footer}
    </div>
  );
}

function ScrollToBottom(props: { className?: string }) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  if (isAtBottom) return null;
  return (
    <Button
      variant="outline"
      className={props.className}
      onClick={() => scrollToBottom()}
    >
      <ArrowDown className="h-4 w-4" />
      <span>滚动到底部</span>
    </Button>
  );
}

function OpenGitHubRepo() {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <a
            href="https://github.com/langchain-ai/agent-chat-ui"
            target="_blank"
            className="flex items-center justify-center"
          >
            <GitHubSVG
              width="24"
              height="24"
            />
          </a>
        </TooltipTrigger>
        <TooltipContent side="left">
          <p>打开 GitHub 仓库</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function Thread() {
  const [artifactContext, setArtifactContext] = useArtifactContext();
  const [artifactOpen, closeArtifact] = useArtifactOpen();

  const [threadId, _setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );
  const [hideToolCalls, setHideToolCalls] = useQueryState(
    "hideToolCalls",
    parseAsBoolean.withDefault(false),
  );
  const [input, setInput] = useState("");
  const {
    contentBlocks,
    setContentBlocks,
    handleFileUpload,
    dropRef,
    removeBlock,
    resetBlocks: _resetBlocks,
    dragOver,
    handlePaste,
  } = useFileUpload();
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");

  const stream = useStreamContext();
  const isLoading = stream.isLoading;
  const taskPlan = (stream.values as Record<string, unknown>)?.task_plan as
    TaskItem[] | undefined;

  const messages = stream.messages.filter(
    (m) => !m.id?.startsWith(DO_NOT_RENDER_ID_PREFIX),
  );

  const lastError = useRef<string | undefined>(undefined);

  const setThreadId = (id: string | null) => {
    _setThreadId(id);

    // close artifact and reset artifact context
    closeArtifact();
    setArtifactContext({});
  };

  useEffect(() => {
    if (!stream.error) {
      lastError.current = undefined;
      return;
    }
    try {
      const message = (stream.error as any).message;
      if (!message || lastError.current === message) {
        // Message has already been logged. do not modify ref, return early.
        return;
      }

      // Message is defined, and it has not been logged yet. Save it, and send the error
      lastError.current = message;
      toast.error("发生错误，请重试。", {
        description: (
          <p>
            <strong>错误：</strong> <code>{message}</code>
          </p>
        ),
        richColors: true,
        closeButton: true,
      });
    } catch {
      // no-op
    }
  }, [stream.error]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if ((input.trim().length === 0 && contentBlocks.length === 0) || isLoading)
      return;

    const newHumanMessage: Message = {
      id: uuidv4(),
      type: "human",
      content: [
        ...(input.trim().length > 0 ? [{ type: "text", text: input }] : []),
        ...contentBlocks,
      ] as Message["content"],
    };

    const toolMessages = ensureToolCallsHaveResponses(stream.messages);

    const context =
      Object.keys(artifactContext).length > 0 ? artifactContext : undefined;

    stream.submit(
      { messages: [...toolMessages, newHumanMessage], context },
      {
        streamMode: ["values", "custom"],
        streamSubgraphs: true,
        streamResumable: true,
        optimisticValues: (prev) => ({
          ...prev,
          context,
          messages: [
            ...(prev.messages ?? []),
            ...toolMessages,
            newHumanMessage,
          ],
        }),
      },
    );

    setInput("");
    setContentBlocks([]);
  };

  const handleRegenerate = (
    parentCheckpoint: Checkpoint | null | undefined,
  ) => {
    stream.submit(undefined, {
      checkpoint: parentCheckpoint,
      streamMode: ["values", "custom"],
      streamSubgraphs: true,
      streamResumable: true,
    });
  };

  const chatStarted = !!threadId || !!messages.length;
  const hasNoAIOrToolMessages = !messages.find(
    (m) => m.type === "ai" || m.type === "tool",
  );

  return (
    <div className="flex h-screen w-full overflow-hidden">
      <div className="relative hidden lg:flex">
        <motion.div
          className="absolute z-20 h-full overflow-hidden border-r bg-white"
          style={{ width: 300 }}
          animate={
            isLargeScreen
              ? { x: chatHistoryOpen ? 0 : -300 }
              : { x: chatHistoryOpen ? 0 : -300 }
          }
          initial={{ x: -300 }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 30 }
              : { duration: 0 }
          }
        >
          <div
            className="relative h-full"
            style={{ width: 300 }}
          >
            <ThreadHistory />
          </div>
        </motion.div>
      </div>

      <div
        className={cn(
          "grid w-full grid-cols-[1fr_0fr] transition-all duration-500",
          artifactOpen && "grid-cols-[3fr_2fr]",
        )}
      >
        <motion.div
          className={cn(
            "relative flex min-w-0 flex-1 flex-col overflow-hidden",
            !chatStarted && "grid-rows-[1fr]",
          )}
          layout={isLargeScreen}
          animate={{
            marginLeft: chatHistoryOpen ? (isLargeScreen ? 300 : 0) : 0,
            width: chatHistoryOpen
              ? isLargeScreen
                ? "calc(100% - 300px)"
                : "100%"
              : "100%",
          }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 30 }
              : { duration: 0 }
          }
        >
          {!chatStarted && (
            <div className="absolute top-0 left-0 z-10 flex w-full items-center justify-between gap-3 p-2 pl-4">
              <div>
                {(!chatHistoryOpen || !isLargeScreen) && (
                  <Button
                    className="hover:bg-gray-100"
                    variant="ghost"
                    onClick={() => setChatHistoryOpen((p) => !p)}
                  >
                    {chatHistoryOpen ? (
                      <PanelRightOpen className="size-5" />
                    ) : (
                      <PanelRightClose className="size-5" />
                    )}
                  </Button>
                )}
              </div>
              <div className="absolute top-2 right-4 flex items-center">
                <OpenGitHubRepo />
              </div>
            </div>
          )}
          {chatStarted && (
            <div className="relative z-10 flex items-center justify-between gap-3 p-2">
              <div className="relative flex items-center justify-start gap-2">
                <div className="absolute left-0 z-10">
                  {(!chatHistoryOpen || !isLargeScreen) && (
                    <Button
                      className="hover:bg-gray-100"
                      variant="ghost"
                      onClick={() => setChatHistoryOpen((p) => !p)}
                    >
                      {chatHistoryOpen ? (
                        <PanelRightOpen className="size-5" />
                      ) : (
                        <PanelRightClose className="size-5" />
                      )}
                    </Button>
                  )}
                </div>
                <motion.button
                  className="flex cursor-pointer items-center gap-2"
                  onClick={() => setThreadId(null)}
                  animate={{
                    marginLeft: !chatHistoryOpen ? 48 : 0,
                  }}
                  transition={{
                    type: "spring",
                    stiffness: 300,
                    damping: 30,
                  }}
                >
                  <LangGraphLogoSVG
                    width={32}
                    height={32}
                  />
                  <span className="text-xl font-semibold tracking-tight">
                    城市治理智能体
                  </span>
                </motion.button>
              </div>

              <div className="flex items-center gap-4">
                <div className="flex items-center">
                  <OpenGitHubRepo />
                </div>
                <TooltipIconButton
                  size="lg"
                  className="p-4"
                  tooltip="新建对话"
                  variant="ghost"
                  onClick={() => setThreadId(null)}
                >
                  <SquarePen className="size-5" />
                </TooltipIconButton>
              </div>

              <div className="from-background to-background/0 absolute inset-x-0 top-full h-5 bg-gradient-to-b" />
            </div>
          )}

          <StickToBottom className="relative flex-1 overflow-hidden">
            <StickyToBottomContent
              className={cn(
                "absolute inset-0 overflow-y-scroll px-4 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 [&::-webkit-scrollbar-track]:bg-transparent",
                !chatStarted && "mt-[25vh] flex flex-col items-stretch",
                chatStarted && "grid grid-rows-[1fr_auto]",
              )}
              contentClassName="pt-8 pb-16 max-w-3xl mx-auto flex flex-col gap-4 w-full"
              content={
                <>
                  {messages.map((message, index) => {
                    // 在最后一条 human 消息后插入任务进度列表
                    const isLastHuman =
                      message.type === "human" &&
                      !messages
                        .slice(index + 1)
                        .some((m) => m.type === "human");
                    return (
                      <Fragment key={message.id || `${message.type}-${index}`}>
                        {message.type === "human" ? (
                          <HumanMessage
                            message={message}
                            isLoading={isLoading}
                          />
                        ) : (
                          <AssistantMessage
                            message={message}
                            isLoading={isLoading}
                            handleRegenerate={handleRegenerate}
                          />
                        )}
                        {isLastHuman && !!taskPlan?.length && (
                          <TaskPlanView
                            tasks={taskPlan}
                            activities={stream.agentActivities}
                          />
                        )}
                      </Fragment>
                    );
                  })}
                  {/* Special rendering case where there are no AI/tool messages, but there is an interrupt.
                    We need to render it outside of the messages list, since there are no messages to render */}
                  {hasNoAIOrToolMessages && !!stream.interrupt && (
                    <AssistantMessage
                      key="interrupt-msg"
                      message={undefined}
                      isLoading={isLoading}
                      handleRegenerate={handleRegenerate}
                    />
                  )}
                  {isLoading &&
                    !taskPlan?.some(
                      (task) => task.status === "in_progress",
                    ) && <AssistantMessageLoading />}
                </>
              }
              footer={
                <div className="sticky bottom-0 flex flex-col items-center gap-8 bg-white">
                  {!chatStarted && (
                    <div className="flex items-center gap-3">
                      <LangGraphLogoSVG className="h-8 flex-shrink-0" />
                      <h1 className="text-2xl font-semibold tracking-tight">
                        城市治理智能体
                      </h1>
                    </div>
                  )}

                  <ScrollToBottom className="animate-in fade-in-0 zoom-in-95 absolute bottom-full left-1/2 mb-4 -translate-x-1/2" />

                  <div
                    ref={dropRef}
                    className={cn(
                      "bg-muted relative z-10 mx-auto mb-8 w-full max-w-3xl rounded-2xl shadow-xs transition-all",
                      dragOver
                        ? "border-primary border-2 border-dotted"
                        : "border border-solid",
                    )}
                  >
                    <form
                      onSubmit={handleSubmit}
                      className="mx-auto grid max-w-3xl grid-rows-[1fr_auto] gap-2"
                    >
                      <ContentBlocksPreview
                        blocks={contentBlocks}
                        onRemove={removeBlock}
                      />
                      <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onPaste={handlePaste}
                        onKeyDown={(e) => {
                          if (
                            e.key === "Enter" &&
                            !e.shiftKey &&
                            !e.metaKey &&
                            !e.nativeEvent.isComposing
                          ) {
                            e.preventDefault();
                            const el = e.target as HTMLElement | undefined;
                            const form = el?.closest("form");
                            form?.requestSubmit();
                          }
                        }}
                        placeholder="请输入消息..."
                        className="field-sizing-content resize-none border-none bg-transparent p-3.5 pb-0 shadow-none ring-0 outline-none focus:ring-0 focus:outline-none"
                      />

                      <div className="flex items-center gap-6 p-2 pt-4">
                        <div>
                          <div className="flex items-center space-x-2">
                            <Switch
                              id="render-tool-calls"
                              checked={hideToolCalls ?? false}
                              onCheckedChange={setHideToolCalls}
                            />
                            <Label
                              htmlFor="render-tool-calls"
                              className="text-sm text-gray-600"
                            >
                              隐藏工具调用
                            </Label>
                          </div>
                        </div>
                        <Label
                          htmlFor="file-input"
                          className="flex cursor-pointer items-center gap-2"
                        >
                          <Plus className="size-5 text-gray-600" />
                          <span className="text-sm text-gray-600">
                            上传 PDF 或图片
                          </span>
                        </Label>
                        <input
                          id="file-input"
                          type="file"
                          onChange={handleFileUpload}
                          multiple
                          accept="image/jpeg,image/png,image/gif,image/webp,application/pdf"
                          className="hidden"
                        />
                        {stream.isLoading ? (
                          <Button
                            key="stop"
                            onClick={() => stream.stop()}
                            className="ml-auto"
                          >
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                            停止生成
                          </Button>
                        ) : (
                          <Button
                            type="submit"
                            className="ml-auto shadow-md transition-all"
                            disabled={
                              isLoading ||
                              (!input.trim() && contentBlocks.length === 0)
                            }
                          >
                            发送
                          </Button>
                        )}
                      </div>
                    </form>
                  </div>
                </div>
              }
            />
          </StickToBottom>
        </motion.div>
        <div className="relative flex flex-col border-l">
          <div className="absolute inset-0 flex min-w-[30vw] flex-col">
            <div className="grid grid-cols-[1fr_auto] border-b p-4">
              <ArtifactTitle className="truncate overflow-hidden" />
              <button
                onClick={closeArtifact}
                className="cursor-pointer"
              >
                <XIcon className="size-5" />
              </button>
            </div>
            <ArtifactContent className="relative flex-grow" />
          </div>
        </div>
      </div>
    </div>
  );
}
