from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:1.7b"
EXTENSION_ORIGIN = os.environ.get(
    "EXTENSION_ORIGIN",
    "chrome-extension://jlinanjklmiikeepamkodmhmhnnngnlh",
)

PROMPT_PREFIX = """Actúa como un desarrollador Senior .NET con experiencia en desarrollo de software empresarial.

Analiza la publicación de LinkedIn que recibirás y genera un comentario profesional que aporte valor a la conversación.

PERFIL DEL COMENTARISTA:

* Senior .NET Developer.
* Experiencia en C# y ecosistema .NET.
* .NET / .NET Core / .NET 8.
* ASP.NET Core.
* APIs REST / Web API.
* Entity Framework.
* SQL Server.
* Azure.
* Blazor.
* Desarrollo backend y frontend.
* Desarrollo de aplicaciones empresariales.
* Experiencia trabajando con sistemas existentes, mantenimiento, evolución y migración de módulos.
* Experiencia e interés en arquitectura de software.
* Clean Architecture.
* Diseño modular.
* Buenas prácticas de desarrollo.
* Enfoque pragmático para resolver problemas de software.

ENFOQUE PROFESIONAL:

Prioriza soluciones mantenibles y adecuadas al contexto.

No asumas que un patrón, framework o arquitectura es siempre la solución correcta.

Cuando la publicación trate sobre arquitectura, considera aspectos como mantenibilidad, evolución del sistema, separación de responsabilidades, dependencias y complejidad.

OBJETIVO:

Analiza primero la publicación.

Identifica internamente:

* el tema principal;
* la idea central;
* los conceptos técnicos relevantes;
* qué aspecto puede complementarse;
* qué perspectiva puede aportar un Senior .NET Developer;
* qué tipo de comentario sería natural en este contexto.

Después genera UN SOLO comentario profesional para LinkedIn.

REGLAS:

* Escribe en español.
* Debe sonar natural y humano.
* Debe parecer escrito por un desarrollador experimentado.
* Aporta una idea propia, experiencia práctica o matiz técnico.
* No repitas simplemente la publicación.
* No hagas un resumen de la publicación.
* No inventes experiencias, proyectos, tecnologías, empresas o resultados.
* No fuerces referencias a .NET cuando no sean relevantes.
* Si la publicación es técnica, aporta una observación técnica cuando corresponda.
* Si habla de arquitectura, puedes relacionarla con mantenibilidad, evolución de sistemas o decisiones pragmáticas.
* Si habla de .NET, puedes aportar contexto desde la experiencia en el ecosistema .NET.
* Si el tema no es técnico, responde desde una perspectiva profesional relacionada con el tema.
* Evita frases genéricas.
* No comiences automáticamente con "Totalmente de acuerdo".
* No utilices "Excelente publicación", "Excelente aporte", "Muy interesante", "Gran publicación", "Sin duda" o "Gracias por compartir" como relleno.
* No utilices lenguaje de marketing.
* No exageres.
* No utilices emojis salvo que sean realmente necesarios.
* No utilices hashtags.
* No hagas parecer que conoces personalmente al autor.
* No hagas afirmaciones que no puedan deducirse del contexto disponible.
* No conviertas el comentario en una clase o artículo.
* No utilices listas.
* No termines siempre con una pregunta.
* Utiliza aproximadamente entre 50 y 90 palabras.
* Utiliza uno o dos párrafos cortos.
* Prioriza profundidad y relevancia sobre longitud.

EJEMPLO DE LO QUE NO DEBES HACER:
Excelente publicación. Totalmente de acuerdo. La arquitectura es muy importante para desarrollar software de calidad.

EJEMPLO DEL TIPO DE COMENTARIO ESPERADO:
En proyectos empresariales, la arquitectura empieza a demostrar su valor cuando el sistema necesita evolucionar sin que cada cambio termine afectando múltiples partes. Ahí es donde una separación clara de responsabilidades puede marcar una diferencia real, más allá de cómo se distribuyan físicamente las carpetas o proyectos.

Si la publicación no trata de software, arquitectura o tecnología, no menciones código, arquitectura, frameworks ni .NET. Comenta ese tema desde una perspectiva profesional.

EJEMPLO CUANDO EL TEMA NO ES TÉCNICO:
Cuando un error se puede conversar sin convertirlo en culpa, el equipo aprende del caso. En un grupo de trabajo eso pesa más que tener siempre la respuesta correcta, porque la siguiente decisión sale de lo que se entendió y no de quién quedó señalado.

No copies estos ejemplos. Úsalos solo como referencia de tono: empieza por la observación, sin resumir la publicación y sin un halago inicial. No reformules con otras palabras lo que el texto ya dijo.

IMPORTANTE:

Analiza internamente la publicación antes de generar el comentario, pero NO muestres el análisis, razonamiento, categorías ni instrucciones.

Devuelve únicamente el comentario final listo para publicar.

/no_think
"""

