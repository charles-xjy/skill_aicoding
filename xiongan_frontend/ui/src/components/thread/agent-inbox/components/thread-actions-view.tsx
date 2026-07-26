import { useCallback, useEffect, useMemo, useState } from "react";
import { Interrupt } from "@langchain/langgraph-sdk";
import { Button } from "@/components/ui/button";
import { ThreadIdCopyable } from "./thread-id";
import { InboxItemInput } from "./inbox-item-input";
import useInterruptedActions from "../hooks/use-interrupted-actions";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useQueryState } from "nuqs";
import { constructOpenInStudioURL, buildDecisionFromState } from "../utils";
import { Decision, HITLRequest, DecisionType, ActionRequest } from "../types";
import { useStreamContext } from "@/providers/Stream";

interface ThreadActionsViewProps {
  interrupt: Interrupt<HITLRequest>;
  handleShowSidePanel: (showState: boolean, showDescription: boolean) => void;
  showState: boolean;
  showDescription: boolean;
}

function ButtonGroup({
  handleShowState,
  handleShowDescription,
  showingState,
  showingDescription,
}: {
  handleShowState: () => void;
  handleShowDescription: () => void;
  showingState: boolean;
  showingDescription: boolean;
}) {
  return (
    <div className="flex flex-row items-center justify-center gap-0">
      <Button
        variant="outline"
        className={cn(
          "rounded-l-md rounded-r-none border-r-[0px]",
          showingState ? "text-black" : "bg-white",
        )}
        size="sm"
        onClick={handleShowState}
      >
        状态
      </Button>
      <Button
        variant="outline"
        className={cn(
          "rounded-l-none rounded-r-md border-l-[0px]",
          showingDescription ? "text-black" : "bg-white",
        )}
        size="sm"
        onClick={handleShowDescription}
      >
        说明
      </Button>
    </div>
  );
}

function isValidHitlRequest(
  interrupt: Interrupt<HITLRequest>,
): interrupt is Interrupt<HITLRequest> & { value: HITLRequest } {
  return (
    !!interrupt.value &&
    Array.isArray(interrupt.value.action_requests) &&
    interrupt.value.action_requests.length > 0 &&
    Array.isArray(interrupt.value.review_configs) &&
    interrupt.value.review_configs.length > 0
  );
}

function getDecisionStatus(
  decision: Decision | undefined,
): DecisionType | null {
  if (!decision) return null;
  return decision.type;
}

function getActionTitle(action?: ActionRequest) {
  return action?.name ?? "未知确认请求";
}

