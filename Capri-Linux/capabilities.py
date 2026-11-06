import configparser
import json
import html
import ipaddress
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from http.client import HTTPException
from itertools import chain
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


MAX_TEXT_FILE_BYTES = 1_000_000
MAX_WRITE_BYTES = 200_000
MAX_FOLDER_SEARCH_FILES = 10_000
MAX_FOLDER_SEARCH_RESULTS = 50
MAX_START_MENU_SHORTCUTS = 5_000

ACTION_REQUEST_PATTERNS = (
    r"^\s*(?:por favor[:,]?\s+)?(?:abrir|acessar|iniciar|criar|salvar|"
    r"gravar|escrever|ler|listar|mostrar|pesquisar|buscar|procurar)\b",
    r"\b(?:abra|abre|abram|acesse|acessem|inicie|inicia)\b",
    r"\b(?:pode|poderia|quero|gostaria|preciso|consegue)\s+"
    r"(?:me\s+)?(?:abrir|acessar|iniciar)\b",
    r"\b(?:crie|cria|salve|salva|grave|grava|escreva|escreve|"
    r"leia|liste|lista|mostre|mostra)\b",
    r"\b(?:pode|poderia|quero|gostaria|preciso|consegue)\s+"
    r"(?:me\s+)?(?:criar|salvar|gravar|escrever|ler|listar|mostrar)\b",
    r"\b(?:pesquise|busque|procure)\b",
    r"\b(?:encontre|encontrar|localize|localizar|ache|achar)\b",
    r"\b(?:pode|poderia|quero|gostaria|preciso|consegue)\s+"
    r"(?:pesquisar|buscar|procurar)\b",
    r"\b(?:me\s+lembre|me\s+avise|me\s+alerte)\b",
    r"\b(?:crie|cria)\b.{0,30}\b(?:lembrete|alarme)\b",
    r"\b(?:consulte|consulta|verifique|verifica)\b",
    r"\b(?:qual|como|quanto|me\s+diga|verifique|consulte)\b.{0,32}"
    r"\b(?:bateria|processos|armazenamento|espa[cç]o\s+livre|"
    r"status\s+(?:do\s+)?(?:pc|computador|sistema))\b",
    r"\b(?:status|bateria|processos|armazenamento)\b.{0,32}\b(?:pc|computador|sistema|disco)\b",
    r"\b(?:pc|computador|sistema|disco)\b.{0,32}\b(?:status|bateria|processos|armazenamento|espa[cç]o)\b",
    r"\b(?:espa[cç]o\s+livre|quanto\s+tem\s+livre)\b",
    r"\b(?:informac(?:ao|oes)|dados|configurac(?:ao|oes)|"
    r"especificac(?:ao|oes)|hardware)\b.{0,50}\b"
    r"(?:meu\s+)?(?:pc|computador|sistema)\b",
    r"\b(?:meu\s+)?(?:pc|computador|sistema)\b.{0,50}\b"
    r"(?:informac(?:ao|oes)|dados|configurac(?:ao|oes)|"
    r"especificac(?:ao|oes)|hardware)\b",
    r"\b(?:qual|quais|quanto|como|me\s+diga|voce\s+sabe|sabe)\b.{0,40}\b"
    r"(?:processador|cpu|ram|memoria|sistema\s+operacional|"
    r"versao\s+do\s+windows|windows)\b",
    r"\b(?:processador|cpu|ram|memoria|sistema\s+operacional|"
    r"versao\s+do\s+windows|windows)\b.{0,40}\b"
    r"(?:pc|computador|meu|minha)\b",
)


def should_offer_tools(message: str) -> bool:
    normalized = unicodedata.normalize("NFKD", message.casefold())
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return any(
        re.search(pattern, normalized)
        for pattern in ACTION_REQUEST_PATTERNS
    )

