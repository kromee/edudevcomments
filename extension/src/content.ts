const POST_ERROR = "No se pudo obtener el contenido de la publicación.";
const OLLAMA_ERROR = "No se pudo conectar con Ollama.\nVerifica que Ollama esté ejecutándose localmente.";
const GENERATION_ERROR = "No se pudo generar el comentario.\nIntenta nuevamente.";

const POST_SELECTOR = [
  '[data-view-name="feed-full-update"]',
  '[componentkey^="expanded"][componentkey$="FeedType_FEED_DETAIL"]',
  "div.feed-shared-update-v2",
  "article.feed-shared-update-v2",
  'div[data-id^="urn:li:activity"]',
  'div[data-urn^="urn:li:activity"]',
  'div[data-urn^="urn:li:share"]',
  'div[data-urn^="urn:li:ugcPost"]',
].join(",");

const TEXT_SELECTOR = [
  '[data-testid="expandable-text-box"]',
  '[data-view-name="feed-commentary"]',
  '[componentkey^="feed-commentary"]',
  ".update-components-text",
  ".feed-shared-update-v2__commentary",
  ".feed-shared-inline-show-more-text",
].join(",");

const AUTHOR_SELECTOR = [
  ".update-components-actor__name span[aria-hidden='true']",
  ".update-components-actor__title span[aria-hidden='true']",
  ".feed-shared-actor__name span[aria-hidden='true']",
  ".feed-shared-actor__name",
  ".update-components-actor__name",
].join(",");

const COMMENT_SELECTOR = [
  ".comments-comments-list",
  ".comments-comment-item",
  ".comments-comment-box",
  "[data-view-name='feed-comment']",
].join(",");

const STYLE_ID = "edudev-comment-style";

type CommentResult = { comment: string } | { error: string };

type Draft = {
  post: string;
  author?: string;
};

const signatures = new WeakMap<Element, string>();
const drafts = new WeakMap<HTMLElement, Draft>();
const generating = new WeakSet<Element>();
const pending = new Set<Element | Document>();
let scheduled = 0;

function cleanPostText(value: string): string {
  return value
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/(?:…|\.\.\.)?\s*(?:ver más|see more)\s*$/i, "")
    .trim();
}

function cleanAuthor(value: string): string | undefined {
  const line = value.replace(/\s+/g, " ").trim().split("•")[0]?.trim() ?? "";
  if (line.length < 2 || line.length > 80 || /^\d/.test(line)) {
    return undefined;
  }
  if (/^(promoted|promocionado|suggested|sugerencia)$/i.test(line)) {
    return undefined;
  }
  if (/seguidor|follower|connection|contacto/i.test(line)) {
    return undefined;
  }
  return line;
}

function isOutermost(post: Element): boolean {
  return post.parentElement?.closest(POST_SELECTOR) == null;
}

function outermostPost(node: Element): Element | null {
  let current: Element | null = node.matches(POST_SELECTOR) ? node : node.closest(POST_SELECTOR);
  let outermost: Element | null = null;
  while (current) {
    outermost = current;
    current = current.parentElement?.closest(POST_SELECTOR) ?? null;
  }
  return outermost;
}

function commentaryNodes(post: Element): Element[] {
  return Array.from(post.querySelectorAll(TEXT_SELECTOR)).filter((element) => {
    if (element.closest(".edudev-comment-root") || element.closest(COMMENT_SELECTOR)) {
      return false;
    }
    const parentMatch = element.parentElement?.closest(TEXT_SELECTOR);
    return !(parentMatch && post.contains(parentMatch));
  });
}

function elementText(element: Element): string {
  const clone = element.cloneNode(true);
  if (!(clone instanceof Element)) {
    return "";
  }
  clone.querySelectorAll("button, .edudev-comment-root, .visually-hidden").forEach((node) => node.remove());
  return cleanPostText(clone.textContent ?? "");
}

function extractPostText(post: Element): string {
  const parts = commentaryNodes(post).map(elementText).filter((part) => part.length > 0);
  if (parts.length === 0) {
    return "";
  }
  if (parts[0].length >= 40 || parts.length === 1) {
    return parts[0];
  }
  return [parts[0], parts[1]].filter((part) => part.length > 0).join("\n\n");
}

