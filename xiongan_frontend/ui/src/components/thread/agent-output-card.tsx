import { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  XCircle,
} from "lucide-react";
import { MarkdownText } from "./markdown-text";

export type AgentTaskStatus = "pending" | "in_progress" | "completed" | "error";

const AGENT_LABEL: Record<string, string> = {
  image_agent: "🛰 卫星影像",
  search_agent: "🔍 网络搜索",
};

function extractImageFiles(text: string): string[] {
  const matches =
    text.match(/[\w一-鿿\-（）()]+_\d{4}\.(jpg|jpeg|png)/gi) ?? [];
  return [...new Set(matches)];
}

function StatusBadge({ status }: { status: AgentTaskStatus }) {
  if (status === "in_progress") {
    return (
      <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-amber-600">
        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
        运行中
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-red-500">
        <XCircle className="h-3.5 w-3.5" />
        执行失败
      </span>
    );
  }
  return (
    <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-green-600">
      <CheckCircle2 className="h-3.5 w-3.5" />
      已完成
    </span>
  );
}

export function AgentOutputCard({
  agentName,
  title,
  input,
  content,
  status,
}: {
  agentName: string;
  title: string;
  input: string;
  content: string;
  status: AgentTaskStatus;
}) {
  const [open, setOpen] = useState(false);
  const label = AGENT_LABEL[agentName] ?? agentName;
  const imageFiles =
    agentName === "image_agent" ? extractImageFiles(content) : [];
  const sourceSection = content.split("## 来源")[1];
  const sourceCount = sourceSection
    ? (sourceSection.match(/^\s*(?:[-*]\s*)?\[\d+\]/gm) ?? []).length ||
      undefined
    : undefined;

  return (
    <div className="border-border/40 bg-background/70 rounded-lg border text-sm">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="text-foreground/40 h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronRight className="text-foreground/40 h-3.5 w-3.5 shrink-0" />
        )}
        <span className="text-foreground/60 shrink-0 font-medium">{label}</span>
        <span className="text-foreground/45 truncate text-xs">{title}</span>
        {!open && status === "completed" && sourceCount != null ? (
          <span className="bg-foreground/5 text-foreground/40 ml-auto shrink-0 rounded-full px-1.5 py-0.5 text-[10px]">
            {sourceCount} 条来源
          </span>
        ) : (
          !open && <StatusBadge status={status} />
        )}
      </button>

      {open && (
        <div className="border-border/30 text-foreground/70 space-y-3 border-t px-3 py-3">
          <div>
            <p className="text-foreground/40 mb-1 text-[11px] font-medium">
              输入
            </p>
            <p className="text-xs whitespace-pre-wrap">{input}</p>
          </div>

          {content ? (
            <>
              <div>
                <p className="text-foreground/40 mb-1 text-[11px] font-medium">
                  输出
                </p>
                <MarkdownText>{content}</MarkdownText>
              </div>
              {imageFiles.length > 0 && (
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
                  {imageFiles.map((file) => (
                    <a
                      key={file}
                      href={`/api/local-image?file=${encodeURIComponent(file)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group relative"
                    >
                      <img
                        src={`/api/local-image?file=${encodeURIComponent(file)}`}
                        alt={file}
                        className="aspect-square w-full rounded object-cover transition-opacity group-hover:opacity-80"
                      />
                      <span className="absolute right-0 bottom-0 left-0 truncate rounded-b bg-black/50 px-1 py-0.5 text-center text-[10px] text-white">
                        {file.match(/_(\d{4})\./)?.[1] ?? file}
                      </span>
                    </a>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-foreground/40 text-xs">
              {status === "in_progress"
                ? "子 Agent 正在执行，输出将在生成后显示。"
                : "暂无输出。"}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
