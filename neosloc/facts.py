# neosloc: ignore (detection vocabulary, not usage)
"""Observations about a repository, computed once and shared by all criteria.

Every observation returns evidence: a list of `Hit`s (path + detail). An
empty list means "not observed". Criteria (criteria.py) only combine facts;
all pattern knowledge lives here.

Content patterns are matched against the code view of product code
(repo.grep), library names only against dependency manifests.
"""
from __future__ import annotations

import ast
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .repo import STATICALLY_TYPED, Repo, estimate_tokens
from .specs import Spec, find_specs, openapi_operations


@dataclass(frozen=True)
class Hit:
    path: Optional[str]
    detail: str = ""


Hits = List[Hit]


def _hits(found: Dict[str, int], detail: str = "") -> Hits:
    return [Hit(p, detail or "%d match%s" % (n, "" if n == 1 else "es")) for p, n in
            sorted(found.items(), key=lambda kv: -kv[1])]


# ---------------------------------------------------------------------------
# Pattern catalogue

ROUTE_PATTERNS = [
    ("fastapi/flask", r"\.py$", r"@\w+\.(get|post|put|patch|delete|route|api_route|websocket)\(\s*['\"]"),
    ("django", r"urls\.py$", r"\b(re_)?path\(\s*r?['\"]"),
    ("drf", r"\.py$", r"\.register\(\s*r?['\"]"),
    ("express/koa/hono", r"\.[jt]sx?$", r"\b(app|router|server|api)\.(get|post|put|patch|delete|all|route)\(\s*['\"`]"),
    ("nestjs", r"\.ts$", r"@(Get|Post|Put|Patch|Delete|All)\("),
    ("nextjs-route", r"(^|/)app/.*route\.[jt]s$", r"export\s+(async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b"),
    ("spring/jax-rs", r"\.(java|kt)$", r"@(Get|Post|Put|Patch|Delete|Request)Mapping\b|@(GET|POST|PUT|DELETE|PATCH)\b"),
    ("rails", r"routes\.rb$", r"^\s*(get|post|put|patch|delete|resources?|match)\s+['\":]"),
    ("laravel", r"\.php$", r"Route::(get|post|put|patch|delete|any|resource|apiResource)\("),
    ("slim/php", r"\.php$", r"\$app->(get|post|put|patch|delete|map)\("),
    ("go-http", r"\.go$", r"\.(HandleFunc|Handle|GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete)\(\s*\""),
    ("rust-axum/actix", r"\.rs$", r"\.route\(\s*\"|#\[(get|post|put|patch|delete)\(\s*\""),
    ("aspnet", r"\.cs$", r"\[Http(Get|Post|Put|Patch|Delete)\b|\.Map(Get|Post|Put|Patch|Delete)\("),
    ("vapor/hummingbird", r"\.swift$", r"\b(app|routes|router|group|grouped\([^)]*\))\.(get|post|put|patch|delete|on)\(\s*\""),
]
SERVER = re.compile(r"\bFastAPI\(|\bFlask\(|\bexpress\(\)|new\s+Hono\(|http\.ListenAndServe|HttpServer::new|axum::serve"
                    r"|uvicorn\.run\(|\bapp\.listen\(|ROOT_URLCONF|WSGI_APPLICATION|createServer\("
                    r"|Application\(\.detect|import Vapor\b|import Hummingbird\b")
GENERATED_SPEC = [
    ("FastAPI (auto OpenAPI)", "code", r"\bFastAPI\("),
    ("django-ninja", "code", r"\bNinjaAPI\("),
    ("drf-spectacular", "deps", r"drf[_-]spectacular"),
    ("drf-yasg", "deps", r"drf[_-]yasg"),
    ("flask-smorest/apispec", "deps", r"flask[_-]smorest|\bapispec\b|flasgger"),
    ("springdoc/springfox", "deps", r"springdoc|springfox"),
    ("@nestjs/swagger", "deps", r"@nestjs/swagger"),
    ("tsoa/zod-openapi/fastify-swagger", "deps",
     r"\"(tsoa|@asteasolutions/zod-to-openapi|@hono/zod-openapi|fastify-swagger|@fastify/swagger)\""),
    ("swaggo", "deps", r"swaggo/swag"),
    ("utoipa/aide/poem-openapi", "deps", r"\b(utoipa|aide|poem-openapi)\b"),
    ("Swashbuckle/NSwag", "deps", r"Swashbuckle|NSwag"),
    ("graphql server", "deps", r"strawberry-graphql|\bgraphene\b|apollo-server|@apollo/server|gqlgen|async-graphql|graphql-yoga"),
]
# Standard wire protocols a server can speak. (name, where, pattern, application protocol?)
# An application protocol means off-the-shelf clients can use the server (a contract);
# a bare transport such as WebSocket carries custom messages, so it is only a surface.
# Codec/broker libraries in manifests count only when the code also opens a listener,
# so that client libraries (redis-py, paho, fred) don't make a project a server.
PROTOCOL_SERVERS = [
    ("RESP (Redis wire protocol)", "deps", r"\b(redis-protocol|redis_protocol|redcon|resp-async)\b", True),
    ("MQTT broker", "deps", r"\b(rumqttd|mqttbytes|ntex-mqtt|amqtt|hbmqtt|aedes|mochi-mqtt|moquette|mqtt-packet)\b", True),
    ("gRPC server", "code", r"add_\w+Servicer_to_server|tonic::transport::Server|grpc\.NewServer\(|new\s+grpc\.Server\(", True),
    ("PostgreSQL wire protocol", "deps", r"\b(pgwire|postgres-wire)\b", True),
    ("Kafka protocol", "deps", r"\bkafka-protocol\b", True),
    ("SMTP server", "deps", r"\b(aiosmtpd|smtp-server|go-smtp|mailin)\b", True),
    ("WebSocket server", "code", r"accept_async\(|WebSocketServer\(|websockets\.serve\(|websocket\.Upgrader|tokio_tungstenite::accept", False),
]
# Native error replies of standard protocols (only meaningful when the project serves one).
PROTOCOL_ERRORS = re.compile(r"Resp[23]?Frame::(Error|SimpleError|BlobError)|\bFrame::Error\b|\bSimpleError\b|"
                             r"['\"]-(ERR|WRONGTYPE)\b|\b\w*ReasonCode\b|ConnectReturnCode|tonic::Status|"
                             r"Status::(new|invalid_argument|not_found|internal|unavailable)|status\.Error\(codes\.|"
                             r"grpc\.StatusCode|SqlState")
ENV_NAME_LITERAL = re.compile(r"""['"]([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)['"]""")
LISTENER = re.compile(r"TcpListener::bind|UdpSocket::bind|net\.Listen\(|asyncio\.start_server|socketserver\.|"
                      r"createServer\(|ServerSocket\(|\.listen\(\s*\d|serve_forever\(")
PROTOCOL_DOC = r"(^|/)(PROTOCOL|protocol|WIRE|wire)[\w.-]*\.(md|rst|txt|adoc)$|(^|/)docs?/[\w/-]*protocol[\w.-]*\.(md|rst)$|(^|/)asyncapi[\w.-]*\.(ya?ml|json)$"

MCP_SERVER = re.compile(r"\bFastMCP\(|from mcp\.server|@modelcontextprotocol/sdk/server|\bMcpServer\(|\bServerHandler\b"
                        r"|server\.NewMCPServer|mcp_server\.run\(")