CAPRI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": (
                "Abrir pelo nome um aplicativo instalado (atalho no Menu "
                "Iniciar do Windows ou entrada .desktop no Linux). A pessoa "
                "confirma a abertura."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "application": {"type": "string"},
                },
                "required": ["application"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Abrir um site HTTPS no navegador padrão.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_local_file",
            "description": "Selecionar e ler um arquivo de texto escolhido pelo usuário.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_local_folder",
            "description": "Selecionar uma pasta e listar seus itens imediatos.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_files",
            "description": (
                "Pesquisar nomes de arquivos e subpastas dentro de uma pasta "
                "escolhida pela pessoa. Não lê conteúdo dos arquivos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_local_file",
            "description": "Criar ou substituir um arquivo de texto escolhido pelo usuário.",
            "parameters": {
                "type": "object",
                "properties": {
                    "suggested_filename": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["suggested_filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Consultar sistema, processos, bateria e espaço em disco.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": (
                "Criar um lembrete local. A data deve ser ISO 8601; "
                "o CAPRI precisa estar aberto para avisar no horário."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "due_at": {"type": "string", "format": "date-time"},
                },
                "required": ["text", "due_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Pesquisar na web enviando a consulta para o DuckDuckGo "
                "e retornar títulos e trechos de resultados."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
]


def find_application_shortcut(application: str) -> Path:
    requested = _normalize_application_name(application)
    if not requested:
        raise ValueError("Informe o nome do aplicativo que deseja abrir.")

    known_aliases = {
        "steam": ("steam",),
        "opera": ("opera",),
        "minecraft": ("minecraft launcher", "minecraft"),
        "gog": ("gog galaxy", "gog"),
        "gog galaxy": ("gog galaxy", "gog"),
    }
    aliases = known_aliases.get(requested, (requested,))
    if sys.platform.startswith("linux"):
        return _find_linux_application_desktop(application, aliases)

    start_menu_paths = (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs",
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs",
    )

    matches: list[tuple[int, Path]] = []
    scan_errors: list[OSError] = []
    scanned = 0

    def record_error(error: OSError) -> None:
        scan_errors.append(error)

    for root in start_menu_paths:
        if not root.is_dir():
            continue
        for current, directories, filenames in os.walk(
            root, followlinks=False, onerror=record_error
        ):
            directories[:] = [
                name
                for name in directories
                if not (Path(current) / name).is_symlink()
            ]
            for filename in filenames:
                if Path(filename).suffix.casefold() != ".lnk":
                    continue
                scanned += 1
                if scanned > MAX_START_MENU_SHORTCUTS:
                    break
                shortcut_name = _normalize_application_name(
                    Path(filename).stem
                )
                score = _application_name_score(shortcut_name, aliases)
                if score is not None:
                    matches.append(
                        (score, Path(current) / filename)
                    )
            if scanned > MAX_START_MENU_SHORTCUTS:
                break
        if scanned > MAX_START_MENU_SHORTCUTS:
            break

    if not matches:
        if scan_errors:
            raise OSError(
                f"Não foi possível pesquisar o Menu Iniciar: {scan_errors[0]}"
            )
        raise FileNotFoundError(
            f"Não encontrei “{application}” nos atalhos do Menu Iniciar. "
            "Adicione um atalho do aplicativo ao Menu Iniciar do Windows."
        )

    matches.sort(key=lambda result: (result[0], str(result[1]).casefold()))
    shortcut = matches[0][1]
    if not shortcut.is_file():
        raise FileNotFoundError(
            f"O atalho do aplicativo não está mais disponível: {shortcut}"
        )
    return shortcut


def _find_linux_application_desktop(
    application: str, aliases: tuple[str, ...]
) -> Path:
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    )
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    roots = dict.fromkeys(
        (data_home / "applications", *(
            Path(directory) / "applications"
            for directory in data_dirs.split(os.pathsep)
            if directory
        ))
    )
    matches: list[tuple[int, Path]] = []
    scan_errors: list[OSError] = []
    scanned = 0

    for root in roots:
        if not root.is_dir():
            continue
        for current, directories, filenames in os.walk(
            root, followlinks=False, onerror=scan_errors.append
        ):
            directories[:] = [
                name
                for name in directories
                if not (Path(current) / name).is_symlink()
            ]
            for filename in filenames:
                if Path(filename).suffix.casefold() != ".desktop":
                    continue
                scanned += 1
                if scanned > MAX_START_MENU_SHORTCUTS:
                    break
                desktop_path = Path(current) / filename
                parser = configparser.ConfigParser(
                    interpolation=None, strict=False
                )
                try:
                    with desktop_path.open(encoding="utf-8") as desktop_file:
                        parser.read_file(desktop_file)
                except (OSError, configparser.Error, UnicodeError) as error:
                    scan_errors.append(OSError(
                        f"Não foi possível ler {desktop_path}: {error}"
                    ))
                    continue
                if not parser.has_section("Desktop Entry"):
                    continue
                if parser.get(
                    "Desktop Entry", "Type", fallback="Application"
                ) != "Application":
                    continue
                if parser.getboolean(
                    "Desktop Entry", "NoDisplay", fallback=False
                ):
                    continue
                name = parser.get("Desktop Entry", "Name", fallback="")
                score = _application_name_score(
                    _normalize_application_name(name), aliases
                )
                if score is not None:
                    matches.append((score, desktop_path))
            if scanned > MAX_START_MENU_SHORTCUTS:
                break
        if scanned > MAX_START_MENU_SHORTCUTS:
            break

    if not matches:
        if scan_errors:
            raise OSError(
                f"Não foi possível pesquisar os aplicativos instalados: "
                f"{scan_errors[0]}"
            )
        raise FileNotFoundError(
            f"Não encontrei “{application}” entre os aplicativos instalados "
            "com uma entrada .desktop."
        )

    matches.sort(key=lambda result: (result[0], str(result[1]).casefold()))
    desktop_path = matches[0][1]
    if not desktop_path.is_file():
        raise FileNotFoundError(
            f"A entrada do aplicativo não está mais disponível: {desktop_path}"
        )
    return desktop_path


def _application_name_score(
    name: str, aliases: tuple[str, ...]
) -> int | None:
    for alias_index, alias in enumerate(aliases):
        if name == alias:
            return alias_index * 10
        if name.startswith(alias + " "):
            return 100 + alias_index * 10 + len(name)
        if f" {alias} " in f" {name} ":
            return 200 + alias_index * 10 + len(name)
    return None


def find_registered_application(application: str) -> tuple[str, str]:
    requested = _normalize_application_name(application)
    if not requested:
        raise ValueError("Informe o nome do aplicativo que deseja abrir.")

    known_aliases = {
        "steam": ("steam",),
        "opera": ("opera",),
        "minecraft": ("minecraft launcher", "minecraft"),
        "gog": ("gog galaxy", "gog"),
        "gog galaxy": ("gog galaxy", "gog"),
    }
    aliases = known_aliases.get(requested, (requested,))
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                command,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "A consulta aos aplicativos registrados do Windows excedeu "
            "o tempo limite."
        ) from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "O Windows não retornou detalhes."
        raise RuntimeError(
            f"Não foi possível consultar os aplicativos do Menu Iniciar: "
            f"{detail}"
        ) from error

    try:
        registered_apps = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "O Windows retornou uma lista de aplicativos inválida."
        ) from error
    if isinstance(registered_apps, dict):
        registered_apps = [registered_apps]
    if not isinstance(registered_apps, list):
        raise RuntimeError("O Windows retornou uma lista de aplicativos inválida.")

    matches: list[tuple[int, str, str]] = []
    for app in registered_apps:
        if not isinstance(app, dict):
            continue
        name = app.get("Name")
        app_id = app.get("AppID")
        if not isinstance(name, str) or not isinstance(app_id, str):
            continue
        normalized_name = _normalize_application_name(name)
        score = _application_name_score(normalized_name, aliases)
        if score is not None:
            matches.append((score, name, app_id))

    if not matches:
        raise FileNotFoundError(
            f"Não encontrei “{application}” entre os aplicativos registrados "
            "no Menu Iniciar."
        )
    matches.sort(key=lambda result: (result[0], result[1].casefold()))
    _, name, app_id = matches[0]
    return name, app_id


def _normalize_application_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.casefold())
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_accents).split())


