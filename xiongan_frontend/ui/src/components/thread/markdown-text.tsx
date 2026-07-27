"use client";

import "./markdown-styles.css";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import { FC, memo, useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { SyntaxHighlighter } from "@/components/thread/syntax-highlighter";

import { TooltipIconButton } from "@/components/thread/tooltip-icon-button";
import { cn } from "@/lib/utils";
import { copyToClipboard as writeToClipboard } from "@/lib/copy-to-clipboard";

import "katex/dist/katex.min.css";

/**
 * 模型偶尔会把整个来源列表压成一个段落。这里在渲染前统一整理，
 * 既能修复新回复，也能改善 SQLite 中已经保存的历史消息。
 */
function normalizeSourceList(markdown: string): string {
  const sourceHeading =
    /(^|\n)[ \t]*(?:#{1,6}[ \t]+)?来源[ \t]*(?:\n|(?=(?:[-*][ \t]*)?\[\d+\]))/gm;
  let lastMatch: RegExpExecArray | null = null;
  let match: RegExpExecArray | null;

  while ((match = sourceHeading.exec(markdown)) !== null) {
    lastMatch = match;
  }

  if (!lastMatch) return markdown;

  const headingStart = lastMatch.index + (lastMatch[1] ? 1 : 0);
  const sourceStart = lastMatch.index + lastMatch[0].length;
  const report = markdown.slice(0, headingStart).trimEnd();
  const sourceText = markdown.slice(sourceStart).trim();
  if (!sourceText) return markdown;

  const entries = sourceText
    .replace(/^[ \t]*[-*][ \t]+/gm, "")
    .replace(/\s+(?=\[\d+\][ \t]+)/g, "\n")
    .split(/\n+/)
    .map((entry) => entry.trim())
    .filter(Boolean);

  if (!entries.length) return markdown;

  // 来源用占位标记包裹，MarkdownTextImpl 会把它替换成紧凑容器（来源专用字号/行距），
  // 避免复用正文 <p> 的大行距；内容为 [n] 标题 - url 逐行排列，无列表圆点。
  // 仅做排版改善，不修改任何编号——编号语义由后端报告合并节点决定。
  return `${report}\n\n## 来源\n\n<!--sources-->\n${entries.join("\n\n")}\n<!--/sources-->`;
}

interface CodeHeaderProps {
  language?: string;
  code: string;
}

const useCopyToClipboard = ({
  copiedDuration = 3000,
}: {
  copiedDuration?: number;
} = {}) => {
  const [isCopied, setIsCopied] = useState<boolean>(false);

  const copyToClipboard = async (value: string) => {
    if (!value) return;

    if (!(await writeToClipboard(value))) return;
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), copiedDuration);
  };

  return { isCopied, copyToClipboard };
};

const CodeHeader: FC<CodeHeaderProps> = ({ language, code }) => {
  const { isCopied, copyToClipboard } = useCopyToClipboard();
  const onCopy = () => {
    if (!code || isCopied) return;
    copyToClipboard(code);
  };

  return (
    <div className="flex items-center justify-between gap-4 rounded-t-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white">
      <span className="lowercase [&>span]:text-xs">{language}</span>
      <TooltipIconButton
        tooltip="复制"
        onClick={onCopy}
      >
        {!isCopied && <CopyIcon />}
        {isCopied && <CheckIcon />}
      </TooltipIconButton>
    </div>
  );
};