function extractAuthor(post: Element): string | undefined {
  const legacy = post.querySelector(AUTHOR_SELECTOR);
  if (legacy && !legacy.closest(COMMENT_SELECTOR)) {
    const name = cleanAuthor(legacy.textContent ?? "");
    if (name) {
      return name;
    }
  }

  const actor = post.querySelector('[data-view-name="feed-actor-image"]');
  const scope = actor?.parentElement;
  if (!scope) {
    return undefined;
  }
  for (const node of scope.querySelectorAll("p, span")) {
    if (node.children.length > 0 || node.closest(TEXT_SELECTOR) || node.closest(COMMENT_SELECTOR)) {
      continue;
    }
    const name = cleanAuthor(node.textContent ?? "");
    if (name) {
      return name;
    }
  }
  return undefined;
}

function isSeeMore(button: HTMLButtonElement): boolean {
  if (button.closest(`.edudev-comment-root, ${COMMENT_SELECTOR}`)) {
    return false;
  }
  const label = `${button.getAttribute("aria-label") ?? ""} ${button.innerText ?? ""}`.replace(/\s+/g, " ").trim().toLowerCase();
  if (label.length > 32 || /comentario|comment|respuesta/.test(label)) {
    return false;
  }
  if (label.includes("ver menos") || label.includes("see less")) {
    return false;
  }
  return label.includes("ver más") || label.includes("see more");
}

async function expandPost(post: Element): Promise<void> {
  const scopes = commentaryNodes(post).map((node) => node.parentElement ?? node);
  const buttons = new Set<HTMLButtonElement>();
  for (const scope of scopes) {
    for (const button of scope.querySelectorAll("button")) {
      if (button instanceof HTMLButtonElement && isSeeMore(button)) {
        buttons.add(button);
      }
    }
  }
  if (buttons.size === 0) {
    return;
  }
  for (const button of buttons) {
    button.click();
  }
  await new Promise((resolve) => window.setTimeout(resolve, 350));
}