export function ThreadActionsView({
  interrupt,
  handleShowSidePanel,
  showDescription,
  showState,
}: ThreadActionsViewProps) {
  const stream = useStreamContext();
  const [threadId] = useQueryState("threadId");
  const [apiUrl] = useQueryState("apiUrl");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [addressedActions, setAddressedActions] = useState<
    Map<number, Decision>
  >(new Map());
  const [submittingAll, setSubmittingAll] = useState(false);

  const hitlValue = interrupt.value;
  const actionRequests = useMemo(
    () => hitlValue?.action_requests ?? [],
    [hitlValue?.action_requests],
  );
  const reviewConfigs = useMemo(
    () => hitlValue?.review_configs ?? [],
    [hitlValue?.review_configs],
  );

  const hasMultipleActions = actionRequests.length > 1;
  const currentAction = actionRequests[currentIndex];
  const matchingConfig =
    reviewConfigs.find(
      (config) => config.action_name === currentAction?.name,
    ) ?? reviewConfigs[currentIndex];

  const singleActionInterrupt = useMemo(() => {
    if (!currentAction || !matchingConfig) {
      return interrupt;
    }

    return {
      ...interrupt,
      value: {
        action_requests: [currentAction],
        review_configs: [matchingConfig],
      },
    };
  }, [interrupt, currentAction, matchingConfig]);

  const {
    approveAllowed,
    hasEdited,
    hasAddedResponse,
    streaming,
    supportsMultipleMethods,
    streamFinished,
    loading,
    handleSubmit,
    handleResolve,
    setSelectedSubmitType,
    setHasAddedResponse,
    setHasEdited,
    humanResponse,
    setHumanResponse,
    selectedSubmitType,
    initialHumanInterruptEditValue,
  } = useInterruptedActions({
    interrupt: singleActionInterrupt,
  });

  useEffect(() => {
    setCurrentIndex(0);
    setAddressedActions(new Map());
  }, [interrupt]);

  const handleOpenInStudio = () => {
    if (!apiUrl) {
      toast.error("错误", {
        description: "请先在设置中填写 LangGraph 服务地址。",
        duration: 5000,
        richColors: true,
        closeButton: true,
      });
      return;
    }

    const studioUrl = constructOpenInStudioURL(apiUrl, threadId ?? undefined);
    window.open(studioUrl, "_blank");
  };

  const handleApproveAll = useCallback(() => {
    if (!hasMultipleActions) return;

    try {
      const allDecisions: Decision[] = actionRequests.map(() => ({
        type: "approve",
      }));

      stream.submit(
        {},
        {
          command: {
            resume: { decisions: allDecisions },
          },
        },
      );

      toast("操作成功", {
        description: "已批准全部操作。",
        duration: 5000,
      });
    } catch (error) {
      console.error("Error approving all actions", error);
      toast.error("错误", {
        description: "无法批准全部操作。",
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
    }
  }, [actionRequests, hasMultipleActions, stream]);

  const handleSubmitAll = useCallback(() => {
    if (!hasMultipleActions) return;

    if (addressedActions.size !== actionRequests.length) {
      toast.error("错误", {
        description: `请先处理全部 ${actionRequests.length} 项操作，再统一提交。`,
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
      return;
    }

    try {
      setSubmittingAll(true);
      const allDecisions = actionRequests.map((_, index) => {
        const decision = addressedActions.get(index);
        if (!decision) {
          throw new Error(`Missing decision for action ${index + 1}`);
        }
        return decision;
      });

      stream.submit(
        {},
        {
          command: {
            resume: { decisions: allDecisions },
          },
        },
      );

      toast("提交成功", {
        description: "全部操作已成功提交。",
        duration: 5000,
      });
      setAddressedActions(new Map());
    } catch (error) {
      console.error("Error submitting all actions", error);
      toast.error("错误", {
        description: "操作提交失败。",
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
    } finally {
      setSubmittingAll(false);
    }
  }, [actionRequests, addressedActions, hasMultipleActions, stream]);

  const allAllowApprove = useMemo(() => {
    if (!hasMultipleActions) return false;
    return actionRequests.every((actionRequest) => {
      const matching = reviewConfigs.find(
        (config) => config.action_name === actionRequest.name,
      );
      return matching?.allowed_decisions.includes("approve");
    });
  }, [actionRequests, reviewConfigs, hasMultipleActions]);

  const handleSaveDecision = () => {
    const { decision, error } = buildDecisionFromState(
      humanResponse,
      selectedSubmitType,
    );

    if (!decision || error) {
      toast.error("错误", {
        description: error ?? "无法确定处理决定。",
        richColors: true,
        closeButton: true,
        duration: 5000,
      });
      return;
    }

    setAddressedActions((prev) => {
      const next = new Map(prev);
      next.set(currentIndex, decision);
      return next;
    });

    toast("已保存", {
      description: `第 ${currentIndex + 1} 项操作已记录。`,
      duration: 3000,
    });

    if (currentIndex < actionRequests.length - 1) {
      setCurrentIndex((prev) => Math.min(actionRequests.length - 1, prev + 1));
    }
  };

  const currentTitle = getActionTitle(currentAction);
  const actionsDisabled = loading || streaming || submittingAll;
  const hasAllDecisions =
    hasMultipleActions && addressedActions.size === actionRequests.length;

  if (!isValidHitlRequest(interrupt)) {
    return (
      <div className="flex min-h-full w-full flex-col items-center justify-center rounded-2xl bg-gray-50/50 p-8">
        <p className="text-sm text-gray-600">
          无法显示人工确认内容，收到的数据格式不符合预期。
        </p>
      </div>
    );
  }
  const interruptValue = singleActionInterrupt.value as HITLRequest;

  return (
    <div className="flex min-h-full w-full max-w-full flex-col gap-9">
      <div className="flex w-full flex-wrap items-center justify-between gap-3">
        <div className="flex items-center justify-start gap-3">
          <p className="text-2xl tracking-tighter text-pretty">
            {hasMultipleActions
              ? `${currentTitle} (${currentIndex + 1}/${actionRequests.length})`
              : currentTitle}
          </p>
          {threadId && <ThreadIdCopyable threadId={threadId} />}
        </div>
        <div className="flex flex-row items-center justify-start gap-2">
          {apiUrl && (
            <Button
              size="sm"
              variant="outline"
              className="flex items-center gap-1 bg-white"
              onClick={handleOpenInStudio}
            >
              在 Studio 中打开
            </Button>
          )}
          <ButtonGroup
            handleShowState={() => handleShowSidePanel(true, false)}
            handleShowDescription={() => handleShowSidePanel(false, true)}
            showingState={showState}
            showingDescription={showDescription}
          />
        </div>
      </div>

      <div className="flex w-full flex-row flex-wrap items-center justify-start gap-2">
        <Button
          variant="outline"
          className="border-gray-500 bg-white font-normal text-gray-800"
          onClick={handleResolve}
          disabled={actionsDisabled}
        >
          标记为已解决
        </Button>
        {hasMultipleActions && allAllowApprove && (
          <Button
            variant="outline"
            className="border-gray-500 bg-white font-normal text-gray-800"
            onClick={handleApproveAll}
            disabled={actionsDisabled}
          >
            全部批准
          </Button>
        )}
      </div>

      {hasMultipleActions && (
        <div className="flex w-full items-center gap-2">
          {actionRequests.map((_, index) => {
            const status = getDecisionStatus(addressedActions.get(index));
            return (
              <button
                type="button"
                key={index}
                onClick={() => setCurrentIndex(index)}
                className={cn(
                  "h-2 flex-1 rounded-full border transition-colors",
                  "border-gray-300 bg-gray-200",
                  status === "approve" && "border-emerald-500 bg-emerald-200",
                  status === "reject" && "border-red-500 bg-red-200",
                  status === "edit" && "border-amber-500 bg-amber-200",
                  index === currentIndex &&
                    "outline-primary outline-2 outline-offset-2",
                )}
              >
                <span className="sr-only">第 {index + 1} 项操作</span>
              </button>
            );
          })}
        </div>
      )}

      <InboxItemInput
        approveAllowed={approveAllowed}
        hasEdited={hasEdited}
        hasAddedResponse={hasAddedResponse}
        interruptValue={interruptValue}
        humanResponse={humanResponse}
        initialValues={initialHumanInterruptEditValue.current}
        setHumanResponse={setHumanResponse}
        supportsMultipleMethods={supportsMultipleMethods}
        setSelectedSubmitType={setSelectedSubmitType}
        setHasAddedResponse={setHasAddedResponse}
        setHasEdited={setHasEdited}
        handleSubmit={hasMultipleActions ? handleSaveDecision : handleSubmit}
        isLoading={hasMultipleActions ? submittingAll : loading}
        selectedSubmitType={selectedSubmitType}
      />

      {hasMultipleActions && (
        <div className="flex w-full items-center justify-between">
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={currentIndex === 0}
              onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
            >
              上一项
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={currentIndex === actionRequests.length - 1}
              onClick={() =>
                setCurrentIndex((prev) =>
                  Math.min(actionRequests.length - 1, prev + 1),
                )
              }
            >
              下一项
            </Button>
          </div>
          <Button
            variant="brand"
            disabled={!hasAllDecisions || submittingAll}
            onClick={handleSubmitAll}
          >
            {submittingAll
              ? "正在提交..."
              : `提交全部 ${actionRequests.length} 项决定`}
          </Button>
        </div>
      )}

      {!hasMultipleActions && streamFinished && (
        <p className="text-base font-medium text-green-600">
          图任务已成功执行完成。
        </p>
      )}
    </div>
  );
}
