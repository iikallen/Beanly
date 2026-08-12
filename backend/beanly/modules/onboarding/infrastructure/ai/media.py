import asyncio
import base64
import http.client
import ipaddress
import multiprocessing
import socket
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlparse, urlunsplit

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader

from beanly.modules.onboarding.domain.exceptions import (
    AiExtractionUnavailable,
    ImportFileTooLarge,
    ImportFileTypeInvalid,
    ImportParseFailed,
)

MAX_AI_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_AI_PDF_PAGES = 20
MAX_AI_TEXT_CHARS = 120_000
MAX_AI_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_AI_IMAGE_PAYLOAD_CHARS = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 2048
MAX_PREPARE_SECONDS = 30
MAX_PREPARE_MEMORY_BYTES = 768 * 1024 * 1024

_IMAGE_TYPES = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}


@dataclass(frozen=True, slots=True)
class PreparedExtraction:
    text: str
    images: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DownloadedMenu:
    content: bytes
    media_type: str
    file_name: str


def prepare_file(content: bytes, media_type: str, file_name: str) -> PreparedExtraction:
    if not content:
        raise ImportParseFailed("AI import file is empty")
    if len(content) > MAX_AI_UPLOAD_BYTES:
        raise ImportFileTooLarge("AI import file exceeds 10 MB")
    media_type = media_type.partition(";")[0].strip().casefold()
    suffix = PurePosixPath(file_name.replace("\\", "/")).suffix.casefold()
    if media_type == "application/pdf":
        if suffix != ".pdf" or not content.startswith(b"%PDF-"):
            raise ImportFileTypeInvalid("PDF content, extension, and magic bytes do not match")
        return _prepare_pdf(content)
    if media_type in _IMAGE_TYPES:
        if suffix not in _IMAGE_TYPES[media_type]:
            raise ImportFileTypeInvalid("Image content type and extension do not match")
        return PreparedExtraction("", (_normalize_image(content, media_type),))
    if media_type in {"text/plain", "text/html"}:
        if media_type == "text/plain":
            text = _decode_text(content)
        else:
            parser = _VisibleTextParser()
            parser.feed(_decode_text(content))
            text = parser.text
        if not text.strip():
            raise ImportParseFailed("Public menu page contains no readable text")
        return PreparedExtraction(text[:MAX_AI_TEXT_CHARS], ())
    raise ImportFileTypeInvalid("AI import supports JPEG, PNG, WebP, and PDF")


def prepare_file_isolated(
    content: bytes, media_type: str, file_name: str
) -> PreparedExtraction:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_prepare_worker,
        args=(sender, content, media_type, file_name),
        daemon=True,
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(MAX_PREPARE_SECONDS):
            process.terminate()
            process.join(5)
            raise ImportParseFailed("AI import file processing timed out")
        try:
            outcome, value = receiver.recv()
        except EOFError as exc:
            raise ImportParseFailed("AI import file processing failed safely") from exc
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(5)
    if outcome == "ok":
        return value
    exception_type, message = value
    exceptions = {
        "ImportFileTooLarge": ImportFileTooLarge,
        "ImportFileTypeInvalid": ImportFileTypeInvalid,
        "ImportParseFailed": ImportParseFailed,
    }
    raise exceptions.get(exception_type, ImportParseFailed)(message)


