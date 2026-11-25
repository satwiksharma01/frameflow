"""The thinker: whatever writes an answer to one of Frameflow's requests.

Frameflow drives every step. It sends a thinker the request it already writes
and gets back only the answer, which it checks against a schema and its own
check. Any problems go back for a fix round, at most MAX_FIX_ROUNDS of them;
then the step stops with what is still wrong, in one plain line.

A thinker is either an agent on this PC (Claude Code, OpenCode), run without a
window in the repository with read-only tools, or the creator's own API key,
through the providers in `project/providers/`. An agent writes nothing: its
answer is the last fenced ```json block of its final message, and Frameflow
writes every file after checking it.

The choice comes from the environment the app sets for one job:
    FRAMEFLOW_THINKER    auto (default) | agent:claude | agent:opencode | key
    FRAMEFLOW_SERVICE    for a key: anthropic | openai | openrouter | gemini | custom
    FRAMEFLOW_MODEL      for a key; anthropic has a default
    FRAMEFLOW_BASE_URL   for custom: any OpenAI-compatible address
    FRAMEFLOW_KEY        the key, for this run only
"""
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from jsonschema import Draft202012Validator

from project.providers import ProviderError, ToolSpec

MAX_FIX_ROUNDS = 3

REPO_ROOT = Path(__file__).resolve().parent.parent

AGENT_TIMEOUT = 20 * 60  # seconds; a pitch's plan looks facts up on the web
VERSION_TIMEOUT = 10
SLICE = 0.5  # seconds between looks at what a running agent has logged


class ThinkError(Exception):
    """One plain line, already redacted, for the creator to read."""


class Thinker(Protocol):
    name: str
    can_search: bool
    can_see: bool       # it can open an image file and look at it: the agent's eyes on a clip's sheet

    def answer(self, system: str, request: str, schema: dict,
               check: Callable[[dict], list[str]], *, search: bool = False, material: Sequence[Path] = ()) -> dict:
        """The first answer the schema and `check` both accept. `search` is for the step that writes facts;
        `material` is the video's files, whose folders an agent may read."""
        ...


def redact(text: str, secret: str | None) -> str:
    """Replace the secret, and any run of 8 or more of its characters, with an ellipsis."""
    if not secret:
        return text
    if len(secret) < 8:
        return text.replace(secret, "…")
    starts = {secret[i:i + 8] for i in range(len(secret) - 7)}
    out, i = [], 0
    while i < len(text):
        if text[i:i + 8] in starts:
            end = i + 8
            while end < len(text) and text[i:end + 1] in secret:
                end += 1
            out.append("…")
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _line(text: str, limit: int = 300) -> str:
    text = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- checking an answer, and the fix rounds -------------------------------------------

_JSON_BLOCK = re.compile(r"```json[ \t]*\n(.*?)```", re.S | re.I)


def _problems(answer, schema: dict, check: Callable[[dict], list[str]]) -> list[str]:
    if not isinstance(answer, dict):
        return ["The answer must be a JSON object."]
    errors = [f"at {'/'.join(str(p) for p in e.path) or 'the top'}: {e.message}"
              for e in Draft202012Validator(schema).iter_errors(answer)]
    return errors or check(answer)


def _read(reply, schema: dict, check) -> tuple[object, list[str]]:
    """The answer in a reply (a dict, or an agent's text), and what is wrong with it."""
    if isinstance(reply, str):
        blocks = _JSON_BLOCK.findall(reply)
        if not blocks:
            return None, ["There was no ```json block in the answer. End the final message with one."]
        try:
            reply = json.loads(blocks[-1])
        except json.JSONDecodeError as e:
            return None, [f"The answer's JSON could not be read: {e}."]
    return reply, _problems(reply, schema, check)


def _fix_request(request: str, answer, problems: list[str]) -> str:
    last = "" if answer is None else (
        "\n\nYour last answer:\n\n```json\n" + json.dumps(answer, indent=2, ensure_ascii=False) + "\n```")
    listed = "\n".join(f"- {p}" for p in problems)
    return (f"{request}\n\n## Fix your last answer{last}\n\n"
            f"It had these problems. Send the whole answer again, with each one fixed:\n\n{listed}\n")