def search_local_files(
    root: Path,
    query: str,
) -> tuple[list[str], int, bool, bool]:
    if not query.strip():
        raise ValueError("Digite parte do nome que deseja localizar.")
    if not root.is_dir():
        raise ValueError("A pasta selecionada não está disponível.")

    needle = "".join(
        character
        for character in unicodedata.normalize("NFKD", query.casefold())
        if not unicodedata.combining(character)
    )
    matches: list[str] = []
    scanned = 0
    truncated = False
    results_truncated = False

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, directories, filenames in os.walk(
        root, followlinks=False, onerror=raise_walk_error
    ):
        directories[:] = [
            name
            for name in directories
            if not (Path(current) / name).is_symlink()
        ]
        for name in chain(directories, filenames):
            if scanned >= MAX_FOLDER_SEARCH_FILES:
                truncated = True
                break
            scanned += 1
            normalized_name = "".join(
                character
                for character in unicodedata.normalize("NFKD", name.casefold())
                if not unicodedata.combining(character)
            )
            if needle in normalized_name:
                relative_path = (Path(current) / name).relative_to(root)
                if len(matches) < MAX_FOLDER_SEARCH_RESULTS:
                    matches.append(str(relative_path))
                else:
                    results_truncated = True
        if truncated:
            break

    return matches, scanned, truncated, results_truncated