const defaultComponents: any = {
  h1: ({ className, ...props }: { className?: string }) => (
    <h1
      className={cn(
        "mb-8 scroll-m-20 text-4xl font-extrabold tracking-tight last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h2: ({ className, ...props }: { className?: string }) => (
    <h2
      className={cn(
        "mt-8 mb-4 scroll-m-20 text-3xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h3: ({ className, ...props }: { className?: string }) => (
    <h3
      className={cn(
        "mt-6 mb-4 scroll-m-20 text-2xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h4: ({ className, ...props }: { className?: string }) => (
    <h4
      className={cn(
        "mt-6 mb-4 scroll-m-20 text-xl font-semibold tracking-tight first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h5: ({ className, ...props }: { className?: string }) => (
    <h5
      className={cn(
        "my-4 text-lg font-semibold first:mt-0 last:mb-0",
        className,
      )}
      {...props}
    />
  ),
  h6: ({ className, ...props }: { className?: string }) => (
    <h6
      className={cn("my-4 font-semibold first:mt-0 last:mb-0", className)}
      {...props}
    />
  ),
  p: ({ className, ...props }: { className?: string }) => (
    <p
      className={cn("mt-5 mb-5 leading-7 first:mt-0 last:mb-0", className)}
      {...props}
    />
  ),
  a: ({ className, ...props }: { className?: string }) => (
    <a
      className={cn(
        "text-primary font-medium underline underline-offset-4",
        className,
      )}
      {...props}
    />
  ),
  blockquote: ({ className, ...props }: { className?: string }) => (
    <blockquote
      className={cn("border-l-2 pl-6 italic", className)}
      {...props}
    />
  ),
  ul: ({ className, ...props }: { className?: string }) => (
    <ul
      className={cn("my-5 ml-6 list-disc [&>li]:mt-2", className)}
      {...props}
    />
  ),
  ol: ({ className, ...props }: { className?: string }) => (
    <ol
      className={cn("my-5 ml-6 list-decimal [&>li]:mt-2", className)}
      {...props}
    />
  ),
  hr: ({ className, ...props }: { className?: string }) => (
    <hr
      className={cn("my-5 border-b", className)}
      {...props}
    />
  ),
  table: ({ className, ...props }: { className?: string }) => (
    <table
      className={cn(
        "my-5 w-full border-separate border-spacing-0 overflow-y-auto",
        className,
      )}
      {...props}
    />
  ),
  th: ({ className, ...props }: { className?: string }) => (
    <th
      className={cn(
        "bg-muted px-4 py-2 text-left font-bold first:rounded-tl-lg last:rounded-tr-lg [&[align=center]]:text-center [&[align=right]]:text-right",
        className,
      )}
      {...props}
    />
  ),
  td: ({ className, ...props }: { className?: string }) => (
    <td
      className={cn(
        "border-b border-l px-4 py-2 text-left last:border-r [&[align=center]]:text-center [&[align=right]]:text-right",
        className,
      )}
      {...props}
    />
  ),
  tr: ({ className, ...props }: { className?: string }) => (
    <tr
      className={cn(
        "m-0 border-b p-0 first:border-t [&:last-child>td:first-child]:rounded-bl-lg [&:last-child>td:last-child]:rounded-br-lg",
        className,
      )}
      {...props}
    />
  ),
  sup: ({ className, ...props }: { className?: string }) => (
    <sup
      className={cn("[&>a]:text-xs [&>a]:no-underline", className)}
      {...props}
    />
  ),
  pre: ({ className, ...props }: { className?: string }) => (
    <pre
      className={cn(
        "max-w-4xl overflow-x-auto rounded-lg bg-black text-white",
        className,
      )}
      {...props}
    />
  ),
  code: ({
    className,
    children,
    ...props
  }: {
    className?: string;
    children: React.ReactNode;
  }) => {
    const match = /language-(\w+)/.exec(className || "");

    if (match) {
      const language = match[1];
      const code = String(children).replace(/\n$/, "");

      return (
        <>
          <CodeHeader
            language={language}
            code={code}
          />
          <SyntaxHighlighter
            language={language}
            className={className}
          >
            {code}
          </SyntaxHighlighter>
        </>
      );
    }

    return (
      <code
        className={cn("rounded font-semibold", className)}
        {...props}
      >
        {children}
      </code>
    );
  },
};

const SOURCES_OPEN = "<!--sources-->";
const SOURCES_CLOSE = "<!--/sources-->";

const MarkdownTextImpl: FC<{ children: string }> = ({ children }) => {
  const normalizedMarkdown = normalizeSourceList(children);

  // normalizeSourceList 会把「## 来源」之后的条目放进 <!--sources--> 标记。
  // 这里把它单独切出来，套一层 .markdown-sources 容器：来源用更紧凑的
  // 字号与行距，不复用正文 <p> 的大行距。
  const openIdx = normalizedMarkdown.indexOf(SOURCES_OPEN);
  let body = normalizedMarkdown;
  let sources = "";
  if (openIdx !== -1) {
    const closeIdx = normalizedMarkdown.indexOf(SOURCES_CLOSE, openIdx);
    if (closeIdx !== -1) {
      body = normalizedMarkdown.slice(0, openIdx).trimEnd();
      sources = normalizedMarkdown
        .slice(openIdx + SOURCES_OPEN.length, closeIdx)
        .trim();
    }
  }

  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={defaultComponents}
      >
        {body}
      </ReactMarkdown>
      {sources && (
        <div className="markdown-sources">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={defaultComponents}
          >
            {sources}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
};

export const MarkdownText = memo(MarkdownTextImpl);
