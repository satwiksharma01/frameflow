"""The thinker: an agent or an API key that answers a request, checked by Frameflow.

No test runs a real agent or calls a model. A stand-in thinker gives scripted
answers, a fake agent script (this Python, printing scripted outputs) stands in
for Claude Code and OpenCode, and fake SDK clients stand in for the services.
"""
import contextlib
import io
import json
import os
import platform
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from project import app_think, thinkers
from project.thinkers import (AGENTS, MAX_FIX_ROUNDS, Agent, AgentThinker, KeyThinker,
                              StandInThinker, ThinkError, found_agents, redact,
                              thinker_from_env)

KEY = "sk-test-0123456789abcdef"
SCHEMA = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}


def accept(answer):
    return []


def refuse_zero(answer):
    return ["a must not be 0"] if answer["a"] == 0 else []


def block(answer: str) -> str:
    return "```json\n" + answer + "\n```"


# Each run prints the next scripted output, and keeps what it was asked and how it was run.
FAKE_AGENT = """import json, os, sys
from pathlib import Path
here = Path(__file__).parent
count = here / "count"
n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
(here / f"asked-{n}.txt").write_bytes(sys.stdin.buffer.read())
(here / f"run-{n}.json").write_text(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                                                "config": os.environ.get("OPENCODE_CONFIG_CONTENT"),
                                                "key": os.environ.get("FRAMEFLOW_KEY")}))
sys.stdout.write(json.loads((here / "outputs.json").read_text(encoding="utf-8"))[n])
"""


class TestFixRounds(unittest.TestCase):
    def test_an_answer_the_check_accepts_is_returned(self):
        thinker = StandInThinker([{"a": 1}])
        self.assertEqual(thinker.answer("system", "request", SCHEMA, accept), {"a": 1})
        self.assertEqual(thinker.asked, [("system", "request")])

    def test_problems_go_back_for_a_fix_round(self):
        thinker = StandInThinker([{"a": 0}, {"a": 1}])
        self.assertEqual(thinker.answer("system", "request", SCHEMA, refuse_zero), {"a": 1})
        self.assertEqual(len(thinker.asked), 2)
        self.assertIn("a must not be 0", thinker.asked[1][1])
        self.assertIn("request", thinker.asked[1][1])

    def test_a_schema_failure_gets_a_fix_round_before_the_check(self):
        thinker = StandInThinker([{"a": "one"}, {"a": 1}])
        self.assertEqual(thinker.answer("system", "request", SCHEMA, refuse_zero), {"a": 1})
        self.assertIn("is not of type 'integer'", thinker.asked[1][1])

    def test_after_three_fix_rounds_it_stops_with_what_is_still_wrong(self):
        seen = []

        def still_wrong(answer):
            seen.append(answer)
            return [f"problem {len(seen)}"]

        thinker = StandInThinker([{"a": 0}] * 4)
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, still_wrong)
        self.assertEqual(len(thinker.asked), MAX_FIX_ROUNDS + 1)
        self.assertIn("problem 4", str(caught.exception))
        self.assertNotIn("\n", str(caught.exception))