RETRY_NOTE = (
    "\nLa respuesta anterior no era válida. Devuelve solo el comentario final en español, "
    "listo para publicar. Empieza por tu observación. No resumas la publicación, "
    "no uses «la publicación», «como desarrollador» ni «me gustaría aportar», "
    "no copies frases de la publicación y no incluyas análisis, títulos, JSON ni listas.\n"
)

AI_TELL = re.compile(
    r"la publicaci[oó]n destaca|la publicaci[oó]n (?:menciona|habla|explica|subraya)|"
    r"como desarrollador|me gustar[ií]a aportar|es importante destacar|cabe mencionar|"
    r"en el mundo actual|en la era digital|sin lugar a dudas|como profesionales",
    re.IGNORECASE,
)
BANNED_OPENER = re.compile(
    r"^(?:totalmente de acuerdo|excelente publicaci[oó]n|excelente aporte|muy interesante|"
    r"gran publicaci[oó]n|sin duda|as[ií] es|exactamente|gracias por compartir)\b",
    re.IGNORECASE,
)
SPANISH_MARKERS = (" que ", " de ", " en ", " la ", " el ", " los ", " una ", " para ", " con ", " por ")
ENGLISH_LEAKS = frozenset({
    "grow",
    "the",
    "and",
    "with",
    "this",
    "that",
    "should",
    "would",
    "could",
    "because",
    "however",
    "really",
    "make",
    "makes",
    "about",
    "their",
    "there",
    "these",
    "those",
})
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
THINK_RE = re.compile(r"(?is)<think>.*?</think>")