ARG_PARSING = re.compile(
    r"\bimport (argparse|click|typer|fire|docopt)\b|from (click|typer) import|ArgumentParser\("
    r"|['\"](commander|yargs|oclif|meow|cac)['\"]|process\.argv"
    r"|spf13/cobra|urfave/cli|\"flag\"|flag\.Parse\(|os\.Args|\bclap\b|std::env::args|picocli|String\[\] args"
    r"|import ArgumentParser\b|\b(Async)?ParsableCommand\b|CommandLine\.arguments")
JSON_FLAG = re.compile(r"""['"]--(json|format|output)['"]|['"]-o['"]|\bjson=True\b|"json"\s*:\s*\{|--json\b"""
                       r"""|@(Flag|Option)(\([^)]*\))?\s*var\s+(json|format|output)\b""")
PROMPT = re.compile(r"(?<![\w.])input\(|getpass\(|click\.(prompt|confirm)\(|typer\.(prompt|confirm)\(|inquirer|"
                    r"readline\.question\(|promptui\.|dialoguer::|questionary\.|prompt_toolkit")
NONINTERACTIVE_GUARD = re.compile(r"isatty\(\)|--yes\b|--no-input\b|--non-interactive\b|assume_yes|IsTerminal\(")
PY_ADD_ARGUMENT = re.compile(r"\.add_argument\(\s*((?:['\"][^'\"]+['\"]\s*,?\s*)+)([^)]*)\)", re.S)
CLICK_OPTION = re.compile(r"@click\.(option|argument)\(([^)]*)\)", re.S)
EXIT_CODES_DOC = re.compile(r"(exit|return)\s+(status|code)s?\b", re.I)
JSON_SCHEMA_CODE = re.compile(r"json-schema\.org/[\w/-]*schema|\"\$schema\"|'\$schema'")
DRY_RUN = re.compile(r"dry[-_ ]?run|--check\b|validate[-_]only|--plan\b")
LIMIT_OPTIONS = re.compile(r"""['"]--(max[-_][\w-]+|timeout|budget|limit|deadline)['"]""")
STDERR_DIAG = re.compile(r"file=sys\.stderr|sys\.stderr\.write|logging\.|getLogger\(|console\.error\(|eprintln!"
                         r"|os\.Stderr|log\.(Print|Fatal)|System\.err|FileHandle\.standardError|fputs\([^)]*stderr"
                         r"|\bLogger\(\s*(subsystem|label)|os_log\(")
NONZERO_EXIT = re.compile(r"sys\.exit\(\s*[1-9]|SystemExit\(|exit\(\s*[1-9]|os\.Exit\(\s*[1-9]|process\.exit\(\s*[1-9]"
                          r"|process::exit\(\s*[1-9]|return\s+(EXIT_\w+|[1-9])\b|exit_status|ExitCode")
JSON_ERROR = re.compile(r"""["']error["']\s*:""")
COLOR = re.compile(r"\x1b\[|\\033\[|\\x1b\[|colorama|\brich\b|chalk|termcolor|fatih/color|owo_colors|colored\(")
COLOR_GUARD = re.compile(r"NO_COLOR|isatty\(\)|force_terminal|supports_color|IsTerminal\(")
VERBOSITY = re.compile(r"""['"]--(quiet|log[-_]level|loglevel|debug|silent|verbosity)['"]|['"]-q['"]|count=True|action="count"|PersistentFlags\(\)\.CountP""")
STRUCTURED_LOG = re.compile(r"""['"]--log[-_]format['"]|class\s+\w*Json\w*Formatter|structlog|python-json-logger|jsonlogger|\bpino\b|winston|go\.uber\.org/zap|zerolog|slog\.NewJSONHandler|logstash""")
TRACING = re.compile(r"opentelemetry|@opentelemetry/|go\.opentelemetry\.io|jaeger|zipkin|ddtrace|newrelic|elastic-apm")
METRICS = re.compile(r"prometheus|/metrics\b|statsd|micrometer|metrics\.NewCounter|prom-client|django-prometheus|starlette_exporter")
HEALTH = re.compile(r"""['"`]/(health|healthz|healthcheck|ready|readyz|livez|ping)\b""")
HEALTHCHECK_CFG = re.compile(r"^HEALTHCHECK\b|healthcheck:|livenessProbe|readinessProbe", re.M)
STD_LOGGER = re.compile(r"getLogger\(__name__\)|getLogger\(['\"][\w.]+['\"]\)|require\(['\"]debug['\"]\)|log::(debug|info|warn)|\bslog\.|zap\.L\(\)|LoggerFactory"
                        r"|\bLogger\(\s*(subsystem|label)|import Logging\b|os_log\(|electron-log|QLoggingCategory|Serilog|NLog")
PRINT_CALL = re.compile(r"^\s*print\(", re.M)
LOG_LEVEL_CALL = re.compile(r"\b(?:self\.|Self\.)?(?:log|logger|LOG|LOGGER|logging)\.(debug|info|notice|warning|warn|error|exception|critical|fault|trace)\(")
EXCEPTION_CLASS = re.compile(r"^class\s+\w+\((\w+\.)?(\w*Error|\w*Exception)\)"                       # Python
                             r"|^\s*(public\s+|internal\s+)?(enum|struct|class)\s+\w+\s*:\s*[^{\n]*\b(Error|LocalizedError)\b"  # Swift
                             r"|\bclass\s+\w+\s+extends\s+\w*(Error|Exception)\b"                          # JS/TS, Java
                             r"|\bclass\s+\w+(\([^)]*\))?\s*:\s*\w*(Exception|Error)\b"                   # Kotlin, C#
                             r"|\bstruct\s+\w+Error\b|\benum\s+\w*Error\b", re.M)                          # Rust, Go-style
SYS_EXIT = re.compile(r"\bsys\.exit\(|\bexit\(\d")
ARG_VALIDATION = re.compile(r"raise\s+(ValueError|TypeError|\w+Error)\(\s*f?['\"]|throw\s+new\s+(TypeError|RangeError|Error)\(")
TIMEOUT_PARAM = re.compile(r"\btimeout\s*[:=]")
RETRY_PARAM = re.compile(r"\b(max_)?retries\s*[:=]|\bretry\s*[:=]")
DOCTEST = re.compile(r"doctest|>>>\s")

# Events
INTERNAL_EVENTS = re.compile(r"Signal\(\)|\.connect\(|EventEmitter|\.emit\(|celery|bullmq|sidekiq|outbox|pg_notify|pubsub")
OUTBOUND_WEBHOOK = re.compile(
    r"(send|deliver|dispatch|fire|trigger|emit|post|notify)_?\w*webhook|webhook\w*(subscription|endpoint|delivery|deliveries|sender|dispatcher)"
    r"|Webhook(Endpoint|Subscription|Delivery)|class\s+\w*Webhook\w*\(.*Model", re.I)