class TestAgentThinker(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        (self.dir / "agent.py").write_text(FAKE_AGENT, encoding="utf-8")

    def agent(self, outputs, agent=Agent("fake", "Fake agent", "fake")):
        (self.dir / "outputs.json").write_text(json.dumps(outputs), encoding="utf-8")
        return AgentThinker(agent, command=[sys.executable, str(self.dir / "agent.py")])

    def asked(self, n):
        return (self.dir / f"asked-{n}.txt").read_text(encoding="utf-8")

    def test_an_agents_answer_is_its_last_json_block(self):
        thinker = self.agent(["Looking at the files.\n" + block('{"a": 0}') + "\nOn second thought:\n"
                              + block('{"a": 1}') + "\nDone."])
        self.assertEqual(thinker.answer("system", "request", SCHEMA, accept), {"a": 1})
        self.assertIn("request", self.asked(0))

    def test_an_agent_with_no_json_block_gets_a_fix_round(self):
        thinker = self.agent(["I could not decide.", block('{"a": 1}')])
        self.assertEqual(thinker.answer("system", "request", SCHEMA, accept), {"a": 1})
        self.assertIn("json block", self.asked(1))

    def test_broken_json_gets_a_fix_round(self):
        thinker = self.agent([block('{"a": '), block('{"a": 1}')])
        self.assertEqual(thinker.answer("system", "request", SCHEMA, accept), {"a": 1})
        self.assertIn("could not be read", self.asked(1))

    def test_an_agent_not_found_says_so_in_one_line(self):
        thinker = AgentThinker(AGENTS[0], command=["frameflow-no-such-agent"])
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, accept)
        message = str(caught.exception)
        self.assertIn("Claude Code", message)
        self.assertIn("not found", message)
        self.assertNotIn("\n", message)

    def stops(self, line: str) -> str:
        """What the creator reads when the agent exits 1 having said `line` last."""
        (self.dir / "stops.py").write_text(
            "import sys\nsys.stdin.read()\nprint('Starting.', file=sys.stderr)\n"
            "print(sys.argv[1], file=sys.stderr)\nsys.exit(1)\n", encoding="utf-8")
        thinker = AgentThinker(Agent("fake", "Fake agent", "fake"),
                               command=[sys.executable, str(self.dir / "stops.py"), line])
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, accept)
        return str(caught.exception)

    def test_an_agent_that_is_not_signed_in_points_to_settings(self):
        for line in ("Invalid API key - Please run /login", "You are not signed in",
                     "Error: Please sign in to continue", "Sign-in required", "Please log in first", "Please log in",
                     "You are not logged in.", "Not authenticated", "Failed to authenticate with the server",
                     "Authentication failed", "authentication_error", "invalid x-api-key", "No credentials found"):
            with self.subTest(line):
                self.assertEqual(self.stops(line),
                                 "Fake agent is not signed in. Sign in to it, or choose another way in Settings.")
        # Any other stop says the agent's own last line: a log, or "catalog index", is no sign-in.
        for line in ("Error: the catalog index is out of date", "See the log in C:/tmp/log for details",
                     "Log information was written"):
            with self.subTest(line):
                self.assertEqual(self.stops(line), f"Fake agent stopped: {line}")

    def test_an_agent_that_overruns_is_stopped_with_everything_it_started(self):
        # As an npm .cmd shim does: the child starts a grandchild that holds the output pipes.
        (self.dir / "slow.py").write_text(
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(15)'], stdout=sys.stdout, stderr=sys.stderr)\n"
            "time.sleep(15)\n", encoding="utf-8")
        thinker = AgentThinker(Agent("slow", "Slow agent", "slow"),
                               command=[sys.executable, str(self.dir / "slow.py")], timeout=1)
        started = time.monotonic()
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, accept)
        self.assertLess(time.monotonic() - started, 8)
        self.assertIn("Slow agent took longer than", str(caught.exception))

    def logs(self, lines: list[str], answer: str = "", sleep: float = 0) -> AgentThinker:
        """An agent that reads its request, logs `lines` to stderr as OpenCode does, answers, then sleeps."""
        (self.dir / "log.json").write_text(json.dumps({"lines": lines, "answer": answer, "sleep": sleep}),
                                           encoding="utf-8")
        (self.dir / "logs.py").write_text(
            "import json, sys, time\nfrom pathlib import Path\nsys.stdin.read()\n"
            "log = json.loads((Path(__file__).parent / 'log.json').read_text(encoding='utf-8'))\n"
            "for line in log['lines']:\n    print(line, file=sys.stderr, flush=True)\n"
            "sys.stdout.write(log['answer'])\ntime.sleep(log['sleep'])\n", encoding="utf-8")
        return AgentThinker(Agent("fake", "Fake agent", "fake"), command=[sys.executable, str(self.dir / "logs.py")],
                            timeout=30)

    def test_a_model_error_in_the_log_stops_the_agent_at_once_in_its_own_words(self):
        # OpenCode sits on after its model call failed: it is stopped there, not at the timeout.
        line = ('timestamp=2026-11-18T08:14:39.358Z level=ERROR run=e9b6bc6b message="stream error" '
                'providerID=opencode modelID=big-pickle session.id=ses_1 small=false agent=frameflow mode=primary '
                'error.error="AI_APICallError: {}"')
        limit = ("Free usage limit reached. Free models work in OpenCode (https://opencode.ai); "
                 "subscribe to OpenCode Go to keep going: https://opencode.ai/go")
        for error, said in ((limit, f"Fake agent stopped: {limit} Add credit, or choose another way in Settings."),
                            ("The model is overloaded", "Fake agent stopped: The model is overloaded")):
            with self.subTest(error):
                thinker = self.logs([line.format(error)], sleep=60)
                started = time.monotonic()
                with self.assertRaises(ThinkError) as caught:
                    thinker.answer("system", "request", SCHEMA, accept)
                self.assertLess(time.monotonic() - started, 10)
                self.assertEqual(str(caught.exception), said)

    def test_a_log_line_at_another_level_is_not_a_failure(self):
        # Many of them, more than a pipe holds, while the answer is still to come.
        thinker = self.logs(['timestamp=2026-11-18T08:14:39Z level=WARN message="stream error" error.error="retrying"']
                            * 3000, block('{"a": 1}'))
        self.assertEqual(thinker.answer("system", "request " * 20000, SCHEMA, accept), {"a": 1})

    def test_each_agent_runs_in_the_repository_and_may_not_write(self):
        claude, opencode = AGENTS
        with mock.patch.dict("os.environ", {"FRAMEFLOW_KEY": KEY}):
            self.agent([block('{"a": 1}')], claude).answer("system", "request", SCHEMA, accept)
        run = json.loads((self.dir / "run-0.json").read_text())
        self.assertEqual(Path(run["cwd"]), thinkers.REPO_ROOT)
        self.assertIsNone(run["key"])
        tools = run["argv"][run["argv"].index("--tools") + 1].split(",")
        self.assertEqual(set(tools), {"Read", "Glob", "Grep"})
        self.assertNotIn("--print-logs", run["argv"])

        (self.dir / "count").unlink()
        self.agent([block('{"a": 1}')], opencode).answer("system", "request", SCHEMA, accept)
        run = json.loads((self.dir / "run-0.json").read_text())
        # Its errors are logged to stderr, where a model's refusal is read as it comes.
        self.assertEqual(run["argv"][-3:], ["--print-logs", "--log-level", "ERROR"])
        name = run["argv"][run["argv"].index("--agent") + 1]
        permission = json.loads(run["config"])["agent"][name]["permission"]
        self.assertEqual(next(iter(permission.items())), ("*", "deny"))
        self.assertNotIn("edit", permission)
        self.assertNotIn("bash", permission)

    def ran(self, agent: Agent, search: bool, material=()) -> dict:
        """How the fake agent was run, standing in for `agent`, for one answer with or without the web."""
        with contextlib.suppress(FileNotFoundError):
            (self.dir / "count").unlink()
        self.agent([block('{"a": 1}')], agent).answer("system", "request", SCHEMA, accept, search=search,
                                                      material=material)
        return json.loads((self.dir / "run-0.json").read_text())

    def test_an_agent_has_the_web_only_when_it_may_search(self):
        # Only a pitch's plan looks facts up; an agent reading untrusted pages and material sends nothing out.
        claude, opencode = AGENTS
        for search, web in ((False, set()), (True, {"WebSearch", "WebFetch"})):
            with self.subTest(search=search):
                argv = self.ran(claude, search)["argv"]
                self.assertEqual(set(argv[argv.index("--tools") + 1].split(",")), {"Read", "Glob", "Grep"} | web)
                self.assertEqual("look things up on the web" in self.asked(0), search)
                run = self.ran(opencode, search)
                name = run["argv"][run["argv"].index("--agent") + 1]
                permission = json.loads(run["config"])["agent"][name]["permission"]
                said = "allow" if search else "deny"
                self.assertEqual((permission["webfetch"], permission["websearch"]), (said, said))
                self.assertEqual("look things up on the web" in self.asked(0), search)

    def test_claude_code_reads_the_repository_and_the_picked_folders_only(self):
        # The repository is its working directory and each picked folder is added; any other read is refused.
        folders = [Path("D:/clips"), Path("C:/Users/x/My Videos/Ränge")]
        for search in (False, True):
            with self.subTest(search=search):
                args = thinkers._claude_args(search, folders)
                at = args.index("--add-dir")
                self.assertEqual(args[at + 1:at + 3], tuple(map(str, folders)))
                self.assertTrue(args[at + 3].startswith("--"))      # --add-dir takes a list
                self.assertNotIn("--add-dir", thinkers._claude_args(search, []))
                settings = json.loads(args[args.index("--settings") + 1])
                self.assertEqual(settings["permissions"], {"blockReadsOutsideWorkingDirectories": True})
                self.assertIs(settings["disableAllHooks"], True)
                # A Read allowed there would be allowed anywhere; reads in the working directories need no asking.
                if search:
                    self.assertEqual(args[args.index("--allowedTools") + 1], "WebSearch,WebFetch")
                else:
                    self.assertNotIn("--allowedTools", args)
        argv = self.ran(AGENTS[0], False, [self.dir / "clips" / "a.mp4"])["argv"]
        self.assertEqual(argv[argv.index("--add-dir") + 1], str((self.dir / "clips").resolve()))

    def test_opencode_reads_the_repository_and_the_picked_folders_only(self):
        folders = [Path("D:/clips"), Path("C:/Users/x/My Videos/Ränge")]
        config = json.loads(thinkers._opencode_env(False, folders)["OPENCODE_CONFIG_CONTENT"])
        # In order: the last rule that matches wins.
        self.assertEqual(list(config["agent"]["frameflow"]["permission"]["external_directory"].items()),
                         [("*", "deny")] + [(str(folder) + os.sep + "*", "allow") for folder in folders])
        # Its grep shows each matching line, .env files' too, with no read rule applied.
        self.assertEqual(config["agent"]["frameflow"]["permission"]["grep"], "deny")
        run = self.ran(AGENTS[1], False, [self.dir / "clips" / "a.mp4"])
        self.assertEqual(json.loads(run["config"])["agent"]["frameflow"]["permission"]["external_directory"],
                         {"*": "deny", str((self.dir / "clips").resolve()) + os.sep + "*": "allow"})

    def test_env_files_are_refused_to_both_agents(self):
        for search in (False, True):
            with self.subTest(search=search):
                args = thinkers._claude_args(search, [])
                self.assertLessEqual({"Read(//**/.env)", "Read(//**/.env.*)", "Read(//**/*.env)", "Read(//**/.envrc)",
                                      "Read(//**/*.env.*)"},        # prod.env.local too
                                     set(args[args.index("--disallowedTools") + 1].split(",")))
                config = json.loads(thinkers._opencode_env(search, [])["OPENCODE_CONFIG_CONTENT"])
                read = config["agent"]["frameflow"]["permission"]["read"]
                self.assertEqual(next(iter(read.items())), ("*", "allow"))     # first, so each refusal wins
                self.assertEqual((read["*.env"], read["*.env.*"], read["*.envrc"]), ("deny",) * 3)

    def test_the_folders_an_agent_may_read(self):
        with self.subTest("two folders"):
            files = [self.dir / ("music" if n % 2 else "clips") / f"{n}.mp4" for n in range(30)]
            self.assertEqual(thinkers._folders(files), [(self.dir / "clips").resolve(), (self.dir / "music").resolve()])
        with self.subTest("inside the repository"):
            self.assertEqual(thinkers._folders([thinkers.REPO_ROOT / "output" / "video" / "a.mp4"]), [])
        with self.subTest("a drive's root"):     # it would open the whole drive
            paths = ["/a.mp4"] + (["D:/a.mp4"] if os.name == "nt" else [])
            self.assertEqual(thinkers._folders([Path(path) for path in paths]), [])
        with self.subTest("the home folder"):    # it would open ~/.ssh and the rest
            self.assertEqual(thinkers._folders([Path.home() / "a.mp4", Path.home().parent / "a.mp4"]), [])
            videos = Path.home() / "Videos"
            self.assertEqual(thinkers._folders([videos / "a.mp4"]), [videos.resolve()])
        with self.subTest("a name cmd.exe reads as commands"):     # it runs an npm install of Claude Code
            if os.name != "nt":
                self.skipTest("cmd.exe is Windows' own")
            self.assertEqual(thinkers._folders([self.dir / name / "a.mp4" for name in ("R&D", "50%", "x^y")]), [])
        # Spotted before it is resolved, which would look the server up.
        with self.subTest("a network path"), mock.patch.object(Path, "resolve", side_effect=AssertionError("resolved")):
            paths = ["//server/share/a.mp4"] + ([r"\\server\share\a.mp4"] if os.name == "nt" else [])
            self.assertEqual(thinkers._folders([Path(path) for path in paths]), [])

    def test_an_agent_out_of_its_usage_points_to_settings(self):
        for line in ("Claude AI usage limit reached|1763510400", "Credit balance is too low",
                     "Error: You exceeded your current quota",
                     "You've hit your limit - resets 3:30pm (Asia/Kolkata)"):
            with self.subTest(line):
                self.assertEqual(self.stops(line),
                                 f"Fake agent stopped: {line} Add credit, or choose another way in Settings.")