app = FastAPI(title="EduDev Comments", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXTENSION_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class CommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str = Field(min_length=20, max_length=8000)
    author: str | None = Field(default=None, max_length=120)
    previous: str | None = Field(default=None, max_length=1200)

    @field_validator("author", "previous", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class CommentResponse(BaseModel):
    comment: str
    model: str


class InvalidComment(Exception):
    pass


def normalize_post(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.replace("\r\n", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def normalize_author(value: str | None) -> str | None:
    if not value:
        return None
    line = re.sub(r"\s+", " ", value).split("•")[0].strip()
    line = re.sub(r"[\x00-\x1f]", "", line)
    if len(line) < 2:
        return None
    return line[:120]


SOFTWARE_TERMS = (
    "arquitectura",
    "architecture",
    "software",
    "código",
    "codigo",
    ".net",
    "dotnet",
    "c#",
    " api",
    "sql",
    "azure",
    "framework",
    "backend",
    "frontend",
    "base de datos",
    "database",
    "microservicio",
    "microservice",
)


def post_mentions_software(post: str) -> bool:
    folded = f" {post.lower()} "
    return any(term in folded for term in SOFTWARE_TERMS)


def comment_forces_software(comment: str) -> bool:
    folded = comment.lower()
    return any(term in folded for term in ("arquitectura", "código", "codigo", ".net", "framework"))


def sentence_copies_post(sentence: str, post_folded: str) -> bool:
    folded = " ".join(re.sub(r"[^\w\s]", "", sentence.lower()).split())
    return len(folded) >= 20 and folded in post_folded


def without_copied_sentences(post: str, comment: str) -> str:
    post_folded = " ".join(post.lower().split())
    sentences = re.split(r"(?<=[.!?])\s+", comment.strip())
    kept: list[str] = []
    skipping = True
    for sentence in sentences:
        if skipping and sentence_copies_post(sentence, post_folded):
            continue
        skipping = False
        if sentence.strip():
            kept.append(sentence.strip())
    return " ".join(kept)


def repeats_post(post: str, comment: str) -> bool:
    post_folded = " ".join(post.lower().split())
    comment_folded = " ".join(comment.lower().split())
    words = comment_folded.split()
    if len(words) >= 8 and " ".join(words[:8]) in post_folded:
        return True
    window = 50
    if len(post_folded) <= window:
        return len(post_folded) >= 30 and post_folded in comment_folded
    return any(
        post_folded[index:index + window] in comment_folded
        for index in range(0, len(post_folded) - window + 1, 12)
    )


def build_prompt(request: CommentRequest) -> str:
    parts = [PROMPT_PREFIX]
    if not post_mentions_software(request.post):
        parts.append(
            "Esta publicación no es técnica. Habla solo de ese tema. "
            "No menciones software, arquitectura, código, frameworks ni .NET.\n"
        )
    if request.previous:
        parts.append(
            "El usuario pidió otro comentario. No repitas el siguiente texto y aporta un matiz distinto:\n"
            f"{normalize_post(request.previous)}\n"
        )
    author = normalize_author(request.author)
    if author:
        parts.append(f"AUTOR:\n{author}\n")
    parts.append("PUBLICACIÓN DE LINKEDIN:\n\n")
    parts.append(normalize_post(request.post))
    parts.append("\n")
    return "".join(parts)


def strip_thinking(text: str) -> str:
    value = THINK_RE.sub("", text).strip()
    if "<think>" in value.lower() or "</think>" in value.lower():
        return ""
    return value


def looks_spanish(text: str) -> bool:
    sample = f" {text.lower()} "
    return sum(marker in sample for marker in SPANISH_MARKERS) >= 3


def validate_comment(raw: str) -> str:
    text = strip_thinking(raw).strip()
    text = re.sub(r"^```(?:json|text|markdown)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    if text.startswith("{") and text.endswith("}"):
        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError as error:
            raise InvalidComment from error
        if not isinstance(payload, dict):
            raise InvalidComment
        extracted = next(
            (
                payload[key].strip()
                for key in ("comentario", "comment", "respuesta")
                if isinstance(payload.get(key), str) and payload[key].strip()
            ),
            None,
        )
        if extracted is None:
            raise InvalidComment
        text = extracted

    text = re.sub(r"(?i)^comentario\s*:\s*", "", text).strip()
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\*+", "", text)
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("«") and text.endswith("»")):
        text = text[1:-1].strip()

    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        cleaned = EMOJI_RE.sub("", line)
        cleaned = re.sub(r"#\w+", "", cleaned)
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", cleaned).strip()
        if not cleaned:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(cleaned)
    if current:
        paragraphs.append(" ".join(current))
    paragraphs = [re.sub(r"\s{2,}", " ", paragraph).strip() for paragraph in paragraphs if paragraph.strip()]
    if not paragraphs:
        raise InvalidComment
    if len(paragraphs) > 2:
        paragraphs = [paragraphs[0], " ".join(paragraphs[1:])]
    text = "\n\n".join(paragraphs).strip()

    if re.match(r"(?i)^(an[aá]lisis|tema|idea principal|idea|nivel|respuesta)\s*:", text):
        raise InvalidComment
    if BANNED_OPENER.match(text) or AI_TELL.search(text):
        raise InvalidComment
    folded = text.lower()
    if "distribuyan físicamente las carpetas" in folded or "empieza a demostrar su valor" in folded:
        raise InvalidComment
    if "sin convertirlo en culpa" in folded:
        raise InvalidComment
    words = text.split()
    if len(words) < 20 or len(words) > 180 or len(text) > 1200:
        raise InvalidComment
    if not looks_spanish(text):
        raise InvalidComment
    tokens = {re.sub(r"[^\w]", "", word.lower()) for word in text.split()}
    if tokens & ENGLISH_LEAKS:
        raise InvalidComment
    return text


def ask_ollama_text(prompt: str, *, temperature: float) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "keep_alive": "15m",
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_ctx": 8192,
                "num_predict": 512,
            },
        }
    ).encode("utf-8")
    request = Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as error:
        raise HTTPException(status_code=503, detail={"code": "ollama_unavailable"}) from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=502, detail={"code": "invalid_comment"}) from error

    message = payload.get("message") if isinstance(payload, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        fallback = payload.get("response") if isinstance(payload, dict) else None
        content = fallback if isinstance(fallback, str) else ""
    if not content.strip():
        raise InvalidComment
    return content


def produce_comment(request: CommentRequest) -> str:
    prompt = build_prompt(request)
    temperature = 0.7 if request.previous else 0.4
    for attempt in range(2):
        raw = ask_ollama_text(
            prompt if attempt == 0 else f"{prompt}{RETRY_NOTE}",
            temperature=temperature if attempt == 0 else min(temperature + 0.15, 0.9),
        )
        try:
            comment = without_copied_sentences(request.post, validate_comment(raw))
            comment = validate_comment(comment)
            if not post_mentions_software(request.post) and comment_forces_software(comment):
                raise InvalidComment
            if repeats_post(request.post, comment):
                raise InvalidComment
            return comment
        except InvalidComment:
            if attempt == 1:
                raise
    raise InvalidComment


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL}


@app.post("/comment", response_model=CommentResponse)
def comment(request: CommentRequest, http_request: FastAPIRequest) -> CommentResponse:
    origin = http_request.headers.get("origin")
    if origin is not None and origin != EXTENSION_ORIGIN:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    content_type = http_request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail={"code": "unsupported_media"})

    try:
        generated = produce_comment(request)
    except InvalidComment as error:
        raise HTTPException(status_code=502, detail={"code": "invalid_comment"}) from error
    return CommentResponse(comment=generated, model=MODEL)