SIGNED_WEBHOOK = re.compile(r"X-Hub-Signature|X-Signature|Webhook-Signature|hmac\.new\(|createHmac\(|hmac\.New\(")
STREAMING = re.compile(r"text/event-stream|EventSourceResponse|ServerSentEvent|websocket|socket\.io|@WebSocketGateway|channels\.generic", re.I)
CLOUDEVENTS = re.compile(r"cloudevents|ce-specversion|\"specversion\"", re.I)
EVENT_STREAM_CLI = re.compile(r"ndjson|jsonl|json[-_]lines|--stream\b")
EVENT_HOOK_CLI = re.compile(r"""['"]--on[-_][\w-]+['"]|['"]--exec['"]|['"]--webhook[\w-]*['"]""")
LONG_RUNNING = re.compile(r"""['"]--(watch|follow|serve|daemon|listen)['"]|add_parser\(\s*['"](serve|watch|daemon|listen|run-server)['"]|@\w+\.command\(\s*['"]?(serve|watch|daemon)""")

# Identity
TOKEN_AUTH = re.compile(r"\b(pyjwt|jsonwebtoken|python-jose|golang-jwt|TokenAuthentication|HTTPBearer|APIKeyHeader|"
                        r"X-API-Key|BearerAuth|passport-http-bearer|knox|simplejwt|sanctum)\b", re.I)
OAUTH = re.compile(r"\b(authlib|oauthlib|django-oauth-toolkit|oauth2_provider|social[-_]auth|allauth|passport-oauth2|"
                   r"next-auth|@auth/core|openid-client|keycloak|spring-security-oauth2|go-oidc|omniauth|doorkeeper|"
                   r"laravel/passport|authentik|fusionauth|auth0)\b", re.I)
MANAGED_KEYS = re.compile(r"service[_ ]?account|personal[_ ]?access[_ ]?token|class\s+Api[_]?(Key|Token)\b|ApiToken\b|machine[_ ]user", re.I)
SCOPES = re.compile(r"\bscopes?\s*[=:\[]|Security\([^)]*scopes|@PreAuthorize|permission_classes|has_perm\(|@RolesAllowed|casbin|cancancan|pundit")
OIDC_SCIM = re.compile(r"\bscim\b|client_credentials|\boidc\b", re.I)
CREDENTIAL_ENV = re.compile(r"(environ(\.get)?|getenv|env::var|process\.env|Getenv)\W{1,4}([A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)")
SECRET_FLAG = re.compile(r"""['"]--([\w-]*(token|password|passwd|secret|api[-_]key|auth[-_]header|credential)s?)['"]""", re.I)
ENV_FALLBACK = re.compile(r"envvar\s*=|default\s*=\s*os\.(environ|getenv)|auto_envvar_prefix|\.Env\(|env\s*=\s*['\"]")
SECRET_LOGGED = re.compile(r"(print|logger\.\w+|logging\.\w+|console\.log)\([^)\n]*\b(api_key|token|secret|password|auth_headers?)\b", re.I)
PROFILES = re.compile(r"""['"]--profile['"]|\bprofiles?\b.*\b(config|credentials)\b""", re.I)

# Portability
OWNS_DATA_PATH = re.compile(r"(^|/)(migrations/|alembic/|db/migrate/|prisma/schema\.prisma$|schema\.sql$|liquibase|flyway|ent/schema/)")
OWNS_DATA_CODE = re.compile(r"models\.Model\b|declarative_base\(|DeclarativeBase\b|@Entity\b|gorm\.Model|#\[derive\([^)]*Queryable|"
                            r"sequelize\.define|mongoose\.Schema|sqlite3\.connect\(|ActiveRecord::Base|Eloquent|"
                            r"NSPersistentContainer|NSManagedObject|import SwiftData\b|@Model\b|import GRDB\b|import RealmSwift\b|tauri-plugin-sql")
DB_DRIVERS = re.compile(r"\b(psycopg2?|asyncpg|mysqlclient|pymysql|pymongo|motor|\"pg\"|mysql2|mongodb|sqlx|diesel|gorm|"
                        r"sqlalchemy|django|prisma|typeorm|sequelize|mongoose)\b", re.I)
EXPORT = re.compile(r"""(def|function|func|fn)\s+\w*(export|backup)\w*\s*\(|['"`]/[\w/{}:<>.-]*\b(export|dump|backup)\b|add_parser\(\s*['"](export|dump|backup)""")
IMPORT = re.compile(r"""(def|function|func|fn)\s+\w*(import_|restore|bulk_load)\w*\s*\(|['"`]/[\w/{}:<>.-]*\b(import|restore)\b|add_parser\(\s*['"](import|restore|load)""")
OPEN_FORMATS = re.compile(r"csv\.writer|DictWriter|to_csv\(|json\.dump\(|ndjson|jsonl|parquet|pyarrow|geojson|icalendar|vcard|rdflib|datapackage|frictionless|openpyxl")
EXPORT_DOC = re.compile(r"\bexport(ing|s)?\b.{0,60}\b(format|schema|csv|json|ndjson|parquet)", re.I)

# Ergonomics (service)
# FastAPI, DRF and NestJS return JSON errors by default.
JSON_ERRORS_SVC = re.compile(r"\bFastAPI\(|HTTPException|rest_framework|@nestjs/common|exception_handler|@ControllerAdvice|@ExceptionHandler|errorHandler|ErrorResponse\b|APIException|HttpException|setErrorHandler|JsonResponse\(\s*\{\s*['\"]error")
VALIDATION = re.compile(r"\b(pydantic|marshmallow|serializers\.|zod|joi|yup|class-validator|ajv|jsonschema|go-playground/validator|@Valid)\b")
PAGINATION = re.compile(r"\bcursor\b|next_page|page_size|PageNumberPagination|CursorPagination|LimitOffsetPagination|paginat|rel=\"next\"")
PROBLEM_DETAILS = re.compile(r"application/problem\+json|ProblemDetail|problem_details|http-problem")
IDEMPOTENCY = re.compile(r"Idempotency-Key|idempotency_key")
RATE_LIMIT = re.compile(r"X-RateLimit|RateLimit-(Limit|Remaining|Reset)|slowapi|django-ratelimit|express-rate-limit|rate-limiter-flexible|throttle_classes|golang\.org/x/time/rate")
CONDITIONAL = re.compile(r"\bETag\b|If-Match|If-None-Match")
AGENT_DOCS = r"(^|/)(llms(-full)?\.txt|AGENTS\.md|CLAUDE\.md|GEMINI\.md|\.cursorrules|\.github/copilot-instructions\.md|\.well-known/ai-plugin\.json)$"

# Embeddability
DOCKERFILE = r"(^|/)(Dockerfile|Containerfile)(\.[\w.-]+)?$"
COMPOSITION = r"(^|/)((docker-)?compose(\.[\w.-]+)?\.ya?ml|Chart\.yaml|[\w.-]+\.tf|Pulumi\.ya?ml)$"
ENV_TEMPLATE = r"(^|/)\.env[\w.-]*\.(example|sample|template|dist)$|[\w.-]*(config|settings)[\w.-]*\.schema\.json$"
ENV_READ = re.compile(r"os\.environ|os\.getenv|getenv\(|process\.env\.|std::env::var|env::var\(|System\.getenv|ENV\[|BaseSettings\b|envconfig")
PUBLISH = re.compile(r"pypa/gh-action-pypi-publish|twine upload|npm publish|cargo publish|goreleaser|gem push|poetry publish|uv publish|flit publish|pod trunk push")
SINGLE_BINARY = r"(^|/)(\.goreleaser\.ya?ml|[\w.-]+\.spec)$"
EXTRAS = re.compile(r"\[project\.optional-dependencies\]|extras_require|peerDependenciesMeta|\[features\]")