# --- a key: fake SDK clients, shaped like the Anthropic SDK's beta stream ---

PAUSE = "pause"      # a web search that paused its own loop
NOTHING = "nothing"  # a turn with text only, and no answer


class _FakeClaude:
    def __init__(self, *outcomes):
        self.outcomes, self.requests = list(outcomes), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome == PAUSE:
            content, stop = [SimpleNamespace(type="server_tool_use", id="s1", name="web_search", input={})], "pause_turn"
        elif outcome == NOTHING:
            content, stop = [SimpleNamespace(type="text", text="Let me think.")], "end_turn"
        else:
            content = [SimpleNamespace(type="tool_use", id=f"t{len(self.requests)}",
                                       name=request["tools"][0]["name"], input=outcome)]
            stop = "tool_use"
        final = SimpleNamespace(content=content, stop_reason=stop, model="claude-opus-5", stop_details=None)
        return contextlib.nullcontext(SimpleNamespace(get_final_message=lambda: final))


class TestKeyThinker(unittest.TestCase):
    def claude(self, *outcomes):
        client = _FakeClaude(*outcomes)
        with mock.patch("anthropic.Anthropic", return_value=client) as made:
            thinker = KeyThinker("anthropic", KEY)
        made.assert_called_once_with(api_key=KEY)
        return thinker, client

    def test_a_key_never_appears_in_an_error(self):
        thinker, _ = self.claude(RuntimeError(f"401 for {KEY}: invalid x-api-key ...{KEY[8:]}"))
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, accept)
        message = str(caught.exception)
        self.assertNotIn(KEY, message)
        self.assertNotIn("0123456789", message)
        self.assertNotIn("\n", message)

    def test_an_account_out_of_credit_points_to_settings(self):
        thinker, _ = self.claude(RuntimeError("Your credit balance is too low to access the Anthropic API."))
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, accept)
        self.assertEqual(str(caught.exception),
                         "The Anthropic account is out of credit. Add credit, or choose another way in Settings.")

    def test_redact_hides_the_key_and_any_long_run_of_it(self):
        self.assertEqual(redact(f"key {KEY}, part {KEY[5:15]}, short {KEY[:4]}", KEY), "key …, part …, short sk-t")
        self.assertEqual(redact("nothing to hide", None), "nothing to hide")

    def test_a_key_thinker_stops_with_what_is_still_wrong(self):
        thinker, client = self.claude(*[{"a": 0}] * (MAX_FIX_ROUNDS + 1))
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, refuse_zero)
        self.assertIn("a must not be 0", str(caught.exception))
        self.assertEqual(len(client.requests), MAX_FIX_ROUNDS + 1)

    def test_only_an_anthropic_key_can_search(self):
        thinker, client = self.claude(PAUSE, {"a": 1})
        self.assertTrue(thinker.can_search)
        self.assertEqual(thinker.answer("system", "request", SCHEMA, accept, search=True), {"a": 1})
        self.assertIn({"type": "web_search_20260209", "name": "web_search"}, client.requests[0]["tools"])
        # A paused search turn is sent back as it is, with no nudge after it.
        self.assertEqual(client.requests[1]["messages"][-1]["role"], "assistant")

        with mock.patch("openai.OpenAI"):
            for service in ("openai", "openrouter", "gemini", "custom"):
                self.assertFalse(KeyThinker(service, KEY, "some-model", "http://localhost:11434/v1").can_search)

    def test_the_search_tool_is_sent_only_when_asked(self):
        thinker, client = self.claude({"a": 1}, {"a": 1})
        thinker.answer("system", "request", SCHEMA, accept)
        # It takes the material as every thinker does, and ignores it.
        thinker.answer("system", "request", SCHEMA, accept, search=True, material=[Path("D:/clips/a.mp4")])
        searches = [[t for t in r["tools"] if t.get("name") == "web_search"] for r in client.requests]
        self.assertEqual([len(s) for s in searches], [0, 1])
        # Agents and the stand-in take it too, and ignore it.
        self.assertEqual(StandInThinker([{"a": 1}]).answer("system", "request", SCHEMA, accept, search=True), {"a": 1})

    def test_paused_searches_do_not_use_up_fix_rounds(self):
        thinker, client = self.claude(PAUSE, PAUSE, PAUSE, PAUSE, {"a": 0}, {"a": 0}, {"a": 0}, {"a": 1})
        self.assertEqual(thinker.answer("system", "request", SCHEMA, refuse_zero, search=True), {"a": 1})
        self.assertEqual(len(client.requests), 8)

    def test_endless_pauses_are_stopped(self):
        from project.providers.anthropic_provider import MAX_PAUSES
        thinker, client = self.claude(*[PAUSE] * (MAX_PAUSES + 1))
        with self.assertRaises(ThinkError):
            thinker.answer("system", "request", SCHEMA, accept, search=True)
        self.assertEqual(len(client.requests), MAX_PAUSES + 1)

    def test_a_key_that_never_answers_says_so_plainly(self):
        thinker, _ = self.claude(*[NOTHING] * (MAX_FIX_ROUNDS + 1))
        with self.assertRaises(ThinkError) as caught:
            thinker.answer("system", "request", SCHEMA, accept)
        self.assertEqual(str(caught.exception), f"Anthropic (claude-opus-5) gave no answer after {MAX_FIX_ROUNDS + 1} tries.")

    def test_service_addresses(self):
        addresses = {
            "openrouter": "https://openrouter.ai/api/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "custom": "http://localhost:11434/v1",
        }
        for service, address in addresses.items():
            env = {"FRAMEFLOW_THINKER": "key", "FRAMEFLOW_SERVICE": service, "FRAMEFLOW_MODEL": "some-model",
                   "FRAMEFLOW_BASE_URL": "http://localhost:11434/v1", "FRAMEFLOW_KEY": KEY}
            with mock.patch("openai.OpenAI") as made:
                thinker = thinker_from_env(env)
            made.assert_called_once_with(api_key=KEY, base_url=address)
            self.assertIn("some-model", thinker.name)


