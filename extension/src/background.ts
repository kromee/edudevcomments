export {};

const COMMENT_URL = "http://127.0.0.1:8788/comment";

const OLLAMA_ERROR = "No se pudo conectar con Ollama.\nVerifica que Ollama esté ejecutándose localmente.";
const GENERATION_ERROR = "No se pudo generar el comentario.\nIntenta nuevamente.";
const POST_ERROR = "No se pudo obtener el contenido de la publicación.";

type GenerateMessage = {
  type: "generateLinkedInComment";
  post: string;
  author?: string;
  previous?: string;
};

type CommentResponse = {
  comment: string;
  model: string;
};

type ErrorBody = {
  detail?: { code?: string } | string;
};

async function generateComment(message: GenerateMessage): Promise<CommentResponse> {
  let response: Response;
  try {
    response = await fetch(COMMENT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        post: message.post,
        author: message.author,
        previous: message.previous,
      }),
    });
  } catch {
    throw new Error(OLLAMA_ERROR);
  }

  const payload = (await response.json().catch(() => ({}))) as CommentResponse | ErrorBody;
  if (!response.ok) {
    const detail = "detail" in payload ? payload.detail : undefined;
    const code = detail && typeof detail === "object" && detail.code ? detail.code : "";
    if (response.status === 503 || code === "ollama_unavailable") {
      throw new Error(OLLAMA_ERROR);
    }
    throw new Error(GENERATION_ERROR);
  }
  if (!("comment" in payload) || typeof payload.comment !== "string" || !payload.comment.trim()) {
    throw new Error(GENERATION_ERROR);
  }
  return payload;
}

chrome.runtime.onMessage.addListener(
  (
    message: GenerateMessage,
    sender,
    sendResponse: (response: CommentResponse | { error: string }) => void,
  ) => {
    if (sender.id !== chrome.runtime.id || message?.type !== "generateLinkedInComment") {
      return undefined;
    }

    if (typeof message.post !== "string" || message.post.trim().length < 20 || message.post.length > 8000) {
      sendResponse({ error: POST_ERROR });
      return undefined;
    }
    if (message.author !== undefined && typeof message.author !== "string") {
      return undefined;
    }
    if (message.previous !== undefined && typeof message.previous !== "string") {
      return undefined;
    }

    void generateComment(message)
      .then(sendResponse)
      .catch((error: unknown) => {
        sendResponse({
          error: error instanceof Error && error.message ? error.message : GENERATION_ERROR,
        });
      });

    return true;
  },
);