# Extensibility
SEAM = re.compile(r"^def\s+(register\w*|add_\w*plugin\w*|add_\w*hook\w*)\s*\(|\bclass\s+\w*(Registry|PluginManager)\b|"
                  r"^\w*REGISTRY\s*[:=]|\bregisterPlugin\b|\baddHook\b|\bhookspec\b", re.M)
OUT_OF_TREE = re.compile(r"metadata\.entry_points\(|\bentry_points\(\s*group\s*=|iter_entry_points|pluggy\.PluginManager|load_setuptools_entrypoints|"
                         r"stevedore|ServiceLoader\.load|plugin\.Open\(|pkgutil\.iter_modules|import_module\([^)]*(plugin|config)")
EXT_API_VERSION = re.compile(r"(PLUGIN|EXTENSION|HOOK)_?API_?VERSION|api_version\s*=|apiVersion\b", re.I)
HOOKS = re.compile(r"\bhookimpl\b|\bhookspec\b|add_action\(|add_filter\(|register_hook|addHook|\bon_(start|finish|load|init)\b")

# Desktop GUI applications: (toolkit, where, pattern)
DESKTOP_TOOLKITS = [
    ("Electron", "deps", r'"electron"\s*:'),
    ("Tauri", "path", r"(^|/)(src-tauri/tauri\.conf\.json|tauri\.conf\.json)$"),
    ("Qt", "code+deps", r"\b(PyQt[56]|PySide[26])\b|QApplication\(|QGuiApplication\(|find_package\(Qt[56]"),
    ("GTK", "code+deps", r"gi\.repository import Gtk|Gtk\.Application|\bgtk4?\s*=|gtkmm|libadwaita"),
    ("Tkinter", "code", r"^\s*(import tkinter|from tkinter)"),
    ("wxWidgets", "code+deps", r"\bimport wx\b|wxPython|wx/wx\.h"),
    ("WPF/WinForms", "config", r"<UseWPF>true|<UseWindowsForms>true|<UseMaui>true"),
    ("Avalonia", "deps", r"\bAvalonia\b"),
    ("JavaFX/Swing", "code+deps", r"\bjavafx\b|javax\.swing"),
    ("Compose Desktop", "deps", r"compose\.desktop"),
    ("Rust GUI", "deps", r"\b(eframe|egui|iced|slint|druid)\s*="),
    ("Fyne/Wails", "deps", r"fyne\.io/fyne|wailsapp/wails"),
    ("Flutter desktop", "path", r"^(macos|windows|linux)/(Runner|runner|flutter)/"),
]
# macOS app with SwiftUI/AppKit (SwiftUI alone may be iOS).
MACOS_APP = re.compile(r"\bimport (AppKit|Cocoa)\b|NSApplication\b|NSWindow\b|\bMenuBarExtra\b|\.macOS\(\.v|MACOSX_DEPLOYMENT_TARGET|SDKROOT = macosx")
URL_SCHEME = re.compile(r"CFBundleURLTypes|CFBundleDocumentTypes|x-scheme-handler|setAsDefaultProtocolClient|"
                        r"\"(protocols|fileAssociations)\"\s*:|deep-link|open-url|onOpenURL|application\(_:open|LSHandler")
DESKTOP_ARGS = re.compile(r"process\.argv|CommandLine\.arguments|QCommandLineParser|sys\.argv|std::env::args|"
                          r"getMatches\(|cli\s*:\s*\{|tauri_plugin_cli|ArgumentParser\(|clap::")
AUTOMATION = re.compile(r"NSAppleScriptEnabled|OSAScriptingDefinition|import AppIntents\b|\bAppIntent\b|AppShortcutsProvider|"
                        r"\bzbus\b|\bdbus\b|QDBus|Gio\.DBus|ComVisible|IDispatch")  # not ipcMain/tauri::command: internal UI IPC
HEADLESS = re.compile(r"""['"]--(headless|batch|no-gui|nogui|cli|export)['"]|headless\s*[:=]\s*(true|True)|QT_QPA_PLATFORM""")
AUTOMATION_CONTRACT = r"(^|/)[\w.-]+\.sdef$|(^|/)[\w.-]*(dbus|DBus)[\w.-]*\.xml$"
INSTALLER = r"(^|/)(electron-builder\.(ya?ml|json)|forge\.config\.[jt]s|[\w.-]+\.wxs|[\w.-]+\.iss|[\w.-]+\.nsi|AppImageBuilder\.ya?ml|snapcraft\.ya?ml|[\w.-]+\.flatpak\.(json|ya?ml)|Package\.appxmanifest|[\w.-]+\.desktop|[\w.-]+\.spec)$"
INSTALLER_CODE = re.compile(r"create-dmg|hdiutil|pkgbuild|productbuild|notarytool|\"bundle\"\s*:\s*\{|electron-builder|\[tool\.briefcase\]|cx_Freeze|pyinstaller", re.I)
PACKAGE_MANAGER = re.compile(r"brew install --cask|Casks/|winget|chocolatey|choco install|flathub|snapcraft upload|snap install|"
                             r"tauri-apps/tauri-action|electron-builder[^\n]*--publish|action-gh-release", re.I)
MANAGED_CONFIG = re.compile(r"defaults write|\.mobileconfig|Group Policy|ADMX|managed preferences", re.I)
CRASH_REPORTING = re.compile(r"sentry|crashpad|breakpad|crashlytics|bugsnag|MetricKit|PLCrashReporter|crashReporter\.start", re.I)
DESKTOP_VERBOSITY = re.compile(r"""['"]--(verbose|debug|log[-_]level)['"]|\blog[_-]?[lL]evel\b|LogLevel\b""")
CREDENTIAL_STORE = re.compile(r"\bKeychain\b|SecItemAdd|kSecClass|\bkeytar\b|safeStorage|libsecret|SecretService|"
                              r"CredentialManager|PasswordVault|\bkeyring\b|tauri-plugin-stronghold|keyring-rs")

# Legibility
CI = r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.yml|\.circleci/config\.yml|Jenkinsfile|\.travis\.yml|azure-pipelines\.yml|\.woodpecker\.ya?ml|bitbucket-pipelines\.yml)$"
LOCKFILES = r"(^|/)(uv\.lock|poetry\.lock|Pipfile\.lock|pdm\.lock|requirements[\w.-]*\.lock|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|Cargo\.lock|go\.sum|Gemfile\.lock|composer\.lock|gradle\.lockfile|packages\.lock\.json|flake\.lock|mix\.lock)$"
README = r"^(?i:readme)(\.\w+)?$"  # README.md, readme.md (common on npm), Readme.rst
MODULE_TOKEN_BUDGET = 32_000
FILE_TOKEN_BUDGET = 12_000

# Stability
SEMVER_TAG = re.compile(r"^v?\d+\.\d+(\.\d+)?([-+.].*)?$")
CHANGELOG = re.compile(r"^((docs?|packages/[^/]+)/)?(CHANGELOG|CHANGES|HISTORY|NEWS|RELEASES?)(\.(md|rst|txt|adoc))?$", re.I)
BREAKING_MARK = re.compile(r"\bbreaking\b|\bincompatib|^#+\s*removed\b|\bdeprecat", re.I | re.M)
DEPRECATION = re.compile(r"@Deprecated|@deprecated|DeprecationWarning|FutureWarning|#\[deprecated|\bdeprecated\s*=\s*True|"
                         r"Deprecation:|Sunset:|\[Obsolete|warnings\.warn\(|@available\([^)]*deprecated")
