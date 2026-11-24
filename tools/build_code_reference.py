"""Build deterministic maintainer maps from source without importing the application.

Run from any directory: python3 tools/build_code_reference.py [--check]. Only
explicit authored-source roots are read. No .env, database, upload directory,
native build output or third-party SDK is inspected. See tools/README.md.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/reference"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SYMBOLS = (*FUNCTIONS, ast.ClassDef)
TEMPLATE_ROLES = {
    "base.html": "Shared document head, navigation, signed-in shell and script order.",
    "home.html": "Anonymous landing page and accessible hero carousel.",
    "_avatar.html": "Reusable avatar presentation with current visibility controls.",
    "_display.html": "Browser display-preference dialog.",
    "_empty_state.html": "Reusable empty-result presentation.",
    "_feedback.html": "Shared pending/error/success feedback presentation.",
    "_icons.html": "SVG icon macro registry.",
    "_like_button.html": "Desired-state post/Reel like form and aggregate display.",
    "_tour.html": "Guided-tour dialog and server-supplied JSON configuration.",
    "_tour_prompt.html": "Optional signed-in guided-tour invitation.",
    "auth/dashboard.html": (
        "Owner dashboard; MemberJourney.dismissed_at controls the next-step card."
    ),
    "participation/start.html": (
        "Private next-step choices, explicit hide button and consented public introduction."
    ),
    "education/base.html": "Learning-specific layout and asset blocks within the shared shell.",
    "education/room.html": "Authorized live classroom and host/learner media controls.",
    "reels/layout.html": "Shared shell plus Reel-specific styles and script.",
    "offline/index.html": (
        "Neutral offline workspace enhanced with consented account-scoped browser records."
    ),
}
DOMAIN_ROLES = {
    "auth": "Account registration, sign-in and recovery",
    "community": "Public discussions, community membership and member connections",
    "education": "Educator authoring, learner progress and live-session workflows",
    "employer": "Organization membership and staff approval",
    "events": "Staff-published event details and member RSVP",
    "jobs": "Job discovery, consented applications and private saves/preferences",
    "messages": "Private accepted-connection conversations and attachments",
    "moderation": "Staff community safety review",
    "notifications": "Private inbox and explicit channel choices",
    "offline": "Prepared reading, explicit drafts and synchronization",
    "onboarding": "Optional welcome/discovery using existing privacy controls",
    "pages": "Settings, original resources and install/help pages",
    "participation": "Peer support, recurring activities, welcomes, invitations and digests",
    "profile": "Owner professional profile, field sharing and document review",
    "recruitment": "Staff source discovery/authority and coverage operations",
    "reels": "Short-video playback, publishing and processing status",
    "review": "Authorized private evidence inspection and document decisions",
    "staff": "Administrator/member management and private usage analytics",
}


def source(path: Path) -> str:
    """Read only a caller-selected source file, never runtime configuration."""
    return path.read_text(encoding="utf-8")


def tree(path: Path) -> ast.Module:
    """Parse source declarations without executing imports or decorators."""
    return ast.parse(source(path), filename=str(path.relative_to(ROOT)))


def clean(value: str) -> str:
    """Keep table cells readable and escape Markdown table separators."""
    return " ".join(value.split()).replace("|", "\\|")


def code(value: str) -> str:
    return "`" + clean(value).replace("`", "'") + "`"


def link(path: Path, label: str | None = None, line: int | None = None) -> str:
    relative = path.relative_to(ROOT).as_posix()
    anchor = f"#L{line}" if line else ""
    return f"[{label or relative}](../../{relative}{anchor})"


def summary(node: ast.AST) -> str:
    """Use the entire first paragraph, including wrapped docstring summaries."""
    doc = ast.get_docstring(node) or ""
    return clean(doc.split("\n\n", 1)[0].replace("``", "`"))


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    result = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({ast.unparse(node.args)}){result}"


def declared_calls(node: ast.AST) -> str:
    """Show a few literal call names, not inferred authorization or side effects."""
    statements = node.body if isinstance(node, (*FUNCTIONS, ast.ClassDef)) else [node]
    calls = sorted(
        {
            ast.unparse(item.func)
            for statement in statements
            for item in ast.walk(statement)
            if isinstance(item, ast.Call)
            and isinstance(item.func, (ast.Name, ast.Attribute))
            and not (
                isinstance(item.func, ast.Name)
                and item.func.id
                in {
                    "str",
                    "int",
                    "bool",
                    "len",
                    "list",
                    "set",
                    "dict",
                    "tuple",
                    "min",
                    "max",
                }
            )
        }
    )
    return ", ".join(code(name) for name in calls[:6]) + (" …" if len(calls) > 6 else "")


def heading(title: str, note: str) -> list[str]:
    return [
        f"# {title}",
        "",
        (
            "<!-- Generated by tools/build_code_reference.py; edit source "
            "docstrings or the generator. -->"
        ),
        "",
        note,
        "",
        "Return to the [documentation index](../README.md) or [code guide](../CODE_GUIDE.md).",
        "",
    ]


def python_files(folder: str) -> list[Path]:
    return sorted((ROOT / folder).rglob("*.py"))


def backend() -> str:
    lines = heading(
        "Backend source reference",
        "Every application Python module is listed below. Module-level signatures include "
        "private helpers "
        "so an unfamiliar symbol can be located immediately. Summaries come from source "
        "docstrings; the call column is literal syntax, not a guarantee "
        "of access or commit behavior.",
    )
    files = python_files("app")
    lines += ["## Modules", "", "| Source | Responsibility |", "| --- | --- |"]
    for path in files:
        lines.append(f"| {link(path)} | {summary(tree(path))} |")
    for path in files:
        module = tree(path)
        lines += ["", f"## {path.relative_to(ROOT).as_posix()}", "", link(path), ""]
        doc = ast.get_docstring(module)
        if doc:
            lines += [doc.replace("``", "`"), ""]
        imports = sorted(
            {
                node.module
                for node in ast.walk(module)
                if isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("app.")
            }
        )
        if imports:
            lines += ["Application imports: " + ", ".join(code(name) for name in imports) + ".", ""]
        nodes = [node for node in module.body if isinstance(node, SYMBOLS)]
        if nodes:
            lines += [
                "| Symbol / declared inputs | Responsibility | Literal calls (excerpt) |",
                "| --- | --- | --- |",
            ]
        for node in nodes:
            label = signature(node) if isinstance(node, FUNCTIONS) else "class " + node.name
            calls = declared_calls(node) if isinstance(node, FUNCTIONS) else "Class declaration."
            lines.append(f"| {link(path, code(label), node.lineno)} | {summary(node)} | {calls} |")
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, FUNCTIONS):
                        method_link = link(
                            path, code(node.name + "." + signature(method)), method.lineno
                        )
                        lines.append(
                            f"| {method_link} | {summary(method)} | {declared_calls(method)} |"
                        )
    return "\n".join(lines) + "\n"


def dependencies(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [*node.args.posonlyargs, *node.args.args]
    pairs = list(zip(args[len(args) - len(node.args.defaults) :], node.args.defaults, strict=True))
    pairs += [
        (arg, default)
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
        if default is not None
    ]
    result = []
    for arg, default in pairs:
        if isinstance(default, ast.Call) and ast.unparse(default.func).split(".")[-1] == "Depends":
            value = ast.unparse(default.args[0]) if default.args else "annotation-provided"
            result.append(f"{arg.arg}: {value}")
    return "; ".join(result)


def routes() -> str:
    lines = heading(
        "HTTP route reference",
        "These are literal APIRouter decorators, including their declared prefixes and "
        "parameter dependencies. Middleware, router-level dependencies, in-handler checks "
        "and service checks also affect access. Absence of require_user in this table is "
        "not a claim that an endpoint is public. Static mounts and dynamic URL construction "
        "are documented in the owning source.",
    )
    for path in python_files("app/web"):
        module = tree(path)
        prefixes = {}
        for node in module.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if ast.unparse(node.value.func).split(".")[-1] == "APIRouter":
                    prefix = next(
                        (
                            kw.value.value
                            for kw in node.value.keywords
                            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)
                        ),
                        "",
                    )
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            prefixes[target.id] = prefix
        rows = []
        for node in module.body:
            if not isinstance(node, FUNCTIONS):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(
                    decorator.func, ast.Attribute
                ):
                    continue
                method = decorator.func.attr
                if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                    continue
                if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                    continue
                router_name = ast.unparse(decorator.func.value)
                url = prefixes.get(router_name, "") + str(decorator.args[0].value)
                rows.append(
                    f"| {method.upper()} {code(url)} | {link(path, node.name, node.lineno)} "
                    f"| {code(dependencies(node)) if dependencies(node) else '—'} "
                    f"| {summary(node) or ('Literal calls: ' + declared_calls(node))} |"
                )
        if rows:
            lines += [
                f"## {path.name}",
                "",
                "| Method / path | Handler | Parameter dependencies | Summary |",
                "| --- | --- | --- | --- |",
                *rows,
                "",
            ]
    return "\n".join(lines) + "\n"


def schema() -> str:
    lines = heading(
        "Database declaration reference",
        "This is the checked-in SQLAlchemy model structure, not an inspection of the installed "
        "database. Fields/relationships show their exact source declaration; inherited columns "
        "come from the listed mixins in app/db/base.py. Read the data "
        "guide for privacy and lifecycle rules.",
    )
    lines += [
        (
            "See [data ownership and lifecycle](../DATA_GUIDE.md) and "
            "[migration rules](../../migrations/README.md)."
        ),
        "",
    ]
    for path in python_files("app/models"):
        module = tree(path)
        classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
        if not classes:
            continue
        lines += [f"## {path.name}", "", link(path), ""]
        for cls in classes:
            table = next(
                (
                    node.value.value
                    for node in cls.body
                    if isinstance(node, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "__tablename__" for t in node.targets
                    )
                    and isinstance(node.value, ast.Constant)
                ),
                None,
            )
            lines += [
                f"### {cls.name}" + (f" — {table}" if table else " (vocabulary)"),
                "",
                summary(cls),
                "",
                "Bases: " + ", ".join(code(ast.unparse(b)) for b in cls.bases) + ".",
                "",
                "| Field / relationship | Python type | Source declaration |",
                "| --- | --- | --- |",
            ]
            for node in cls.body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    lines.append(
                        f"| {link(path, code(node.target.id), node.lineno)} "
                        f"| {code(ast.unparse(node.annotation))} "
                        f"| {code(ast.unparse(node.value)) if node.value else '—'} |"
                    )
                elif not table and isinstance(node, ast.Assign):
                    names = ", ".join(ast.unparse(t) for t in node.targets)
                    if not names.startswith("_"):
                        lines.append(
                            f"| {code(names)} | enum value | {code(ast.unparse(node.value))} |"
                        )
            constraints = [
                node
                for node in cls.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__table_args__" for t in node.targets)
            ]
            if constraints:
                lines += ["", "Table constraints/indexes:", ""]
                for node in constraints:
                    values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
                    lines += ["- " + code(ast.unparse(value)) for value in values]
            lines.append("")
    return "\n".join(lines) + "\n"


def header_comment(path: Path) -> str:
    text = source(path)
    match = re.match(r"\s*/\*\*?(.*?)\*/", text, re.S)
    if match:
        return clean(re.sub(r"(?m)^\s*\*\s?", "", match.group(1)).split("Maintainer map:")[0])
    if text.lstrip().startswith("//"):
        return clean(text.lstrip().splitlines()[0][2:])
    if path.name == "home-carousel.js":
        return "Landing carousel with motion/focus/visibility-aware slides and manual controls."
    return "See source and frontend guide."


def frontend() -> str:
    lines = heading(
        "Frontend source reference",
        "All authored templates and feature JavaScript/CSS are indexed here. Asset usages "
        "and Jinja relationships are literal references; inherited/dynamically constructed "
        "references may also apply. Selector excerpts are navigation hints. Third-party SDKs "
        "and generated native/web bundles retain their upstream documentation.",
    )
    templates = sorted((ROOT / "app/templates").rglob("*.html"))
    lines += [
        "## Browser scripts and styles",
        "",
        "| Source | Responsibility | Template references | Selector hooks (excerpt) |",
        "| --- | --- | --- | --- |",
    ]
    for folder, pattern in [("app/static/js", "*.js"), ("app/static/css", "*.css")]:
        for path in sorted((ROOT / folder).glob(pattern)):
            usages = [
                link(t, t.relative_to(ROOT / "app/templates").as_posix())
                for t in templates
                if path.name in source(t)
            ]
            hooks = sorted(set(re.findall(r"\[data-[a-z0-9-]+", source(path))))
            usage_text = ", ".join(usages) or "Inherited/bundled; see load order."
            hook_text = ", ".join(code(h[1:]) for h in hooks[:8])
            if len(hooks) > 8:
                hook_text += " …"
            lines.append(
                f"| {link(path)} | {header_comment(path)} | {usage_text} | {hook_text} |"
            )
    lines += [
        "",
        "## Templates",
        "",
        "| Source | Role | Literal extends/includes/imports | Declared blocks |",
        "| --- | --- | --- | --- |",
    ]
    for path in templates:
        name = path.relative_to(ROOT / "app/templates").as_posix()
        text = source(path)
        refs = re.findall(r"{%\s*(?:extends|include|from|import)\s+['\"]([^'\"]+)['\"]", text)
        blocks = sorted(set(re.findall(r"{%\s*block\s+(\w+)", text)))
        role = TEMPLATE_ROLES.get(name)
        if not role:
            domain = DOMAIN_ROLES.get(path.parent.name, "Reusable presentation")
            subject = path.stem.lstrip("_").replace("_", " ")
            role = f"{domain}: {subject}" + (" partial." if path.stem.startswith("_") else " page.")
        links = [link(ROOT / "app/templates" / ref, ref) for ref in refs]
        lines.append(
            f"| {link(path, name)} | {role} | {', '.join(links) or '—'} "
            f"| {', '.join(code(b) for b in blocks) or 'Partial/macros'} |"
        )
    return "\n".join(lines) + "\n"


def configuration() -> str:
    path = ROOT / "app/core/config.py"
    cls = next(
        node
        for node in tree(path).body
        if isinstance(node, ast.ClassDef) and node.name == "Settings"
    )
    lines = heading(
        "Environment configuration reference",
        "Field names/types/default declarations come from Settings source. No runtime values "
        "or .env files are read. Environment variables use NURSE_NG_ plus the upper-case field "
        "name. Validation may normalize a value or require explicit production configuration; "
        "a source default is not a production recommendation.",
    )
    lines += [
        "Read [hosting setup](../HOSTING.md) before choosing production values. "
        "Settings are cached; restart every affected process after changing them.",
        "",
        "| Environment variable | Type | Source default |",
        "| --- | --- | --- |",
    ]
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id
        if name.startswith("_"):
            continue
        sensitive = any(term in name for term in ("secret", "password", "key", "database_url"))
        default = node.value
        if isinstance(default, ast.Call) and ast.unparse(default.func) == "Field":
            default = next(
                (kw.value for kw in default.keywords if kw.arg == "default"),
                default.args[0] if default.args else None,
            )
        rendered = (
            "Private configuration; inspect source contract."
            if sensitive
            else (code(ast.unparse(default)) if default else "Required")
        )
        lines.append(
            f"| {link(path, code('NURSE_NG_' + name.upper()), node.lineno)} "
            f"| {code(ast.unparse(node.annotation))} | {rendered} |"
        )
    lines += [
        "",
        "Validation entry point: "
        + link(
            path,
            "Settings.validate_security_settings",
            next(
                n.lineno
                for n in cls.body
                if isinstance(n, FUNCTIONS) and n.name == "validate_security_settings"
            ),
        )
        + ".",
        "",
        "Build-only mobile variables, provider PORT and test-runner variables are described "
        "in the mobile, deployment and tests guides; they are not Settings fields.",
    ]
    return "\n".join(lines) + "\n"


def tests() -> str:
    lines = heading(
        "Test source reference",
        "All checked-in Python test modules/runners and mobile test scripts are listed. "
        "Case names describe intended regression coverage, not a claim that they have run "
        "against a live provider or device. Read tests/README.md before "
        "running isolated browser/hosting journeys.",
    )
    lines += ["| Source | Purpose | Top-level cases |", "| --- | --- | --- |"]
    for path in python_files("tests"):
        module = tree(path)
        cases = [
            node.name
            for node in module.body
            if isinstance(node, FUNCTIONS) and node.name.startswith("test_")
        ]
        case_count = len(cases) if cases else "Runner/helpers/fixtures"
        lines.append(f"| {link(path)} | {summary(module)} | {case_count} |")
    for path in sorted((ROOT / "mobile/tests").glob("*.mjs")):
        lines.append(
            f"| {link(path)} | Origin, release configuration and offline-bundle checks. "
            "| Node test runner |"
        )
    lines += ["", "## Python case names", ""]
    for path in python_files("tests"):
        cases = [
            node
            for node in tree(path).body
            if isinstance(node, FUNCTIONS) and node.name.startswith("test_")
        ]
        if cases:
            lines += [f"### {path.name}", ""]
            lines += ["- " + link(path, code(node.name), node.lineno) for node in cases]
            lines.append("")
    return "\n".join(lines) + "\n"


def infrastructure() -> str:
    lines = heading(
        "Infrastructure and migration source reference",
        "Authored process/build entry points, migration revisions and checked-in deployment/CI "
        "definitions. The generator lists source only: it does not start services, execute "
        "operator commands, migrate a database, build an app or deploy infrastructure.",
    )
    files = [
        ROOT / "app/cli.py",
        *python_files("deploy"),
        *python_files("mobile/scripts"),
        ROOT / "migrations/env.py",
        ROOT / "tools/build_code_reference.py",
    ]
    for path in sorted(files):
        module = tree(path)
        lines += [
            f"## {path.relative_to(ROOT).as_posix()}",
            "",
            link(path),
            "",
            summary(module),
            "",
        ]
        nodes = [node for node in module.body if isinstance(node, SYMBOLS)]
        if nodes:
            lines += ["| Symbol | Role |", "| --- | --- |"]
            for node in nodes:
                label = code(signature(node) if isinstance(node, FUNCTIONS) else node.name)
                lines.append(f"| {link(path, label, node.lineno)} | {summary(node)} |")
            lines.append("")
    lines += [
        "## CLI commands",
        "",
        "Names below are parsed declarations. Inspect --help and "
        "the maintenance guide before invoking commands against an installation.",
        "",
        "| Command | Source help |",
        "| --- | --- |",
    ]
    cli = tree(ROOT / "app/cli.py")
    commands = {}
    for node in ast.walk(cli):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
        ):
            if node.args and isinstance(node.args[0], ast.Constant):
                commands[node.args[0].value] = next(
                    (
                        kw.value.value
                        for kw in node.keywords
                        if kw.arg == "help" and isinstance(kw.value, ast.Constant)
                    ),
                    "See --help.",
                )
    # The staff bootstrap pair is declared by a literal loop rather than add_parser constants.
    for name in ("set-staff", "unset-staff"):
        commands[name] = (
            "Operator bootstrap/recovery staff flag change; accepts an existing account phone."
        )
    lines += [
        f"| {code(name)} | {clean(help_text)} |" for name, help_text in sorted(commands.items())
    ]
    lines += [
        "",
        "## Migration revisions",
        "",
        "The parent column describes the source graph. "
        "Use alembic heads/current against the intended environment to find its actual state.",
        "",
        "| Source | Revision | Parent(s) | Change |",
        "| --- | --- | --- | --- |",
    ]
    for path in python_files("migrations/versions"):
        module = tree(path)
        values = {}
        for node in module.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        values[target.id] = ast.literal_eval(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in {"revision", "down_revision"}:
                    values[node.target.id] = ast.literal_eval(node.value)
        description = (ast.get_docstring(module) or "").splitlines()[0]
        lines.append(
            f"| {link(path, path.name)} | {code(str(values.get('revision')))} "
            f"| {code(str(values.get('down_revision')))} | {clean(description)} |"
        )
    lines += [
        "",
        "## Mobile/custom native and deployment definitions",
        "",
        "| Source | Responsibility |",
        "| --- | --- |",
    ]
    entries = {
        "Dockerfile": (
            "Python/web/worker runtime image, scanner/media dependencies and process entry."
        ),
        "render.yaml": (
            "Render single-service deployment definition; startup all "
            "applies migrations then launches services."
        ),
        "deploy/production.env.example": (
            "Setting names and operator guidance for production; no runtime secrets."
        ),
        "deploy/install-local-clamav.sh": (
            "Workstation malware-scanner setup; platform/privilege "
            "requirements in deployment guide."
        ),
        "deploy/install-local-search.sh": (
            "Workstation SearXNG setup, separate from application web requests."
        ),
        "deploy/searxng/compose.yaml": "Local search-service container definition.",
        "deploy/searxng/settings.yml": "Local SearXNG search-engine settings.",
        ".github/workflows/checks.yml": (
            "Lint, reference freshness, Python/mobile checks and isolated "
            "PostgreSQL/container verification."
        ),
        ".github/workflows/mobile.yml": (
            "Manually triggered mobile preview/simulator artifacts; does not "
            "publish store releases."
        ),
        "mobile/package.json": "Pinned mobile tooling and build/test script entry points.",
        "mobile/scripts/configure.mjs": "Validate origin and generate mobile settings/bundle.",
        "mobile/scripts/build-android.mjs": "Build/copy preview or explicitly signed release APKs.",
        "mobile/resources/shell.html": "Unconfigured preview shell containing no member data.",
        ("mobile/android/app/src/main/java/com/nurseng/app/MainActivity.java"): (
            "Capacitor lifecycle, Back handling, resume sync and offline navigation installation."
        ),
        ("mobile/android/app/src/main/java/com/nurseng/app/OfflineWebViewClient.java"): (
            "Bounded same-site GET failure fallback at the site's origin; "
            "preserve TLS/auth/POST errors."
        ),
        "mobile/ios/App/App/AppDelegate.swift": (
            "Capacitor application lifecycle and URL/universal-link forwarding."
        ),
        "mobile/ios/App/App/SceneDelegate.swift": (
            "Scene/resume sync, Capacitor policy forwarding and same-origin "
            "bundled offline navigation."
        ),
        "app/static/vendor/README.md": (
            "Vendored SDK versions, licenses and original distribution provenance."
        ),
        "app/certificates/README.md": "Host-scoped TLS intermediate provenance and trust limits.",
        "app/static/img/CREDITS.txt": "Image provenance and attribution.",
        "app/static/fonts/OFL.txt": "Bundled font license.",
    }
    for relative, purpose in entries.items():
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"Reference entry is missing: {relative}")
        lines.append(f"| {link(path)} | {purpose} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Generate all pages, or check exact freshness without writing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report stale pages; do not write.")
    args = parser.parse_args()
    pages = {
        "BACKEND.md": backend(),
        "ROUTES.md": routes(),
        "SCHEMA.md": schema(),
        "FRONTEND.md": frontend(),
        "CONFIGURATION.md": configuration(),
        "TESTS.md": tests(),
        "INFRASTRUCTURE.md": infrastructure(),
    }
    stale = [
        name
        for name, content in pages.items()
        if not (OUTPUT / name).exists() or source(OUTPUT / name) != content
    ]
    if args.check:
        if stale:
            print("Stale source reference: " + ", ".join(stale))
            print("Run python3 tools/build_code_reference.py and commit the updated pages.")
            return 1
        print(f"All {len(pages)} source reference pages are current.")
        return 0
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, content in pages.items():
        (OUTPUT / name).write_text(content, encoding="utf-8")
    print(f"Generated {len(pages)} source reference pages in docs/reference/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