def _still_wrong(name: str, problems: list[str]) -> str:
    return f"{name}'s answer still had problems after {MAX_FIX_ROUNDS} fix rounds: " + "; ".join(problems)


def _fix_rounds(name: str, ask: Callable[[str, str], object], system: str, request: str,
                schema: dict, check) -> dict:
    """Ask, check, and send the problems back, for at most MAX_FIX_ROUNDS fixes."""
    asked = request
    for _ in range(MAX_FIX_ROUNDS + 1):
        answer, problems = _read(ask(system, asked), schema, check)
        if not problems:
            return answer
        asked = _fix_request(request, answer, problems)
    raise ThinkError(_line(_still_wrong(name, problems)))


# --- agents ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    command: str
    # A run's arguments and environment, given whether it may use the web: the plan step looks facts up for any video,
    # and an agent reading untrusted pages and material must have no way to send the creator's files out. Outside
    # the repository it may read only `folders`, those of the video's files.
    args: Callable[[bool, Sequence[Path]], tuple[str, ...]] = lambda search, folders: ()  # the request on stdin
    env: Callable[[bool, Sequence[Path]], dict[str, str]] = lambda search, folders: {}


_HOME = Path.home().resolve()


def _folders(material: Sequence[Path]) -> list[Path]:
    """The folders of the video's files outside the repository, which an agent may read. Left out, with the file
    still named in the request: a network path, as Claude Code cannot take one as a working directory; a drive's
    root, the home folder and any folder above it, which would open everything below, ~/.ssh too; and on Windows a
    path holding a character cmd.exe acts on, as it runs Claude Code installed with npm and quotes no such path."""
    network = os.sep * 2  # \\server\share on Windows, where //server/share reads the same; //server/share elsewhere
    # Spotted before resolving, which would look the server up; a mapped drive is spotted once resolved.
    parents = (Path(path).resolve().parent for path in material if not str(Path(path)).startswith(network))
    return list(dict.fromkeys(folder for folder in parents if not str(folder).startswith(network)
                              and folder.parent != folder and not _HOME.is_relative_to(folder)
                              and not (os.name == "nt" and set(str(folder)) & set("&|<>^%"))
                              and not folder.is_relative_to(REPO_ROOT)))


# Claude Code: only the read tools exist for the run, and the web's when it may search. It reads in its working
# directories, the repository and the folders added, without asking, and every read outside them is blocked; no
# read tool is allowed outright, as that would allow it anywhere. Anything else is refused rather than asked, no
# .env file is read, the creator's hooks do not run, and no MCP server (which could write) is loaded.
def _claude_args(search: bool, folders: Sequence[Path]) -> tuple[str, ...]:
    tools = "Read,Glob,Grep" + (",WebSearch,WebFetch" if search else "")
    web = ("--allowedTools", "WebSearch,WebFetch") if search else ()
    added = ("--add-dir", *map(str, folders)) if folders else ()  # it takes a list: a flag follows
    settings = {"permissions": {"blockReadsOutsideWorkingDirectories": True}, "disableAllHooks": True}
    return ("-p", "--tools", tools, *web, *added,
            "--disallowedTools", "Read(//**/.env),Read(//**/.env.*),Read(//**/*.env),Read(//**/*.env.*),"
                                 "Read(//**/.envrc)",
            "--permission-mode", "dontAsk", "--settings", json.dumps(settings),
            "--strict-mcp-config", "--no-session-persistence")