VERSIONED_PATH = re.compile(r"""['"`]\^?/?(api/)?v\d+(/|['"`])""")
MAX_HISTORY_TAGS = 20
HISTORY_GREP = r"add_argument|__all__|Deprecat|deprecated|warnings\.warn|FutureWarning"
FIX_SUBJECT = re.compile(r"\b(fix(e[sd])?|bug|hotfix|patch|regression|crash|broken|workaround|revert)\b", re.I)

# Library / frontend
FRONTEND_DEPS = re.compile(r"\"(react|vue|svelte|@angular/core|solid-js|preact|vite|webpack|parcel|next|nuxt)\"\s*:")
API_DOCS_GEN = re.compile(r"sphinx\.ext\.autodoc|mkdocstrings|\bpdoc\b|typedoc|jsdoc|autodoc|rustdoc|godoc|swift-docc-plugin|\bjazzy\b")


class Facts:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.surfaces = None  # set by the engine once surfaces are detected

    # ---- low-level helpers --------------------------------------------------

    @property
    def code(self) -> List[str]:
        return self.repo.source_files(include_tests=False)

    def grep(self, rx, files=None, keep_regex=False) -> Hits:
        return _hits(self.repo.grep(rx if hasattr(rx, "search") else re.compile(rx, re.M),
                                    self.code if files is None else files, keep_regex=keep_regex))

    def deps(self, rx) -> Hits:
        return _hits(self.repo.grep(rx if hasattr(rx, "search") else re.compile(rx, re.M | re.I), self.repo.manifests()))

    def docs(self, rx) -> Hits:
        rx = rx if hasattr(rx, "search") else re.compile(rx, re.M | re.I)
        return _hits({f: len(rx.findall(self.repo.read(f))) for f in self.repo.doc_files()
                      if not self.repo.is_test(f) and rx.search(self.repo.read(f))})

    def paths(self, rx: str) -> Hits:
        r = re.compile(rx)
        return [Hit(f) for f in self.repo.files if r.search(f) and not self.repo.is_test(f)]

    def config(self, rx) -> Hits:
        rx = rx if hasattr(rx, "search") else re.compile(rx, re.M)
        return _hits({f: len(rx.findall(self.repo.read(f))) for f in self.repo.config_files()
                      if rx.search(self.repo.read(f))})

    def workflows(self, rx) -> Hits:
        rx = rx if hasattr(rx, "search") else re.compile(rx, re.M)
        files = [f for f in self.repo.files if re.search(CI, f)]
        return _hits({f: len(rx.findall(self.repo.read(f))) for f in files if rx.search(self.repo.read(f))})

    def _cached(self, key, fn):
        if not hasattr(self, "_cache"):
            self._cache = {}
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # ---- service ------------------------------------------------------------

    def routes(self) -> Dict[str, Dict[str, int]]:
        def compute():
            by_fw = {}
            for fw, path_rx, route_rx in ROUTE_PATTERNS:
                prx, rrx = re.compile(path_rx), re.compile(route_rx, re.M)
                hits = self.repo.grep(rrx, [f for f in self.code if prx.search(f)], keep_regex=True)
                if hits:
                    by_fw[fw] = hits
            return by_fw
        return self._cached("routes", compute)

    def route_files(self) -> List[str]:
        return sorted({f for h in self.routes().values() for f in h})

    def route_total(self) -> int:
        return sum(sum(h.values()) for h in self.routes().values())

    def route_hits(self) -> Hits:
        return [Hit(max(h, key=h.get), "%s: %d route declarations" % (fw, sum(h.values())))
                for fw, h in self.routes().items()]

    def server(self) -> Hits:
        return self.grep(SERVER)

    def mcp_server(self) -> Hits:
        return self.grep(MCP_SERVER)

    def protocol_servers(self, application_only: bool = False) -> Hits:
        """Standard protocols this project serves (not merely consumes)."""
        def compute():
            listener = bool(self.grep(LISTENER))
            out = []
            for name, where, rx, app in PROTOCOL_SERVERS:
                if where == "deps":
                    found = self.deps(re.compile(rx)) if listener else []
                else:
                    found = self.grep(re.compile(rx))
                out += [(Hit(h.path, name), app) for h in found[:1]]
            return out
        return [h for h, app in self._cached("protocols", compute) if app or not application_only]

    def protocol_errors(self) -> Hits:
        if not self.protocol_servers(application_only=True):
            return []
        return [Hit(h.path, "native protocol error replies") for h in self.grep(PROTOCOL_ERRORS)]

    def env_var_names(self) -> List[str]:
        """Variable names in files that read the environment (literal X_Y names, so helpers
        such as env_or("APP_PORT", …) are covered)."""
        names: Set[str] = set()
        for h in self.grep(ENV_READ):
            names |= set(ENV_NAME_LITERAL.findall(self.repo.code_text(h.path)))
        return sorted(names)

    def env_documented(self) -> Hits:
        names = self.env_var_names()
        if not names:
            return []
        docs = "\n".join(self.repo.read(f) for f in self.repo.doc_files())
        documented = [n for n in names if n in docs]
        if len(documented) * 2 >= len(names):
            return [Hit(None, "%d of %d environment variables named in the docs" % (len(documented), len(names)))]
        return []

    def protocol_doc(self) -> Hits:
        return [Hit(h.path, "protocol specification") for h in self.paths(PROTOCOL_DOC)]

    def specs(self) -> List[Spec]:
        return self._cached("specs", lambda: find_specs(self.repo))

    def api_specs(self) -> Hits:
        return [Hit(s.path, "%s, %d operations" % (s.kind, len(s.operations))) for s in self.specs()
                if s.kind in ("openapi", "graphql", "protobuf", "asyncapi")]

    def generated_spec(self) -> Hits:
        out = []
        for name, where, rx in GENERATED_SPEC:
            found = (self.deps if where == "deps" else self.grep)(re.compile(rx))
            out += [Hit(h.path, name) for h in found[:1]]
        return out

    def spec_coverage(self) -> Optional[float]:
        ops = sum(len(s.operations) for s in self.specs() if s.kind == "openapi")
        total = self.route_total()
        if not ops or not total:
            return None
        return min(1.0, ops / float(total))

    # ---- cli ----------------------------------------------------------------

    def entry_points(self) -> Hits:
        def compute():
            out = []
            for f in self.repo.manifests():
                t = self.repo.read(f)
                if f.endswith(("pyproject.toml", "setup.cfg", "setup.py")) and re.search(
                        r"\[project\.scripts\]|\[tool\.poetry\.scripts\]|console_scripts", t):
                    out.append(Hit(f, "console script"))
                elif f.endswith("package.json") and re.search(r"\"bin\"\s*:", t):
                    out.append(Hit(f, "npm bin"))
                elif f.endswith("Cargo.toml") and re.search(r"\[\[bin\]\]", t):
                    out.append(Hit(f, "cargo bin"))
            out += [Hit(f, "cargo binary") for f in self.repo.files if re.search(r"(^|/)src/main\.rs$", f)]
            for f in self.repo.glob(r"(^|/)Package\.swift$"):
                if re.search(r"\.executable(Target)?\(", self.repo.read(f)):
                    out.append(Hit(f, "swift executable"))
            out += [Hit(f, "go main") for f in self.code if f.endswith(".go")
                    and re.search(r"^package main\b", self.repo.read(f), re.M) and "func main(" in self.repo.read(f)]
            return out
        return self._cached("entry_points", compute)

    def arg_parsing(self) -> Hits:
        return self.grep(ARG_PARSING)

    def cli_files(self) -> List[str]:
        return [h.path for h in self.arg_parsing()]

    def prompts(self) -> Hits:
        return self.grep(PROMPT)  # anywhere in product code: helpers called by the CLI can block too

    def noninteractive_guard(self) -> Hits:
        return self.grep(NONINTERACTIVE_GUARD)

    def option_help(self) -> Tuple[int, int, Hits]:
        """(options with help, options in total, evidence) for argparse/click definitions."""
        with_help = total = 0
        where: Dict[str, int] = defaultdict(int)
        for f in self.cli_files():
            if not f.endswith(".py"):
                continue
            text = self.repo.read(f)
            for m in PY_ADD_ARGUMENT.finditer(text):
                total += 1
                if re.search(r"\bhelp\s*=", m.group(2)) or re.search(r"argparse\.SUPPRESS", m.group(2)):
                    with_help += 1
                    where[f] += 1
            for m in CLICK_OPTION.finditer(text):
                total += 1
                if m.group(1) == "argument" or re.search(r"\bhelp\s*=", m.group(2)):
                    with_help += 1
                    where[f] += 1
        return with_help, total, _hits(dict(where), "options with help text")

    def json_output(self) -> Hits:
        return self.grep(JSON_FLAG, self.cli_files())

    def exit_codes_documented(self) -> Hits:
        """Docs or help text that list exit statuses."""
        rx = re.compile(r"(exit|return)\s+(status|code)s?\b[^\n]{0,200}\b[0-9]{1,3}\b", re.I)
        found = self.docs(rx)
        found += _hits({f: 1 for f in self.cli_files() if rx.search(self.repo.read(f))}, "help text")
        return found

    def distinct_error_exit_codes(self) -> int:
        rx = re.compile(r"(exit|return)\s+(status|code)s?\b[^\n]{0,300}", re.I)
        codes: Set[str] = set()
        for f in self.repo.doc_files() + self.cli_files():
            for m in rx.finditer(self.repo.read(f)):
                codes |= {c for c in re.findall(r"\b([1-9][0-9]{0,2})\b", m.group(0))}
        return len(codes)

    def json_errors(self) -> Hits:
        if not self.json_output():
            return []
        return self.grep(JSON_ERROR, self.cli_files() + [f for f in self.code if re.search(r"(error|exception)s?\.\w+$", f)])

    def color_ok(self) -> Hits:
        uses = self.grep(COLOR, self.cli_files() or self.code)
        if not uses:
            return [Hit(None, "no colored output")]
        return self.grep(COLOR_GUARD)

    def output_schema(self) -> Hits:
        return self.grep(JSON_SCHEMA_CODE) + [h for h in self.paths(r"[\w.-]*\.schema\.json$")
                                              if "output" in h.path or "report" in h.path or "result" in h.path]

    # ---- library ------------------------------------------------------------

    def library(self) -> Hits:
        def compute():
            out = []
            publish = bool(self.workflows(PUBLISH))
            service = bool(self.route_total() or self.server())
            for pj in self.repo.glob(r"^(packages/[^/]+/)?package\.json$"):
                t = self.repo.read(pj)
                explicit = re.search(r'"(module|exports|types|typings|files)"\s*:', t)
                is_app = bool(self.repo.glob(r"^(public/|src/|app/)?index\.html$"))
                private = re.search(r'"private"\s*:\s*true', t)
                if (explicit or (re.search(r'"main"\s*:', t) and not is_app)) and not private:
                    out.append(Hit(pj, "npm package"))
            py_manifest = self.repo.glob(r"^(pyproject\.toml|setup\.py|setup\.cfg)$")
            if py_manifest and (not service or publish):
                pkgs = sorted({f.split("/")[0] for f in self.code if f.endswith("/__init__.py") and f.count("/") == 1}
                              | {f.split("/")[1] for f in self.code if f.startswith("src/") and f.endswith("/__init__.py")
                                 and f.count("/") == 2})
                if pkgs and re.search(r"\[project\]|setup\(|\[tool\.poetry\]|\[metadata\]",
                                      "".join(self.repo.read(m) for m in py_manifest)):
                    out.append(Hit(py_manifest[0], "Python package " + ", ".join(pkgs)))
            gomod = self.repo.glob(r"^go\.mod$")
            if gomod and any(f.endswith(".go") and not re.search(r"^package main\b", self.repo.read(f), re.M)
                             for f in self.code if not re.search(r"(^|/)(cmd|internal)/", f)):
                out.append(Hit(gomod[0], "Go module with exported packages"))
            out += [Hit(f, "Rust library crate") for f in self.repo.glob(r"^(crates/[^/]+/)?src/lib\.rs$")]
            out += [Hit(f, "Swift package library") for f in self.repo.glob(r"^Package\.swift$")
                    if re.search(r"\.library\(", self.repo.read(f))]
            return out
        return self._cached("library", compute)

    def python_packages(self) -> List[str]:
        return sorted({f.rsplit("/", 1)[0] for f in self.code if f.endswith("__init__.py")
                       and (f.count("/") == 1 or (f.startswith("src/") and f.count("/") == 2))})

    def public_api_delimited(self) -> Hits:
        out = []
        for pkg in self.python_packages():
            if re.search(r"^__all__\s*=", self.repo.read(pkg + "/__init__.py"), re.M):
                out.append(Hit(pkg + "/__init__.py", "__all__"))
        # An npm package's entry point (exports/main/module/types) is its public API.
        for h in self.library():
            if h.detail == "npm package":
                out.append(Hit(h.path, "package entry point"))
        out += [Hit(h.path, "exported identifiers") for h in self.library() if "Go module" in h.detail]
        out += [Hit(h.path, "pub items") for h in self.library() if "Rust" in h.detail]
        out += [Hit(h.path, "public access control") for h in self.library() if "Swift" in h.detail]
        return out

    def typed_api(self) -> Hits:
        out = [Hit(f, "py.typed") for f in self.repo.glob(r"(^|/)py\.typed$")]
        for h in self.library():
            if h.detail != "npm package":
                continue
            root = posixpath.dirname(h.path)
            ts = any(self.repo.language(f) == "typescript" and f.startswith(root) for f in self.code)
            if re.search(r'"(types|typings)"\s*:', self.repo.read(h.path)) or ts:
                out.append(Hit(h.path, "TypeScript types"))
        out += [Hit(h.path, "statically typed language") for h in self.library()
                if "Go module" in h.detail or "Rust" in h.detail or "Swift" in h.detail]
        return out

    def api_reference(self) -> Hits:
        return (self.config(API_DOCS_GEN) + self.deps(API_DOCS_GEN)
                + self.grep(API_DOCS_GEN, [f for f in self.repo.files if f.endswith("conf.py")])
                + [Hit(f, "DocC catalog") for f in sorted({p.split(".docc/")[0] + ".docc" for p in self.repo.files if ".docc/" in p})])

    def published(self) -> Hits:
        """Released to where consumers install from: a registry upload in CI, or for Swift
        packages (resolved by git tag) semver tags."""
        out = self.workflows(PUBLISH)
        if self.repo.glob(r"^Package\.swift$") and self.semver_tags():
            out.append(Hit("Package.swift", "Swift package released by semver tags"))
        return out

    # ---- desktop ------------------------------------------------------------

    def desktop(self) -> Hits:
        def compute():
            out = []
            for name, where, rx in DESKTOP_TOOLKITS:
                r = re.compile(rx, re.M)
                if where == "path":
                    found = self.paths(rx)
                elif where == "deps":
                    found = self.deps(r)
                elif where == "config":
                    found = _hits({f: 1 for f in self.repo.files if f.endswith(".csproj") and r.search(self.repo.read(f))})
                elif where == "code":
                    found = self.grep(r)
                else:
                    found = self.grep(r) + self.deps(r)
                out += [Hit(h.path, name) for h in found[:1]]
            swiftui = self.grep(re.compile(r"\bimport (SwiftUI|AppKit|Cocoa)\b"))
            project_files = self.repo.glob(r"\.xcodeproj/project\.pbxproj$") + self.repo.glob(r"(^|/)Package\.swift$")
            macos = bool(self.grep(MACOS_APP)) or any(MACOS_APP.search(self.repo.read(p)) for p in project_files)
            if swiftui and macos:  # SwiftUI alone may be an iOS app
                out.append(Hit(swiftui[0].path, "macOS SwiftUI/AppKit"))
            return out
        return self._cached("desktop", compute)

    def desktop_files(self) -> List[str]:
        return list(self.code) + [f for f in self.repo.files if f.endswith((".plist", ".json", ".toml", ".xml", ".yml",
                                                                              ".yaml", ".desktop", ".entitlements"))]

    def url_scheme(self) -> Hits:
        return _hits({f: len(URL_SCHEME.findall(self.repo.read(f))) for f in self.desktop_files()
                      if URL_SCHEME.search(self.repo.read(f)) and not self.repo.is_test(f)})

    def automation(self) -> Hits:
        return _hits({f: len(AUTOMATION.findall(self.repo.read(f))) for f in self.desktop_files()
                      if AUTOMATION.search(self.repo.read(f)) and not self.repo.is_test(f)})

    def credential_store(self) -> Hits:
        return self.grep(CREDENTIAL_STORE) + self.deps(CREDENTIAL_STORE)

    # ---- frontend -----------------------------------------------------------

    def frontend(self) -> Hits:
        html = self.repo.glob(r"^(public/|src/|app/)?index\.html$")
        pkg = self.repo.glob(r"^package\.json$")
        if not (html and pkg):
            return []
        fw = self.deps(FRONTEND_DEPS)
        return [Hit(html[0], "index.html + package.json" + (" (%s)" % fw[0].path if fw else ""))]

    # ---- properties that decide applicability -------------------------------

    def long_running(self) -> Hits:
        return self.grep(LONG_RUNNING, self.cli_files())

    def owns_data(self) -> Hits:
        return (self.paths(OWNS_DATA_PATH.pattern)[:3] + self.grep(OWNS_DATA_CODE)[:3]
                + [h for h in self.deps(DB_DRIVERS)[:1]])

    def uses_credentials(self) -> Hits:
        return self.grep(CREDENTIAL_ENV) + self.grep(SECRET_FLAG, self.cli_files())

    # ---- releases and history -----------------------------------------------

    def semver_tags(self) -> List[str]:
        return self._cached("tags", lambda: [t for t in self.repo.git_safe("tag", "--list", "--sort=creatordate").split()
                                             if SEMVER_TAG.match(t)])

    def changelog(self) -> Hits:
        return [Hit(f) for f in self.repo.files if CHANGELOG.search(f)]

    def history_removals(self) -> Tuple[int, List[str], Hits]:
        """Across consecutive semver tags: (comparisons made, items removed without prior deprecation, evidence).

        Items are OpenAPI operations, CLI long options and Python `__all__` names. Only the most
        recent MAX_HISTORY_TAGS releases are compared (the history integrators live with), and
        each release is read with one `git grep` plus one batched `git cat-file`, so projects
        with hundreds of tags (and partial clones) stay fast."""
        tags = self.semver_tags()[-MAX_HISTORY_TAGS:]
        if len(tags) < 2:
            return 0, [], []

        def snapshot(tag):
            listing = self.repo.git_safe("ls-tree", "-r", "--name-only", tag).split("\n")
            specs = ["%s:%s" % (tag, f) for f in listing if f and not self.repo.is_test(f)
                     and f.endswith((".yaml", ".yml", ".json")) and re.search(r"openapi|swagger", f, re.I)]
            grep = self.repo.git_safe("grep", "-l", "-E", HISTORY_GREP, tag, "--", "*.py")
            specs += [line for line in grep.split("\n") if line and not self.repo.is_test(line.split(":", 1)[-1])]
            texts = self.repo.git_cat_files(specs)
            items: Set[str] = set()
            deprecated_text = ""
            for spec, text in texts.items():
                f = spec.split(":", 1)[1]
                if not f.endswith(".py"):
                    items |= {"op " + o for o in openapi_operations(text, f) or ()}
                    continue
                items |= {"option " + o for o in re.findall(r"""add_argument\([^)]*?['"](--[\w-]+)['"]""", text)}
                if f.endswith("__init__.py") and f.count("/") <= 1:
                    m = re.search(r"^__all__\s*=\s*\[([^\]]*)\]", text, re.M)
                    if m:
                        items |= {"symbol " + x for x in re.findall(r"['\"](\w+)['\"]", m.group(1))}
                if DEPRECATION.search(text):
                    deprecated_text += text
            return items, deprecated_text

        removed: List[str] = []
        prev_items, prev_dep = snapshot(tags[0])
        for tag in tags[1:]:
            items, dep = snapshot(tag)
            for gone in sorted(prev_items - items):
                if gone.split(" ", 1)[1] not in prev_dep:
                    removed.append("%s (removed in %s)" % (gone, tag))
            prev_items, prev_dep = items, dep
        ev = [Hit(None, "%d tagged releases compared" % len(tags))]
        return len(tags) - 1, removed, ev

    # ---- packaging ----------------------------------------------------------

    def command_names(self) -> List[str]:
        names: Set[str] = set()
        for f in self.repo.manifests():
            t = self.repo.read(f)
            if f.endswith("pyproject.toml"):
                m = re.search(r"\[project\.scripts\]\s*\n((?:[^\[\n][^\n]*\n?)*)", t)
                if m:
                    names |= set(re.findall(r"^\s*([\w.-]+)\s*=", m.group(1), re.M))
            elif f.endswith("package.json"):
                m = re.search(r'"bin"\s*:\s*(\{[^}]*\}|"[^"]*")', t)
                if m and m.group(1).startswith("{"):
                    names |= set(re.findall(r'"([\w.-]+)"\s*:', m.group(1)))
                elif m:
                    nm = re.search(r'"name"\s*:\s*"([^"]+)"', t)
                    if nm:
                        names.add(nm.group(1).split("/")[-1])
            elif f.endswith("Package.swift"):
                names |= set(re.findall(r"\.executable\(\s*name:\s*\"([\w.-]+)\"", t))
            elif f.endswith("Cargo.toml") or f.endswith("go.mod"):
                nm = re.search(r'^name\s*=\s*"([^"]+)"|^module\s+\S*?([\w.-]+)\s*$', t, re.M)
                if nm:
                    names.add(nm.group(1) or nm.group(2))
        return sorted(names)

    def runtime_deps(self) -> Optional[int]:
        for f in self.repo.manifests():
            t = self.repo.read(f)
            if f.endswith("pyproject.toml"):
                m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", t, re.M | re.S)
                if m:
                    return len(re.findall(r"['\"][^'\"]+['\"]", m.group(1)))
            if f.endswith("package.json"):
                m = re.search(r'"dependencies"\s*:\s*\{([^}]*)\}', t)
                return len(re.findall(r'"[^"]+"\s*:', m.group(1))) if m else 0
            if f.endswith("Package.swift"):
                return len(re.findall(r"\.package\(", t))
        return None

    def seam_names(self) -> List[str]:
        names: Set[str] = set()
        for f in self.code:
            for m in re.finditer(r"^def\s+(register\w*|add_\w*plugin\w*|add_\w*hook\w*)\s*\(",
                                 self.repo.code_text(f), re.M):
                names.add(m.group(1))
        return sorted(names)

    def test_text(self) -> Dict[str, str]:
        return {f: self.repo.read(f) for f in self.repo.source_files() if self.repo.is_test(f)}

    # ---- legibility ---------------------------------------------------------

    def legibility(self) -> Dict:
        return self._cached("legibility", lambda: measure_legibility(self.repo))


