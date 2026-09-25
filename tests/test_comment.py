import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from fastapi import HTTPException, Request

import server


VALID_COMMENT = (
    "En un sistema que ya está en producción, el costo de un cambio se nota cuando una regla de "
    "negocio obliga a tocar varias capas a la vez. Separar esas reglas de la base de datos y del "
    "framework suele dar más margen para evolucionar que reorganizar carpetas. Conviene aplicar "
    "esa separación solo donde el sistema realmente cambia, y no en cada módulo por seguir un patrón."
)

POST = (
    "Clean Architecture aporta cuando separa responsabilidades sin agregar complejidad innecesaria "
    "en un sistema que ya está en producción."
)


def http_request(origin: str | None, content_type: str = "application/json") -> Request:
    headers = [(b"content-type", content_type.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "path": "/comment", "headers": headers})


class CommentTests(unittest.TestCase):
    def test_prompt_includes_profile_author_and_post(self) -> None:
        prompt = server.build_prompt(server.CommentRequest(post=POST, author="Ana Pérez"))
        self.assertIn("Senior .NET Developer", prompt)
        self.assertIn("AUTOR:\nAna Pérez", prompt)
        self.assertIn(POST, prompt)
        self.assertIn("Devuelve únicamente el comentario final", prompt)
        self.assertIn("/no_think", prompt)

    def test_regeneration_includes_previous_comment(self) -> None:
        prompt = server.build_prompt(
            server.CommentRequest(post=POST, previous="Un comentario anterior suficientemente largo.")
        )
        self.assertIn("Un comentario anterior suficientemente largo.", prompt)
        self.assertIn("matiz distinto", prompt)

    def test_rejects_unknown_fields_and_short_posts(self) -> None:
        with self.assertRaises(Exception):
            server.CommentRequest(post=POST, context="extra")
        with self.assertRaises(Exception):
            server.CommentRequest(post="muy corto")

    def test_strips_thinking_json_and_accepts_comment(self) -> None:
        raw = "<think>tema interno</think>\n" + json.dumps({"comentario": VALID_COMMENT})
        self.assertEqual(server.validate_comment(raw), VALID_COMMENT)

    def test_rejects_banned_opener_analysis_and_short_text(self) -> None:
        with self.assertRaises(server.InvalidComment):
            server.validate_comment("Totalmente de acuerdo. " + VALID_COMMENT)
        with self.assertRaises(server.InvalidComment):
            server.validate_comment("Análisis:\nTema: arquitectura\n" + VALID_COMMENT)
        with self.assertRaises(server.InvalidComment):
            server.validate_comment("La arquitectura importa mucho hoy.")
        with self.assertRaises(server.InvalidComment):
            server.validate_comment(VALID_COMMENT.replace("patrón.", "patrón y puedan grow."))
        with self.assertRaises(server.InvalidComment):
            server.validate_comment(
                "La publicación destaca la importancia de la arquitectura. " + VALID_COMMENT
            )

    def test_flattens_a_list_into_paragraphs(self) -> None:
        listed = (
            "- En proyectos empresariales, la arquitectura demuestra su valor cuando el sistema evoluciona.\n"
            "- Una separación clara de responsabilidades evita que un cambio termine afectando varias partes del código.\n\n"
            "Un enfoque pragmático suele funcionar mejor que aplicar un patrón solo porque está de moda en este momento."
        )
        comment = server.validate_comment(listed)
        self.assertNotIn("\n- ", f"\n{comment}")
        self.assertLessEqual(comment.count("\n\n") + 1, 2)

    def test_other_origin_is_rejected_before_model_call(self) -> None:
        with patch.object(server, "ask_ollama_text") as model:
            with self.assertRaises(HTTPException) as error:
                server.comment(server.CommentRequest(post=POST), http_request("https://www.linkedin.com"))
        self.assertEqual(error.exception.status_code, 403)
        model.assert_not_called()

    def test_non_technical_post_does_not_accept_a_software_comment(self) -> None:
        request = server.CommentRequest(
            post="Un buen equipo se nota cuando alguien se equivoca y el resto puede hablarlo con calma."
        )
        team_comment = (
            "Cuando un error se puede hablar con calma, el grupo aprende del caso y no de la culpa. "
            "En un equipo eso pesa más que acertar siempre, porque la siguiente decisión sale de lo que "
            "se entendió y no de quién quedó señalado delante de los demás."
        )
        self.assertIn("no es técnica", server.build_prompt(request))
        with patch.object(server, "ask_ollama_text", side_effect=[VALID_COMMENT, team_comment]) as model:
            result = server.comment(request, http_request(None))
        self.assertEqual(result.comment, team_comment)
        self.assertEqual(model.call_count, 2)

    def test_drops_sentences_copied_from_the_post(self) -> None:
        request = server.CommentRequest(
            post="Un buen equipo no se nota cuando todo sale bien y el resto puede hablar del error con calma y respeto."
        )
        copied = (
            "Un buen equipo no se nota cuando todo sale bien y el resto puede hablar del error con calma. "
            "Conviene separar el caso de la persona para que la siguiente decisión salga de lo que se entendió "
            "y no del temor a quedar señalado delante del grupo."
        )
        with patch.object(server, "ask_ollama_text", return_value=copied) as model:
            result = server.comment(request, http_request(None))
        self.assertTrue(result.comment.startswith("Conviene separar"))
        self.assertNotIn("no se nota cuando todo sale bien", result.comment)
        model.assert_called_once()

    def test_successful_comment_is_not_cached(self) -> None:
        request = server.CommentRequest(post=POST, author="Ana Pérez")
        with patch.object(server, "ask_ollama_text", return_value=VALID_COMMENT) as model:
            first = server.comment(request, http_request(server.EXTENSION_ORIGIN))
            second = server.comment(request, http_request(server.EXTENSION_ORIGIN))
        self.assertEqual(first.comment, VALID_COMMENT)
        self.assertEqual(second.comment, VALID_COMMENT)
        self.assertEqual(model.call_count, 2)

    def test_invalid_output_is_retried_once(self) -> None:
        request = server.CommentRequest(post=POST)
        with patch.object(
            server,
            "ask_ollama_text",
            side_effect=["Totalmente de acuerdo. Excelente publicación.", VALID_COMMENT],
        ) as model:
            result = server.comment(request, http_request(None))
        self.assertEqual(result.comment, VALID_COMMENT)
        self.assertEqual(model.call_count, 2)

    def test_second_invalid_output_becomes_generation_error(self) -> None:
        with patch.object(server, "ask_ollama_text", return_value="Totalmente de acuerdo."):
            with self.assertRaises(HTTPException) as error:
                server.comment(server.CommentRequest(post=POST), http_request(None))
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(error.exception.detail, {"code": "invalid_comment"})

    def test_ollama_connection_error_is_unavailable(self) -> None:
        with patch.object(server, "urlopen", side_effect=URLError("down")):
            with self.assertRaises(HTTPException) as error:
                server.ask_ollama_text("prompt", temperature=0.2)
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(error.exception.detail, {"code": "ollama_unavailable"})


if __name__ == "__main__":
    unittest.main()
