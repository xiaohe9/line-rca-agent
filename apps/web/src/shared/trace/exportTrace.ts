/**
 * Export a run as Markdown.
 *
 * This exists because the point of the trace contract is that a decision can leave the app:
 * an engineer can paste the reasoning, the tool calls and their outputs into a ticket or a
 * shift handover. It is generated purely from accumulated events, so it works offline and
 * while a run is still streaming.
 */
import { summarise, type TraceEvent } from "./events";

export function traceToMarkdown(events: readonly TraceEvent[], goal: string): string {
  if (events.length === 0) {
    return "# 产线良率根因分析\n\n（本次运行没有产生事件）\n";
  }

  const runId = events[0]?.run_id ?? "unknown";
  const answer = events.find((event) => event.type === "answer");
  const failed = events.find((event) => event.type === "run.failed");

  const lines: string[] = [
    "# 产线良率根因分析报告",
    "",
    `- 问题：${goal || "（未记录）"}`,
    `- 运行 ID：\`${runId}\``,
    `- 事件数：${events.length}`,
    `- schema 版本：${events[0]?.schema_version ?? "?"}`,
    "",
  ];

  if (answer) {
    lines.push("## 结论", "", String(answer.payload["text"] ?? ""), "");
  }
  if (failed) {
    lines.push("## 中断原因", "", `- 阶段：${String(failed.payload["stage"] ?? "")}`, `- 错误：${String(failed.payload["error"] ?? "")}`, "");
  }

  lines.push("## 推理轨迹", "");
  for (const event of events) {
    const summary = summarise(event);
    lines.push(`### ${event.seq}. ${summary.title}`, "", `\`${event.type}\``, "");
    if (summary.detail) {
      lines.push("```text", summary.detail, "```", "");
    }
  }

  lines.push(
    "---",
    "",
    "> 由 line-rca-agent 自动生成。若运行使用了模拟数据，观测中会带有相应标注。",
    "",
  );
  return lines.join("\n");
}

export function downloadMarkdown(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