# OpenCode's own plan agent may still run a shell, so the run gets its own agent that may only read, and search
# when it may. Outside the repository it may read only the folders of the video's files. It has no grep, which
# shows each matching line, a .env file's too, with no read rule applied; it still lists, globs and reads.
def _opencode_env(search: bool, folders: Sequence[Path]) -> dict[str, str]:
    web = "allow" if search else "deny"
    outside = {"*": "deny"} | {str(folder) + os.sep + "*": "allow" for folder in folders}  # the last match wins
    agent = {"agent": {"frameflow": {
        "mode": "primary",
        "description": "Answers Frameflow's requests. Reads and searches; writes nothing and runs nothing.",
        "permission": {"*": "deny", "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny", "*.envrc": "deny"},
                       "grep": "deny", "glob": "allow", "list": "allow", "webfetch": web, "websearch": web,
                       "external_directory": outside},
    }}}
    return {"OPENCODE_CONFIG_CONTENT": json.dumps(agent)}


AGENTS = (
    Agent("claude", "Claude Code", "claude", _claude_args),
    # Its errors logged to stderr: a model call that failed is read there, as OpenCode does not exit after it.
    Agent("opencode", "OpenCode", "opencode",
          lambda search, folders: ("run", "--agent", "frameflow", "--print-logs", "--log-level", "ERROR"),
          _opencode_env),
)