class TestChoosingAThinker(unittest.TestCase):
    def agents(self, *found):
        return [{"id": a.id, "name": a.name, "found": f, "version": "1.0" if f else None}
                for a, f in zip(AGENTS, found)]

    def test_auto_picks_the_first_agent_found(self):
        with mock.patch("project.thinkers.found_agents", return_value=self.agents(True, True)):
            self.assertEqual(thinker_from_env({}).name, "Claude Code")
        with mock.patch("project.thinkers.found_agents", return_value=self.agents(False, True)):
            self.assertEqual(thinker_from_env({"FRAMEFLOW_THINKER": "auto"}).name, "OpenCode")

    def test_auto_with_no_agent_asks_for_one(self):
        with mock.patch("project.thinkers.found_agents", return_value=self.agents(False, False)):
            with self.assertRaises(ThinkError) as caught:
                thinker_from_env({"FRAMEFLOW_THINKER": "auto"})
        self.assertEqual(str(caught.exception),
                         "No agent was found on this PC. Choose one, or add an API key, in Settings.")

    def test_an_agent_can_be_chosen_by_name(self):
        self.assertEqual(thinker_from_env({"FRAMEFLOW_THINKER": "agent:opencode"}).name, "OpenCode")

    def test_found_agents_gives_each_version(self):
        def which(command):
            return sys.executable if command == "claude" else None

        with mock.patch("project.thinkers.shutil.which", which):
            self.assertEqual(found_agents(), [
                {"id": "claude", "name": "Claude Code", "found": True, "version": platform.python_version()},
                {"id": "opencode", "name": "OpenCode", "found": False, "version": None},
            ])

    def test_a_key_reaches_an_openai_compatible_address_through_the_real_sdk(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                call = {"id": "call_1", "type": "function",
                        "function": {"name": thinkers.ANSWER_TOOL, "arguments": '{"ready": true}'}}
                reply = json.dumps({
                    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "test-model",
                    "choices": [{"index": 0, "finish_reason": "tool_calls",
                                 "message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        env = {"FRAMEFLOW_THINKER": "key", "FRAMEFLOW_SERVICE": "custom",
               "FRAMEFLOW_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
               "FRAMEFLOW_MODEL": "test-model", "FRAMEFLOW_KEY": "made-up-key"}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = app_think.main(["test"], env)
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith("Ready: "))
        self.assertTrue(seen[0]["path"].endswith("/chat/completions"))
        self.assertEqual(seen[0]["auth"], "Bearer made-up-key")
        self.assertEqual(seen[0]["body"]["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
