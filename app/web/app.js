const form = document.querySelector("#researchForm");
const queryInput = document.querySelector("#query");
const submitButton = document.querySelector("#submitButton");
const downloadButton = document.querySelector("#downloadButton");
const statusBadge = document.querySelector("#statusBadge");
const stageText = document.querySelector("#stageText");
const taskId = document.querySelector("#taskId");
const progressBar = document.querySelector("#progressBar");
const stepCounter = document.querySelector("#stepCounter");
const timeline = document.querySelector("#timeline");
const plan = document.querySelector("#plan");
const searchResults = document.querySelector("#searchResults");
const report = document.querySelector("#report");
const sources = document.querySelector("#sources");

const stageLabels = {
  planning: "正在规划",
  plan_completed: "计划完成",
  researching: "正在研究",
  search_completed: "搜索完成",
  reading_webpage: "读取网页",
  reviewing: "正在审核",
  retrying: "补充研究",
  writing: "正在写作",
  completed: "研究完成",
  error: "执行失败",
};

let latestReport = "";

function resetView() {
  latestReport = "";
  timeline.replaceChildren();
  plan.replaceChildren();
  searchResults.replaceChildren();
  sources.replaceChildren();
  report.textContent = "报告将在研究完成后显示";
  report.classList.add("empty");
  progressBar.style.width = "2%";
  taskId.textContent = "";
  stepCounter.textContent = "0 / 0";
  downloadButton.disabled = true;
  statusBadge.className = "status-badge running";
  statusBadge.textContent = "执行中";
}

function safeLink(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function appendTimeline(event) {
  const item = document.createElement("li");
  item.className = event.event;
  const title = document.createElement("strong");
  title.textContent = stageLabels[event.event] || event.stage;
  const message = document.createElement("span");
  message.textContent = event.message;
  item.append(title, message);
  timeline.append(item);
  item.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderPlan(items) {
  plan.replaceChildren();
  plan.classList.remove("empty");
  for (const value of items || []) {
    const item = document.createElement("li");
    item.textContent = String(value);
    plan.append(item);
  }
}

function appendSearchResults(results) {
  searchResults.classList.remove("empty");
  for (const result of results || []) {
    const item = document.createElement("article");
    item.className = "search-item";
    const url = safeLink(result.url);
    const title = document.createElement(url ? "a" : "strong");
    title.textContent = result.title || result.url || "无标题";
    if (url) {
      title.href = url;
      title.target = "_blank";
      title.rel = "noopener noreferrer";
    }
    item.append(title);
    if (result.snippet) {
      const summary = document.createElement("p");
      summary.textContent = result.snippet;
      item.append(summary);
    }
    searchResults.append(item);
  }
}

function renderSources(items) {
  sources.replaceChildren();
  sources.classList.remove("empty");
  for (const source of items || []) {
    const item = document.createElement("li");
    const url = safeLink(source.url);
    const label = document.createElement(url ? "a" : "span");
    label.textContent = `${source.id || "来源"} · ${source.title}`;
    if (url) {
      label.href = url;
      label.target = "_blank";
      label.rel = "noopener noreferrer";
    }
    const meta = document.createElement("span");
    meta.className = "source-meta";
    meta.textContent = source.acquisition === "search_snippet" ? "搜索摘要" : "网页正文";
    item.append(label, meta);
    sources.append(item);
  }
}

function renderMarkdown(markdown) {
  report.replaceChildren();
  let activeList = null;
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      activeList = null;
      continue;
    }
    let element;
    if (line.startsWith("# ")) {
      element = document.createElement("h1");
      element.textContent = line.slice(2);
      activeList = null;
    } else if (line.startsWith("## ")) {
      element = document.createElement("h2");
      element.textContent = line.slice(3);
      activeList = null;
    } else if (line.startsWith("- ")) {
      if (!activeList) {
        activeList = document.createElement("ul");
        report.append(activeList);
      }
      element = document.createElement("li");
      element.textContent = line.slice(2);
      activeList.append(element);
      continue;
    } else {
      element = document.createElement("p");
      element.textContent = line;
      activeList = null;
    }
    report.append(element);
  }
}

function handleEvent(event) {
  appendTimeline(event);
  stageText.textContent = event.message;
  taskId.textContent = event.task_id ? `task_id: ${event.task_id}` : "";
  const total = Number(event.total_steps || 0);
  const current = Number(event.current_step || 0);
  stepCounter.textContent = `${current} / ${total}`;
  if (total > 0) {
    const base = event.event === "completed" ? 100 : Math.max(8, (current / total) * 82);
    progressBar.style.width = `${Math.min(base, 100)}%`;
  }
  if (event.event === "plan_completed") renderPlan(event.data?.plan);
  if (event.event === "search_completed") appendSearchResults(event.data?.results);
  if (event.event === "completed") {
    latestReport = event.report || "";
    renderMarkdown(latestReport);
    report.classList.remove("empty");
    renderSources(event.sources);
    progressBar.style.width = "100%";
    statusBadge.className = "status-badge done";
    statusBadge.textContent = "已完成";
    downloadButton.disabled = !latestReport;
  }
  if (event.event === "error") {
    statusBadge.className = "status-badge error";
    statusBadge.textContent = "失败";
  }
}

function parseEventBlock(block) {
  const lines = block.split(/\r?\n/);
  const dataLines = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart());
  if (!dataLines.length) return;
  handleEvent(JSON.parse(dataLines.join("\n")));
}

async function runResearch(query) {
  const response = await fetch("/research/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ query }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`请求失败：HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      if (block.trim()) parseEventBlock(block);
    }
    if (done) break;
  }
  if (buffer.trim()) parseEventBlock(buffer);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetView();
  submitButton.disabled = true;
  try {
    await runResearch(queryInput.value.trim());
  } catch (error) {
    handleEvent({
      event: "error",
      stage: "error",
      message: error instanceof Error ? error.message : "研究请求失败",
      task_id: "",
      current_step: 0,
      total_steps: 0,
    });
  } finally {
    submitButton.disabled = false;
  }
});

downloadButton.addEventListener("click", () => {
  if (!latestReport) return;
  const blob = new Blob([latestReport], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "research-report.md";
  anchor.click();
  URL.revokeObjectURL(url);
});