# ---------------------------------------------------------------------------
# Legibility measurements (moved unchanged from the 0.4 detector)


def _module_of(rel: str) -> str:
    return posixpath.dirname(rel) or "."


def _top_level_imports(tree):
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            if "TYPE_CHECKING" not in ast.dump(node.test):
                stack.extend(node.body + node.orelse)
        elif isinstance(node, ast.Try):
            stack.extend(node.body)


def _python_analysis(repo: Repo, files: List[str]):
    annotated = total = 0
    edges: Set[tuple] = set()
    by_name: Dict[str, str] = {}
    for f in files:
        parts = f[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            by_name.setdefault(".".join(parts[i:]), f)

    def resolve(dotted):
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            hit = by_name.get(".".join(parts[:i]))
            if hit:
                return hit
        return None

    for f in files:
        try:
            tree = ast.parse(repo.read(f))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                args = [a for a in node.args.args if a.arg not in ("self", "cls")]
                if node.returns is not None or any(a.annotation is not None for a in args):
                    annotated += 1
        for node in _top_level_imports(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            else:
                if node.level:
                    pkg = f[:-3].split("/")
                    pkg = pkg[: len(pkg) - node.level]
                    base = ".".join(pkg + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                names = ["%s.%s" % (base, a.name) if base else a.name for a in node.names]
            for n in names:
                hit = resolve(n)
                if hit and hit != f:
                    edges.add((f, hit))
    return annotated, total, edges


JS_IMPORT = re.compile(r"""(?:import\s[^'"]*?from\s*|import\s*\(|require\()\s*['"](\.{1,2}/[^'"]+)['"]""")
JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte")


def _js_edges(repo: Repo, files: List[str]) -> Set[tuple]:
    edges = set()
    for f in files:
        for target in JS_IMPORT.findall(repo.read(f)):
            dest = posixpath.normpath(posixpath.join(posixpath.dirname(f), target))
            cands = [dest] + [dest + e for e in JS_EXTS] + [dest + "/index" + e for e in JS_EXTS]
            hit = next((c for c in cands if repo.exists(c)), None)
            if hit and hit != f:
                edges.add((f, hit))
    return edges


def cycles(edges: Set[tuple]) -> List[List[str]]:
    graph: Dict[str, List[str]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
        graph.setdefault(b, [])
    index, low, stack, on, out = {}, {}, [], set(), []
    counter = [0]

    def strong(v):
        work = [(v, iter(graph[v]))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        while work:
            node, it = work[-1]
            nxt = next(it, None)
            if nxt is None:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    if len(comp) > 1:
                        out.append(sorted(comp))
            elif nxt not in index:
                index[nxt] = low[nxt] = counter[0]
                counter[0] += 1
                stack.append(nxt)
                on.add(nxt)
                work.append((nxt, iter(graph[nxt])))
            elif nxt in on:
                low[node] = min(low[node], index[nxt])

    for v in list(graph):
        if v not in index:
            strong(v)
    return out


def measure_legibility(repo: Repo) -> Dict:
    src = repo.source_files(include_tests=False)
    tests = [f for f in repo.source_files() if repo.is_test(f)]
    file_tokens = {f: estimate_tokens(repo.read(f)) for f in src}
    src_tokens = sum(file_tokens.values())
    test_tokens = sum(estimate_tokens(repo.read(f)) for f in tests)
    module_tokens: Dict[str, int] = defaultdict(int)
    lang_tokens: Dict[str, int] = defaultdict(int)
    for f, t in file_tokens.items():
        module_tokens[_module_of(f)] += t
        lang_tokens[repo.language(f)] += t
    py = [f for f in src if repo.language(f) == "python"]
    annotated, total_fn, py_edges = _python_analysis(repo, py) if py else (0, 0, set())
    py_share = annotated / float(total_fn) if total_fn else 0.0
    typed = sum(t for l, t in lang_tokens.items() if l in STATICALLY_TYPED) + int(lang_tokens.get("python", 0) * py_share)
    js = [f for f in src if repo.language(f) in ("javascript", "typescript")]
    edges = py_edges | (_js_edges(repo, js) if js else set())
    cyc = cycles(edges)
    within = sum(1 for t in module_tokens.values() if t <= MODULE_TOKEN_BUDGET)
    big_files = sorted(((t, f) for f, t in file_tokens.items() if t > FILE_TOKEN_BUDGET), reverse=True)
    fan_out: Dict[str, int] = defaultdict(int)
    for a, _ in edges:
        fan_out[a] += 1
    largest_module = max(module_tokens.items(), key=lambda kv: kv[1]) if module_tokens else (".", 0)
    return {
        "source_files": len(src),
        "source_tokens": src_tokens,
        "test_files": len(tests),
        "test_tokens": test_tokens,
        "test_ratio": round(test_tokens / float(src_tokens), 2) if src_tokens else 0.0,
        "modules": len(module_tokens),
        "modules_within_budget": round(within / float(len(module_tokens)), 2) if module_tokens else 1.0,
        "oversized_files": [f for _, f in big_files],
        "largest_module": {"path": largest_module[0], "tokens": largest_module[1]},
        "typed_ratio": round(typed / float(src_tokens), 2) if src_tokens else 0.0,
        "python_functions": total_fn,
        "python_annotated": annotated,
        "import_edges": len(edges),
        "import_graph": bool(py or js),
        "max_fan_out": max(fan_out.values()) if fan_out else 0,
        "import_cycles": len(cyc),
        "largest_cycle": max(cyc, key=len) if cyc else [],
        "languages": {k: v for k, v in sorted(lang_tokens.items(), key=lambda kv: -kv[1])},
        "test_example": next((t for t in tests if not t.endswith("__init__.py")), None),
    }