class PublicMenuFetcher:
    def __init__(self, *, timeout_seconds: float = 15) -> None:
        self.timeout_seconds = timeout_seconds

    async def fetch(self, public_url: str) -> DownloadedMenu:
        parsed = urlparse(public_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ImportFileTypeInvalid("Public menu URL is invalid")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise ImportFileTypeInvalid("Public menu URL port is invalid") from exc
        if port != (443 if parsed.scheme == "https" else 80):
            raise ImportFileTypeInvalid("Public menu URL must use the standard HTTP(S) port")
        allowed_addresses = await _public_addresses(parsed.hostname, port)
        try:
            content, media_type = await asyncio.to_thread(
                _fetch_pinned,
                parsed,
                allowed_addresses,
                self.timeout_seconds,
            )
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise AiExtractionUnavailable("Public menu could not be downloaded") from exc
        file_name = PurePosixPath(parsed.path).name or _file_name_for_type(media_type)
        if not PurePosixPath(file_name).suffix:
            file_name += PurePosixPath(_file_name_for_type(media_type)).suffix
        return DownloadedMenu(content, media_type, file_name[:255])


def _fetch_pinned(parsed, addresses: frozenset[str], timeout: float) -> tuple[bytes, str]:
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    port = 443 if parsed.scheme == "https" else 80
    last_error: OSError | None = None
    for address in sorted(addresses):
        if parsed.scheme == "https":
            connection = _PinnedHttpsConnection(address, parsed.hostname, port, timeout)
        else:
            connection = http.client.HTTPConnection(address, port, timeout=timeout)
        try:
            connection.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", parsed.hostname)
            connection.putheader(
                "Accept", "image/*,application/pdf,text/html,text/plain"
            )
            connection.putheader("Connection", "close")
            connection.endheaders()
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ImportFileTypeInvalid("Public menu URL redirects are not allowed")
            if response.status < 200 or response.status >= 300:
                raise AiExtractionUnavailable("Public menu could not be downloaded")
            declared = response.getheader("content-length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise ImportFileTypeInvalid(
                        "Public menu returned an invalid content length"
                    ) from exc
                if declared_size < 0 or declared_size > MAX_AI_UPLOAD_BYTES:
                    raise ImportFileTooLarge("Public menu exceeds 10 MB")
            content = response.read(MAX_AI_UPLOAD_BYTES + 1)
            if len(content) > MAX_AI_UPLOAD_BYTES:
                raise ImportFileTooLarge("Public menu exceeds 10 MB")
            return content, response.getheader("content-type", "").partition(";")[0]
        except OSError as exc:
            last_error = exc
        finally:
            connection.close()
    raise last_error or OSError("No public address was reachable")


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(self, address: str, server_hostname: str, port: int, timeout: float) -> None:
        super().__init__(address, port, timeout=timeout, context=ssl.create_default_context())
        self._server_hostname = server_hostname

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.host, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(
            raw_socket, server_hostname=self._server_hostname
        )


def _prepare_pdf(content: bytes) -> PreparedExtraction:
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ImportFileTypeInvalid("Encrypted PDFs are not supported")
        if not 1 <= len(reader.pages) <= MAX_AI_PDF_PAGES:
            raise ImportFileTypeInvalid("PDF must contain 1-20 pages")
        extracted = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except ImportFileTypeInvalid:
        raise
    except Exception as exc:
        raise ImportParseFailed("PDF could not be parsed") from exc
    normalized = "\n".join(line.strip() for line in extracted.splitlines() if line.strip())
    if len(normalized) >= 80:
        return PreparedExtraction(normalized[:MAX_AI_TEXT_CHARS], ())
    document = None
    try:
        document = pdfium.PdfDocument(content)
        images: list[str] = []
        for page_index in range(len(document)):
            page = document[page_index]
            width, height = page.get_size()
            if width <= 0 or height <= 0 or width * height * 1.5 * 1.5 > MAX_IMAGE_PIXELS:
                page.close()
                raise ImportFileTypeInvalid("PDF page dimensions exceed the safety limit")
            bitmap = page.render(scale=1.5)
            image = bitmap.to_pil()
            images.append(_encode_image(image))
            if sum(map(len, images)) > MAX_AI_IMAGE_PAYLOAD_CHARS:
                image.close()
                bitmap.close()
                page.close()
                raise ImportFileTooLarge("Rendered PDF exceeds the AI image safety limit")
            image.close()
            bitmap.close()
            page.close()
    except (ImportFileTooLarge, ImportFileTypeInvalid):
        raise
    except Exception as exc:
        raise ImportParseFailed("Scanned PDF pages could not be rendered") from exc
    finally:
        if document is not None:
            document.close()
    return PreparedExtraction("", tuple(images))


def _normalize_image(content: bytes, media_type: str) -> str:
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(BytesIO(content)) as source:
            source.verify()
        with Image.open(BytesIO(content)) as source:
            actual = (source.format or "").upper()
            expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[
                media_type
            ]
            if actual != expected:
                raise ImportFileTypeInvalid("Image magic bytes do not match content type")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ImportFileTypeInvalid("Image dimensions exceed the safety limit")
            normalized = ImageOps.exif_transpose(source).convert("RGB")
            normalized.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            try:
                return _encode_image(normalized)
            finally:
                normalized.close()
    except ImportFileTypeInvalid:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ImportFileTypeInvalid("Image is invalid or too large") from exc


def _encode_image(image: Image.Image) -> str:
    normalized = image.convert("RGB")
    normalized.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buffer = BytesIO()
    normalized.save(buffer, format="JPEG", quality=90, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def _public_addresses(hostname: str, port: int | None) -> frozenset[str]:
    try:
        values = await asyncio.get_running_loop().getaddrinfo(
            hostname,
            port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise AiExtractionUnavailable("Public menu host could not be resolved") from exc
    addresses = frozenset(value[4][0] for value in values)
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ImportFileTypeInvalid("Public menu URL must resolve only to public addresses")
    return addresses


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ImportParseFailed("Public menu text must be UTF-8") from exc


def _file_name_for_type(media_type: str) -> str:
    return {
        "application/pdf": "menu.pdf",
        "image/jpeg": "menu.jpg",
        "image/png": "menu.png",
        "image/webp": "menu.webp",
        "text/html": "menu.html",
        "text/plain": "menu.txt",
    }.get(media_type, "menu.bin")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0 and data.strip():
            self._parts.append(" ".join(data.split()))

    @property
    def text(self) -> str:
        return "\n".join(self._parts)


def _prepare_worker(sender, content: bytes, media_type: str, file_name: str) -> None:
    try:
        try:
            import resource

            resource.setrlimit(
                resource.RLIMIT_AS,
                (MAX_PREPARE_MEMORY_BYTES, MAX_PREPARE_MEMORY_BYTES),
            )
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (MAX_PREPARE_SECONDS, MAX_PREPARE_SECONDS + 1),
            )
        except (ImportError, OSError, ValueError):
            pass
        sender.send(("ok", prepare_file(content, media_type, file_name)))
    except Exception as exc:
        sender.send(("error", (type(exc).__name__, str(exc))))
    finally:
        sender.close()