def found_agents() -> list[dict]:
    """Each agent, whether it is on PATH, and the version it gives."""
    found = []
    for agent in AGENTS:
        path = shutil.which(agent.command)
        version = None
        if path:
            try:
                done = subprocess.run([path, "--version"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=VERSION_TIMEOUT)
                match = re.search(r"\d+(?:\.\d+)+", done.stdout)
                version = match.group() if match else None
            except (OSError, subprocess.TimeoutExpired):
                pass
        found.append({"id": agent.id, "name": agent.name, "found": path is not None, "version": version})
    return found


# An agent's last line when it stopped for want of a sign-in. At a word's start, so "catalog index" is not one;
# "log in" only as a request, so "the log in C:/tmp" is not either.
_SIGN_IN = re.compile(r"\b(sign in|sign-in|signed in|login|logged in|please log in\b|log in (?:to|first|again)\b"
                      r"|authenticat|credential|api[- ]?key)", re.I)

# OpenCode's log line when its model call failed, and the error in it; then the words of one out of use.
_ERROR_FIELD = re.compile(r'error\.error="((?:[^"\\]|\\.)*)"')
_OUT_OF_USE = re.compile(r"usage limit|hit your limit|credit|quota|subscribe", re.I)


def _stopped(name: str, said: str) -> str:
    """The line for the creator when an agent stopped, in its own words; one out of its usage says where to go."""
    return _line(f"{name} stopped: {said}") + (
        " Add credit, or choose another way in Settings." if _OUT_OF_USE.search(said) else "")


def _model_error(name: str, line: str) -> str | None:
    """The line for the creator when a log line says the model call failed, in the agent's own words."""
    if "level=ERROR" not in line or "stream error" not in line:
        return None
    found = _ERROR_FIELD.search(line)
    return _stopped(name, (found[1] if found else line).removeprefix("AI_APICallError: "))


def _answer_rule(schema: dict, search: bool) -> str:
    return ("## How to answer\n\n"
            "Write nothing and run nothing: Frameflow checks your answer and writes the files itself. "
            f"You may read files{' and look things up on the web' if search else ''}.\n\n"
            "End your final message with the answer: one ```json block holding a JSON object that "
            "matches this schema.\n\n```json\n" + json.dumps(schema) + "\n```\n")


class AgentThinker:
    can_search = True

    def __init__(self, agent: Agent, command: list[str] | None = None, timeout: float = AGENT_TIMEOUT):
        self.agent = agent
        self.name = agent.name
        self.can_see = agent.id == "claude"     # Claude Code reads images; OpenCode depends on its model
        self.command = command
        self.timeout = timeout

    def answer(self, system: str, request: str, schema: dict, check, *, search: bool = False,
               material: Sequence[Path] = ()) -> dict:
        rule = _answer_rule(schema, search)
        return _fix_rounds(self.name, lambda s, r: self._run(f"{s}\n\n{r}\n\n{rule}", search, material),
                           system, request, schema, check)

    def _run(self, prompt: str, search: bool, material: Sequence[Path]) -> str:
        """One run of the agent: a fix round is a new run, so it remembers nothing."""
        command = self.command or [shutil.which(self.agent.command) or self.agent.command]
        folders = _folders(material)
        # An agent needs no key.
        env = {k: v for k, v in os.environ.items() if k != "FRAMEFLOW_KEY"} | self.agent.env(search, folders)
        try:
            # Its own process group off Windows, so a timeout can stop everything it started.
            process = subprocess.Popen([*command, *self.agent.args(search, folders)], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding="utf-8", errors="replace", cwd=REPO_ROOT, env=env,
                                       start_new_session=os.name != "nt")
        except FileNotFoundError:
            raise ThinkError(f"{self.name} was not found on this PC. Install it, or choose another "
                             f"way to think in Settings.") from None
        # Its stderr is a thread's alone, read as it comes; communicate goes on feeding stdin and reading stdout.
        errors, process.stderr, logged, failed = process.stderr, None, [], []

        def watch() -> None:
            with errors:
                for line in errors:
                    logged.append(line)
                    if not failed and (error := _model_error(self.name, line)):
                        failed.append(error)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        deadline, given, out = time.monotonic() + self.timeout, prompt, None
        while not failed and (out is None or watcher.is_alive()):
            if time.monotonic() > deadline:
                _stop_tree(process)
                raise ThinkError(f"{self.name} took longer than {self.timeout / 60:g} minutes, so it was stopped.")
            if out is None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    out = process.communicate(given, timeout=SLICE)[0]
                given = None  # sent once: communicate goes on feeding it
            else:
                watcher.join(SLICE)
        if failed:  # its model refused, and it may sit on after that
            _stop_tree(process)
            raise ThinkError(failed[0])
        if process.returncode != 0:
            said = ("".join(logged).strip() or out.strip()).splitlines()
            if said and _SIGN_IN.search(said[-1]):
                raise ThinkError(f"{self.name} is not signed in. Sign in to it, or choose another way in Settings.")
            raise ThinkError(_stopped(self.name, said[-1] if said else "it gave no reason."))
        return out


def _stop_tree(process: subprocess.Popen) -> None:
    """Stop an agent and everything it started.

    Killing only the child is not enough: an npm .cmd shim (OpenCode) leaves node holding
    the pipes, and reading them would then wait until node finished on its own.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        with contextlib.suppress(OSError):  # the group may have ended already
            os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):  # one that escaped the tree is not waited for
        process.communicate(timeout=5)


# --- a key -----------------------------------------------------------------------------

SERVICES = ("anthropic", "openai", "openrouter", "gemini", "custom")
_SERVICE_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI", "openrouter": "OpenRouter", "gemini": "Gemini"}
_ADDRESSES = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

ANSWER_TOOL = "submit_answer"
ANSWER_TOOL_DESCRIPTION = ("Send the answer. It is checked; if anything is wrong you get the problems "
                           "back to fix before sending it again.")


def _plain(e: Exception, service: str) -> str:
    """What went wrong with a service, in one line, without a traceback."""
    status = getattr(e, "status_code", None)
    words = str(e).lower()
    if status in (401, 403):
        return f"{service} refused the key. Check it in Settings."
    if status == 402 or "credit" in words or "quota" in words:
        return f"The {service} account is out of credit. Add credit, or choose another way in Settings."
    if type(e).__name__ == "APITimeoutError":
        return f"{service} took too long to answer."
    if type(e).__name__ == "APIConnectionError":
        return f"{service} could not be reached. Check the connection and the address."
    return f"{service} failed: {e}"


class KeyThinker:
    def __init__(self, service: str, key: str, model: str | None = None, base_url: str | None = None):
        if service not in SERVICES:
            raise ThinkError(f"Choose a service for the key in Settings: {', '.join(SERVICES)}.")
        if service == "custom" and not base_url:
            raise ThinkError("Type the custom service's address in Settings.")
        self.label = _SERVICE_NAMES.get(service) or base_url
        self.key = key
        self.can_search = service == "anthropic"
        self.can_see = False     # a request is text: no image reaches the model this way yet
        if not key and service != "custom":  # a local server may need none
            raise ThinkError(f"Add your {self.label} key in Settings.")
        if service == "anthropic":
            from project.providers.anthropic_provider import AnthropicProvider
            self.provider = AnthropicProvider(model=model, api_key=key)
        else:
            if not model:
                raise ThinkError(f"Choose a model for {self.label} in Settings.")
            from project.providers.openai_provider import OpenAICompatibleProvider
            self.provider = OpenAICompatibleProvider(model=model, base_url=_ADDRESSES.get(service, base_url),
                                                     api_key=key)
        self.name = f"{self.label} ({self.provider.model})"

    def answer(self, system: str, request: str, schema: dict, check, *, search: bool = False,
               material: Sequence[Path] = ()) -> dict:
        last: list[str] = []

        def checked(answer: dict) -> list[str]:
            last[:] = _problems(answer, schema, check)
            return last

        tool_schema = {k: v for k, v in schema.items() if k not in ("$schema", "$id", "title", "description")}
        tool = ToolSpec(ANSWER_TOOL, ANSWER_TOOL_DESCRIPTION, tool_schema)
        options = {"web_search": search} if self.can_search else {}  # only Anthropic's provider can search
        try:
            return self.provider.submit(system, request, tool, checked, MAX_FIX_ROUNDS + 1, **options)
        except Exception as e:  # nothing from an SDK may reach the creator raw: it can echo the key
            # Redacted before it is cut to one line, so no short piece of the key is left at the cut.
            if isinstance(e, ProviderError) and "valid submission" in str(e):  # out of attempts
                said = (_still_wrong(self.name, last) if last
                        else f"{self.name} gave no answer after {MAX_FIX_ROUNDS + 1} tries.")
                raise ThinkError(_line(redact(said, self.key))) from None
            raise ThinkError(_line(redact(_plain(e, self.label), self.key))) from None


# --- the stand-in, for tests -------------------------------------------------------------

class StandInThinker:
    """Scripted answers, in order, across calls. A str stands for an agent's broken output."""
    name = "Stand-in thinker"

    def __init__(self, answers: list[dict | str], can_search: bool = True, can_see: bool = False):
        self.answers = list(answers)
        self.can_search = can_search
        self.can_see = can_see
        self.asked: list[tuple[str, str]] = []
        self.material: list[list[Path]] = []

    def answer(self, system: str, request: str, schema: dict, check, *, search: bool = False,
               material: Sequence[Path] = ()) -> dict:
        self.material.append(list(material))
        return _fix_rounds(self.name, self._next, system, request, schema, check)

    def _next(self, system: str, request: str):
        self.asked.append((system, request))
        if not self.answers:
            raise ThinkError("The stand-in thinker has no answers left.")
        return self.answers.pop(0)


# --- choosing ----------------------------------------------------------------------------

def thinker_from_env(env: Mapping[str, str] = os.environ) -> Thinker:
    choice = env.get("FRAMEFLOW_THINKER") or "auto"
    if choice.startswith("standin:"):  # for tests only: the answers are a list in the JSON file named
        return StandInThinker(json.loads(Path(choice.removeprefix("standin:")).read_text(encoding="utf-8")))
    if choice == "key":
        return KeyThinker(env.get("FRAMEFLOW_SERVICE", ""), env.get("FRAMEFLOW_KEY", ""),
                          env.get("FRAMEFLOW_MODEL") or None, env.get("FRAMEFLOW_BASE_URL") or None)
    if choice == "auto":
        found = next((a["id"] for a in found_agents() if a["found"]), None)
        if found is None:
            raise ThinkError("No agent was found on this PC. Choose one, or add an API key, in Settings.")
        choice = f"agent:{found}"
    agent = next((a for a in AGENTS if f"agent:{a.id}" == choice), None)
    if agent is None:
        raise ThinkError(f"Frameflow does not know the thinker {choice!r}. Choose one in Settings.")
    return AgentThinker(agent)