function ensureStyle(): void {
  if (document.getElementById(STYLE_ID)) {
    return;
  }
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .edudev-comment-root {
      display: block;
      margin: 8px 16px 10px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .edudev-comment-root button {
      all: unset;
      box-sizing: border-box;
      cursor: pointer;
    }
    .edudev-comment-trigger,
    .edudev-comment-actions button {
      display: inline-flex;
      align-items: center;
      border: 1px solid #0a66c2;
      border-radius: 16px;
      background: #f3f8fc;
      color: #0a66c2;
      padding: 6px 12px;
      font: 600 13px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .edudev-comment-trigger:disabled,
    .edudev-comment-actions button:disabled {
      opacity: .6;
      cursor: default;
    }
    .edudev-comment-panel {
      margin-top: 8px;
      padding: 12px 14px;
      border: 1px solid rgba(0, 0, 0, .12);
      border-radius: 12px;
      background: #f8fafc;
      color: #1d2226;
      box-shadow: 0 1px 2px rgba(0, 0, 0, .04);
    }
    .edudev-comment-title {
      margin: 0 0 8px;
      font-size: 13px;
      font-weight: 650;
    }
    .edudev-comment-body {
      margin: 0;
      font-size: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
      user-select: text;
    }
    .edudev-comment-body[data-state="error"] {
      color: #8f3d22;
    }
    .edudev-comment-body[data-state="loading"] {
      color: #5e6870;
    }
    .edudev-comment-actions {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
    html.theme--dark .edudev-comment-panel,
    body.theme--dark .edudev-comment-panel,
    html[data-color-scheme="dark"] .edudev-comment-panel {
      background: #1d2226;
      color: #f3f6f8;
      border-color: rgba(255, 255, 255, .16);
    }
    html.theme--dark .edudev-comment-trigger,
    html.theme--dark .edudev-comment-actions button,
    body.theme--dark .edudev-comment-trigger,
    body.theme--dark .edudev-comment-actions button {
      background: #1b2733;
      color: #70b5f9;
      border-color: #70b5f9;
    }
  `;
  document.documentElement.appendChild(style);
}

function ownedRoot(post: Element): HTMLElement | null {
  for (const candidate of post.querySelectorAll(".edudev-comment-root")) {
    if (candidate instanceof HTMLElement && candidate.parentElement?.closest(POST_SELECTOR) === post) {
      return candidate;
    }
  }
  return null;
}

function requestComment(draft: Draft, previous?: string): Promise<CommentResult> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      {
        type: "generateLinkedInComment",
        post: draft.post,
        author: draft.author,
        previous,
      },
      (response: CommentResult | undefined) => {
        if (chrome.runtime.lastError || !response) {
          resolve({ error: OLLAMA_ERROR });
          return;
        }
        resolve(response);
      },
    );
  });
}

function showPanel(root: HTMLElement, message: string, mode: "loading" | "ready" | "error" | "retry"): void {
  const title = root.querySelector(".edudev-comment-title");
  const body = root.querySelector(".edudev-comment-body");
  const actions = root.querySelector(".edudev-comment-actions");
  const trigger = root.querySelector(".edudev-comment-trigger");
  const copy = root.querySelector(".edudev-comment-copy");
  const regenerate = root.querySelector(".edudev-comment-regenerate");
  if (!(title instanceof HTMLElement) || !(body instanceof HTMLElement) || !(actions instanceof HTMLElement)) {
    return;
  }
  if (trigger instanceof HTMLButtonElement) {
    trigger.hidden = mode !== "error";
    trigger.disabled = mode === "loading";
  }
  title.hidden = mode !== "ready";
  body.textContent = message;
  body.dataset.state = mode === "ready" ? "ready" : mode === "loading" ? "loading" : "error";
  if (mode === "ready") {
    body.dataset.ready = "1";
  } else {
    delete body.dataset.ready;
  }
  actions.hidden = mode !== "ready" && mode !== "retry";
  if (copy instanceof HTMLButtonElement) {
    copy.hidden = mode !== "ready";
  }
  if (regenerate instanceof HTMLButtonElement) {
    regenerate.hidden = mode !== "ready" && mode !== "retry";
  }
  const panel = root.querySelector(".edudev-comment-panel");
  if (panel instanceof HTMLElement) {
    panel.hidden = false;
  }
}

async function generate(post: Element, root: HTMLElement, previous?: string): Promise<void> {
  if (generating.has(post)) {
    return;
  }
  generating.add(post);
  showPanel(root, "Generando comentario…", "loading");
  try {
    await expandPost(post);
    const text = extractPostText(post);
    signatures.set(post, text.slice(0, 240) || "empty");
    const author = extractAuthor(post);
    if (text.trim().length < 20) {
      showPanel(root, POST_ERROR, "error");
      return;
    }
    const draft = { post: text, author };
    drafts.set(root, draft);
    const result = await requestComment(draft, previous);
    if (!root.isConnected) {
      return;
    }
    if ("error" in result) {
      showPanel(root, result.error || GENERATION_ERROR, "retry");
      return;
    }
    showPanel(root, result.comment, "ready");
  } finally {
    generating.delete(post);
  }
}

function createRoot(post: Element): HTMLElement {
  const root = document.createElement("div");
  root.className = "edudev-comment-root";

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "edudev-comment-trigger";
  trigger.textContent = "✨ Generar comentario";

  const panel = document.createElement("div");
  panel.className = "edudev-comment-panel";
  panel.hidden = true;

  const title = document.createElement("p");
  title.className = "edudev-comment-title";
  title.textContent = "Comentario generado";

  const body = document.createElement("p");
  body.className = "edudev-comment-body";
  body.setAttribute("aria-live", "polite");

  const actions = document.createElement("div");
  actions.className = "edudev-comment-actions";
  actions.hidden = true;

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "edudev-comment-copy";
  copy.textContent = "📋 Copiar";

  const regenerate = document.createElement("button");
  regenerate.type = "button";
  regenerate.className = "edudev-comment-regenerate";
  regenerate.textContent = "🔄 Regenerar";

  const stop = (event: Event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  for (const button of [trigger, copy, regenerate]) {
    button.addEventListener("mousedown", stop);
    button.addEventListener("click", stop);
  }

  trigger.addEventListener("click", () => {
    void generate(post, root);
  });
  copy.addEventListener("click", () => {
    const comment = body.dataset.ready === "1" ? body.textContent ?? "" : "";
    if (!comment) {
      return;
    }
    void copyComment(comment).then((copied) => {
      copy.textContent = copied ? "Copiado" : "No se pudo copiar";
      window.setTimeout(() => {
        copy.textContent = "📋 Copiar";
      }, 1600);
    });
  });
  regenerate.addEventListener("click", () => {
    const draft = drafts.get(root);
    const previous = body.dataset.ready === "1" ? body.textContent ?? undefined : undefined;
    if (!draft) {
      void generate(post, root, previous);
      return;
    }
    void regenerateComment(post, root, draft, previous);
  });

  actions.append(copy, regenerate);
  panel.append(title, body, actions);
  root.append(trigger, panel);
  return root;
}

async function regenerateComment(
  post: Element,
  root: HTMLElement,
  draft: Draft,
  previous?: string,
): Promise<void> {
  if (generating.has(post)) {
    return;
  }
  generating.add(post);
  showPanel(root, "Generando comentario…", "loading");
  try {
    const result = await requestComment(draft, previous);
    if (!root.isConnected) {
      return;
    }
    if ("error" in result) {
      showPanel(root, result.error || GENERATION_ERROR, "retry");
      return;
    }
    showPanel(root, result.comment, "ready");
  } finally {
    generating.delete(post);
  }
}

async function copyComment(comment: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(comment);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = comment;
    area.setAttribute("readonly", "true");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
  }
}

function insertionAnchor(post: Element): { parent: Element; before: ChildNode | null } {
  const action = Array.from(
    post.querySelectorAll(".feed-shared-social-action-bar, [data-view-name='feed-social-action-bar']"),
  ).find((element) => !element.closest(COMMENT_SELECTOR));
  if (action?.parentElement && post.contains(action)) {
    return { parent: action.parentElement, before: action };
  }

  const commentary = commentaryNodes(post)[0];
  if (commentary) {
    let node: Element = commentary;
    while (node.parentElement && node.parentElement !== post && post.contains(node.parentElement)) {
      node = node.parentElement;
    }
    if (node.parentElement) {
      return { parent: node.parentElement, before: node.nextSibling };
    }
  }
  return { parent: post, before: null };
}

function sync(post: Element): void {
  if (!isOutermost(post) || generating.has(post)) {
    return;
  }
  const signature = extractPostText(post).slice(0, 240) || "empty";
  const existing = ownedRoot(post);
  if (existing && signatures.get(post) === signature) {
    return;
  }
  existing?.remove();
  ensureStyle();
  const root = createRoot(post);
  const anchor = insertionAnchor(post);
  anchor.parent.insertBefore(root, anchor.before);
  signatures.set(post, signature);
}

function scan(target: ParentNode): void {
  if (target instanceof Element) {
    const post = outermostPost(target);
    if (post) {
      sync(post);
      return;
    }
  }
  const scope = target instanceof Element || target instanceof Document ? target : document;
  for (const post of scope.querySelectorAll(POST_SELECTOR)) {
    if (isOutermost(post)) {
      sync(post);
    }
  }
}

function queue(target: Element | Document): void {
  pending.add(target);
  if (scheduled) {
    return;
  }
  scheduled = window.setTimeout(() => {
    scheduled = 0;
    const batch = [...pending];
    pending.clear();
    for (const node of batch) {
      scan(node);
    }
  }, 200);
}

function start(): void {
  queue(document);
  window.setTimeout(() => queue(document), 1200);
  window.setTimeout(() => queue(document), 3000);
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (!(node instanceof Element) || node.closest(".edudev-comment-root")) {
          continue;
        }
        queue(node);
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
}

start();