class _DuckDuckGoResults(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._active: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self.results.append({
                "title": "",
                "url": attributes.get("href") or "",
                "snippet": "",
            })
            self._active = "title"
        elif tag in {"a", "div", "td"} and "result__snippet" in classes:
            self._active = "snippet"

    def handle_data(self, data: str) -> None:
        if self._active == "title" and self.results:
            self.results[-1]["title"] += data
        elif self._active == "snippet" and self.results:
            self.results[-1]["snippet"] += data

    def handle_endtag(self, tag: str) -> None:
        if self._active == "title" and tag == "a":
            self._active = None
        elif self._active == "snippet" and tag in {"a", "div", "td"}:
            self._active = None


def validate_public_https_url(url: str) -> str:
    if (
        not isinstance(url, str)
        or len(url) > 2048
        or any(ord(character) < 32 for character in url)
    ):
        raise ValueError("O endereço do site é inválido ou muito longo.")

    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise ValueError("O endereço do site é inválido.") from error

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or hostname.lower() == "localhost"
        or hostname.lower().endswith((".local", ".localhost"))
    ):
        raise ValueError("Só é permitido abrir sites HTTPS públicos.")
    try:
        host_address = ipaddress.ip_address(hostname)
    except ValueError:
        host_address = None
    if host_address is not None and not host_address.is_global:
        raise ValueError("Endereços locais ou privados não podem ser abertos.")
    return url.strip()


def parse_reminder_datetime(value: str) -> datetime:
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("A data do lembrete é inválida.")
    try:
        due_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Não consegui interpretar a data do lembrete.") from error

    if due_at.tzinfo is None:
        due_at = due_at.astimezone()
    due_at = due_at.astimezone()
    if due_at <= datetime.now().astimezone():
        raise ValueError("O horário do lembrete precisa estar no futuro.")
    return due_at


def get_system_status() -> str:
    disk = shutil.disk_usage(Path.home().anchor or Path.home())
    free_gb = disk.free / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)
    processor = platform.processor() or platform.machine() or "indisponível"
    cpu_summary = f"Processador: {processor}."
    try:
        import psutil
    except ImportError:
        process_summary = "Processos: indisponível (psutil não instalado)."
        battery_summary = "Bateria: indisponível (psutil não instalado)."
        memory_summary = "Memória RAM: indisponível (psutil não instalado)."
    else:
        try:
            process_summary = f"Processos em execução: {len(psutil.pids())}."
            memory = psutil.virtual_memory()
            memory_summary = (
                f"Memória RAM: {memory.total / (1024 ** 3):.1f} GB total, "
                f"{memory.available / (1024 ** 3):.1f} GB disponível."
            )
            logical_cpus = psutil.cpu_count(logical=True)
            physical_cpus = psutil.cpu_count(logical=False)
            if logical_cpus is not None:
                cpu_summary += f" Núcleos: {physical_cpus or 'indisponível'} "
                cpu_summary += f"físicos, {logical_cpus} lógicos."
            battery = psutil.sensors_battery()
            if battery is None:
                battery_summary = "Bateria: não detectada."
            else:
                charging = "carregando" if battery.power_plugged else "na bateria"
                battery_summary = (
                    f"Bateria: {battery.percent:.0f}% ({charging})."
                )
        except (OSError, psutil.Error) as error:
            process_summary = "Processos: não foi possível consultar."
            battery_summary = f"Bateria: não foi possível consultar ({error})."
            memory_summary = f"Memória RAM: não foi possível consultar ({error})."

    return "\n".join((
        f"Sistema: {platform.platform()}",
        cpu_summary,
        memory_summary,
        process_summary,
        battery_summary,
        f"Espaço livre na unidade principal: {free_gb:.1f} GB "
        f"de {total_gb:.1f} GB.",
    ))


def search_web(query: str) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("A consulta precisa ter entre 1 e 200 caracteres.")

    url = "https://html.duckduckgo.com/html/?" + urlencode({
        "q": query.strip(),
    })
    request = Request(
        url,
        headers={"User-Agent": "CAPRI/0.1 (local desktop assistant)"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError(
                    f"O serviço de busca retornou HTTP {response.status}."
                )
            document = response.read(1_000_000).decode("utf-8", errors="replace")
    except (HTTPException, URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"A pesquisa na web falhou: {error}") from error

    parser = _DuckDuckGoResults()
    parser.feed(document)
    results = [
        result for result in parser.results
        if result["title"].strip() and result["url"].strip()
    ][:5]
    if not results:
        raise RuntimeError("A busca não retornou resultados legíveis.")

    return "\n\n".join(
        f"{index}. {html.unescape(result['title']).strip()}\n"
        f"URL: {html.unescape(result['url']).strip()}\n"
        f"{html.unescape(result['snippet']).strip()}"
        for index, result in enumerate(results, start=1)
    )
