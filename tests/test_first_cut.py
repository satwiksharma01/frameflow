#!/usr/bin/env python3
"""Milestone 3 tests: transcription parsing, the edit-plan contract, plan -> IR,
and both providers' tool-calling loops.

The provider loops run against fake clients shaped like the SDK objects, so the
retry / error-feedback / fallback logic is covered without spending API calls.

Run with: python -m unittest discover tests
"""
import copy
import json
import unittest
from types import SimpleNamespace

from project.editor_agent import (
    TOOL_NAME,
    NoSpeechError,
    audible_seconds,
    build_agent_request,
    build_tool,
    build_user_prompt,
    check_plan,
    propose_edit_plan,
)
from project.media import choose_cfr_rate
from project.plan_to_ir import edit_plan_to_ir
from project.providers import ProviderError, get_provider
from project.providers.anthropic_provider import AnthropicProvider, _echoable
from project.providers.openai_provider import OpenAICompatibleProvider
from project.transcribe import parse_silencedetect, whisper_json_to_segments
from project.validate import ValidationError, validate

TRANSCRIPT = {
    "source": "C:/media/talk.mp4",
    "duration_seconds": 10.0,
    "language": "en",
    "segments": [
        {"start": 0.0, "end": 2.5, "text": "Hi everyone."},
        {"start": 2.5, "end": 10.0, "text": "Today, today I want to show you something."},
    ],
    "silences": [{"start": 2.6, "end": 5.0}],
}

GOOD_PLAN = {
    "source_duration_seconds": 10.0,
    "decisions": [
        {"action": "keep", "start": 0.0, "end": 2.8, "reason": "greeting"},
        {"action": "remove", "start": 2.8, "end": 4.8, "reason": "long pause"},
        {"action": "keep", "start": 4.8, "end": 10.0, "reason": "main point"},
    ],
}


class TestChooseCfrRate(unittest.TestCase):
    def test_jitter_just_above_a_standard_rate_stays_at_that_rate(self):
        # Measured on real Windows Camera recordings declared as 60 fps.
        for measured in (30.0154, 30.3106, 30.2995):
            self.assertEqual(choose_cfr_rate(measured), 30)

    def test_genuinely_between_rates_rounds_up_so_no_frames_are_dropped(self):
        self.assertEqual(choose_cfr_rate(27.64), 30)  # Game DVR screen capture
        self.assertEqual(choose_cfr_rate(24.8), 25)
        self.assertEqual(choose_cfr_rate(33.0), 50)

    def test_above_the_highest_rate_caps_at_60(self):
        self.assertEqual(choose_cfr_rate(90.0), 60)


class TestTranscriptionParsing(unittest.TestCase):
    def test_whisper_offsets_become_seconds_and_empty_text_is_dropped(self):
        whisper = {"transcription": [
            {"offsets": {"from": 0, "to": 2660}, "text": " Hi everyone."},
            {"offsets": {"from": 2660, "to": 3000}, "text": "   "},
        ]}
        self.assertEqual(whisper_json_to_segments(whisper), [
            {"start": 0.0, "end": 2.66, "text": "Hi everyone."},
        ])

    def test_punctuation_only_segments_are_not_speech(self):
        whisper = {"transcription": [
            {"offsets": {"from": 0, "to": 23400}, "text": " ..."},
            {"offsets": {"from": 0, "to": 2000}, "text": " ."},
        ]}
        self.assertEqual(whisper_json_to_segments(whisper), [])

    def test_silencedetect_pairs_start_and_end(self):
        stderr = (
            "[silencedetect @ 0x1] silence_start: 2.67175\n"
            "[silencedetect @ 0x1] silence_end: 6.589563 | silence_duration: 3.917813\n"
        )
        self.assertEqual(parse_silencedetect(stderr, 30.0), [{"start": 2.672, "end": 6.59}])

    def test_silence_running_to_the_end_is_closed_at_duration(self):
        stderr = "[silencedetect @ 0x1] silence_start: 28.0\n"
        self.assertEqual(parse_silencedetect(stderr, 30.0), [{"start": 28.0, "end": 30.0}])


class TestEditPlanContract(unittest.TestCase):
    def _plan_with(self, decisions):
        plan = copy.deepcopy(GOOD_PLAN)
        plan["decisions"] = decisions
        return plan

    def test_good_plan_is_accepted(self):
        self.assertEqual(check_plan(GOOD_PLAN, TRANSCRIPT), [])

    def test_uncovered_gap_is_rejected(self):
        plan = self._plan_with([
            {"action": "keep", "start": 0.0, "end": 2.8, "reason": "a"},
            {"action": "keep", "start": 5.0, "end": 10.0, "reason": "b"},
        ])
        with self.assertRaisesRegex(ValidationError, "not covered"):
            validate(plan, "edit_plan")

    def test_overlap_is_rejected(self):
        plan = self._plan_with([
            {"action": "keep", "start": 0.0, "end": 6.0, "reason": "a"},
            {"action": "remove", "start": 4.0, "end": 10.0, "reason": "b"},
        ])
        with self.assertRaisesRegex(ValidationError, "overlapping"):
            validate(plan, "edit_plan")

    def test_plan_must_reach_the_end_of_the_source(self):
        plan = self._plan_with([{"action": "keep", "start": 0.0, "end": 8.0, "reason": "a"}])
        with self.assertRaisesRegex(ValidationError, "must end at the source duration"):
            validate(plan, "edit_plan")

    def test_plan_that_keeps_nothing_is_rejected(self):
        plan = self._plan_with([{"action": "remove", "start": 0.0, "end": 10.0, "reason": "a"}])
        with self.assertRaisesRegex(ValidationError, "at least one kept span"):
            validate(plan, "edit_plan")

    def test_wrong_source_duration_is_reported(self):
        plan = copy.deepcopy(GOOD_PLAN)
        plan["source_duration_seconds"] = 12.0
        plan["decisions"][-1]["end"] = 12.0
        self.assertTrue(any("source is 10.0" in p for p in check_plan(plan, TRANSCRIPT)))

    def test_sliver_keep_is_reported(self):
        plan = self._plan_with([
            {"action": "keep", "start": 0.0, "end": 0.05, "reason": "a"},
            {"action": "remove", "start": 0.05, "end": 2.0, "reason": "b"},
            {"action": "keep", "start": 2.0, "end": 10.0, "reason": "c"},
        ])
        self.assertTrue(any("at least 0.1s" in p for p in check_plan(plan, TRANSCRIPT)))

    def test_prompt_includes_measured_silences_and_brief(self):
        prompt = build_user_prompt(TRANSCRIPT, "keep it tight")
        self.assertIn("[2.60-5.00]", prompt)
        self.assertIn("keep it tight", prompt)

    def test_tool_schema_is_the_edit_plan_schema_without_metadata(self):
        tool = build_tool()
        self.assertEqual(tool.name, TOOL_NAME)
        self.assertNotIn("$schema", tool.input_schema)
        self.assertIn("decisions", tool.input_schema["properties"])

    def test_the_editor_is_offered_the_confidence_field(self):
        """Both modes hand the editor this schema, so the field only exists in
        practice if it survives into the tool definition and the request file."""
        decision = build_tool().input_schema["properties"]["decisions"]["items"]
        self.assertEqual(decision["properties"]["confidence"]["enum"], ["high", "low"])
        self.assertNotIn("confidence", decision["required"])
        self.assertEqual(decision["properties"]["action"]["enum"], ["keep", "remove"])


class TestAgentMode(unittest.TestCase):
    """A coding agent (Claude Code, OpenCode, ...) as the editor, no API key."""

    def test_request_carries_guidance_inputs_schema_and_next_step(self):
        from pathlib import Path
        request = build_agent_request(TRANSCRIPT, "keep it tight", Path("out/edit_plan.json"),
                                      'python -m project.first_cut "talk.mp4" --build')
        self.assertIn("place cut points", request.lower())
        self.assertIn("[2.60-5.00]", request)                  # measured silences
        self.assertIn("Today, today I want", request)          # transcript
        self.assertIn("keep it tight", request)                # brief
        self.assertIn("out/edit_plan.json", request)           # where to write
        self.assertIn("--build", request)                      # how to validate
        self.assertIn('"decisions"', request)                  # schema
        self.assertNotIn("submit_edit_plan", request)          # tool mode only
        self.assertIn('"confidence"', request)                 # how to flag doubt

    def test_build_reports_every_problem_for_the_agent_to_fix(self):
        import tempfile
        from pathlib import Path
        from project.first_cut import PlanError, load_plan
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            bad = copy.deepcopy(GOOD_PLAN)
            bad["decisions"] = bad["decisions"][:2]
            (out / "edit_plan.json").write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(PlanError, "needs fixing"):
                load_plan(out, TRANSCRIPT)

            (out / "edit_plan.json").write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(PlanError, "not valid JSON"):
                load_plan(out, TRANSCRIPT)

            (out / "edit_plan.json").write_text(json.dumps(GOOD_PLAN), encoding="utf-8")
            self.assertEqual(load_plan(out, TRANSCRIPT), GOOD_PLAN)

    def test_missing_plan_points_at_the_request(self):
        import tempfile
        from pathlib import Path
        from project.first_cut import PlanError, load_plan
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PlanError, "edit_request.md"):
                load_plan(Path(tmp), TRANSCRIPT)


class _ProviderThatMustNotBeCalled:
    name, model, served_by = "fake", "fake", None

    def submit(self, *args, **kwargs):
        raise AssertionError("the model was called for a recording with no speech")


class TestNoSpeechGate(unittest.TestCase):
    def test_silent_recording_stops_before_the_model_is_called(self):
        # Shape of a real Windows Camera recording with a muted mic: Whisper
        # hallucinated "Thank you." over audio measured as silent end to end.
        silent = {
            "source": "C:/media/silent.mp4",
            "duration_seconds": 16.633,
            "segments": [{"start": 0.0, "end": 16.4, "text": "Thank you."}],
            "silences": [{"start": 0.0, "end": 16.43}],
        }
        with self.assertRaisesRegex(NoSpeechError, "microphone"):
            propose_edit_plan(silent, _ProviderThatMustNotBeCalled())

    def test_transcript_with_no_segments_stops(self):
        empty = {**TRANSCRIPT, "segments": [], "silences": []}
        with self.assertRaises(NoSpeechError):
            propose_edit_plan(empty, _ProviderThatMustNotBeCalled())

    def test_audible_seconds_ignores_silence_past_the_end(self):
        t = {"duration_seconds": 10.0, "silences": [{"start": 8.0, "end": 12.0}]}
        self.assertAlmostEqual(audible_seconds(t), 8.0)


class TestPlanToIR(unittest.TestCase):
    def test_kept_spans_are_laid_end_to_end(self):
        ir = edit_plan_to_ir(GOOD_PLAN, "C:/media/talk.mp4", 1920, 1080, 30, "cfr", "talk",
                             source_duration=10.0)
        clips = ir["tracks"][0]["clips"]
        self.assertEqual([(c["source_in"], c["source_out"]) for c in clips], [(0.0, 2.8), (4.8, 10.0)])
        self.assertEqual([c["timeline_start"] for c in clips], [0.0, 2.8])

    def test_end_slack_beyond_the_source_is_clamped(self):
        plan = copy.deepcopy(GOOD_PLAN)
        plan["decisions"][-1]["end"] = 10.04  # within validation tolerance, past the real end
        ir = edit_plan_to_ir(plan, "C:/media/talk.mp4", 1920, 1080, 30, "cfr", "talk",
                             source_duration=10.0)
        self.assertEqual(ir["tracks"][0]["clips"][-1]["source_out"], 10.0)


# --- Anthropic fakes, shaped like the SDK's beta stream and content blocks ---

def _block(type_, **fields):
    return SimpleNamespace(type=type_, **fields)


def _response(content, stop_reason="tool_use", model="claude-opus-5"):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, stop_details=None)


class _FakeStream:
    def __init__(self, outcome):
        self.outcome = outcome

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _FakeAnthropic:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return _FakeStream(self.outcomes.pop(0))


class TestAnthropicProvider(unittest.TestCase):
    def _submit(self, outcomes, model=None):
        client = _FakeAnthropic(outcomes)
        provider = AnthropicProvider(model=model, client=client)
        result = provider.submit("system", "user", build_tool(),
                                 lambda plan: check_plan(plan, TRANSCRIPT), max_attempts=3)
        return result, client

    def test_invalid_submission_errors_are_fed_back_then_valid_one_returned(self):
        bad = copy.deepcopy(GOOD_PLAN)
        bad["decisions"] = bad["decisions"][:2]  # stops at 4.8s
        result, client = self._submit([
            _response([_block("tool_use", id="t1", name=TOOL_NAME, input=bad)]),
            _response([_block("tool_use", id="t2", name=TOOL_NAME, input=GOOD_PLAN)]),
        ])
        self.assertEqual(result, GOOD_PLAN)
        feedback = client.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(feedback["tool_use_id"], "t1")
        self.assertTrue(feedback["is_error"])
        self.assertIn("source duration", json.loads(feedback["content"])["errors"][0])

    def test_turn_without_a_tool_call_gets_a_nudge(self):
        _, client = self._submit([
            _response([_block("text", text="Here is my thinking...")], stop_reason="end_turn"),
            _response([_block("tool_use", id="t1", name=TOOL_NAME, input=GOOD_PLAN)]),
        ])
        self.assertIn(TOOL_NAME, client.requests[1]["messages"][-1]["content"])

    def test_refusal_raises_instead_of_running_the_tool(self):
        with self.assertRaisesRegex(ProviderError, "declined"):
            self._submit([_response([], stop_reason="refusal")])

    def test_truncated_output_raises(self):
        with self.assertRaisesRegex(ProviderError, "token limit"):
            self._submit([_response([], stop_reason="max_tokens")])

    def test_unparseable_stream_is_reissued(self):
        result, client = self._submit([
            ValueError("could not parse partial JSON"),
            _response([_block("tool_use", id="t1", name=TOOL_NAME, input=GOOD_PLAN)]),
        ])
        self.assertEqual(result, GOOD_PLAN)
        self.assertEqual(len(client.requests), 2)

    def test_fallbacks_enabled_for_opus_5_only(self):
        ok = [_response([_block("tool_use", id="t1", name=TOOL_NAME, input=GOOD_PLAN)])]
        _, opus = self._submit(list(ok))
        self.assertEqual(opus.requests[0]["fallbacks"], "default")
        _, haiku = self._submit(list(ok), model="claude-haiku-4-5")
        self.assertNotIn("fallbacks", haiku.requests[0])

    def test_tool_uses_eager_input_streaming(self):
        _, client = self._submit([_response([_block("tool_use", id="t1", name=TOOL_NAME, input=GOOD_PLAN)])])
        self.assertTrue(client.requests[0]["tools"][0]["eager_input_streaming"])

    def test_pre_fallback_thinking_and_tool_use_are_not_echoed(self):
        content = [
            _block("thinking", thinking=""),
            _block("tool_use", id="old", name=TOOL_NAME, input={}),
            _block("fallback"),
            _block("text", text="continuing"),
            _block("tool_use", id="new", name=TOOL_NAME, input={}),
        ]
        kept = [(b.type, getattr(b, "id", None)) for b in _echoable(content)]
        self.assertEqual(kept, [("fallback", None), ("text", None), ("tool_use", "new")])

    def test_gives_up_after_max_attempts(self):
        text_only = _response([_block("text", text="no")], stop_reason="end_turn")
        with self.assertRaisesRegex(ProviderError, "3 attempts"):
            self._submit([text_only, text_only, text_only])


# --- OpenAI-compatible fakes, shaped like chat completions responses ---

def _completion(tool_calls=None, finish_reason="tool_calls", model="gpt-test"):
    message = SimpleNamespace(content=None, tool_calls=tool_calls)
    return SimpleNamespace(model=model, choices=[SimpleNamespace(finish_reason=finish_reason, message=message)])


def _call(call_id, arguments):
    return SimpleNamespace(id=call_id, type="function",
                           function=SimpleNamespace(name=TOOL_NAME, arguments=arguments))


class _FakeOpenAI:
    def __init__(self, completions):
        self.completions_queue = list(completions)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.completions_queue.pop(0)


class TestOpenAICompatibleProvider(unittest.TestCase):
    def _submit(self, completions):
        client = _FakeOpenAI(completions)
        provider = OpenAICompatibleProvider(model="gpt-test", client=client)
        result = provider.submit("system", "user", build_tool(),
                                 lambda plan: check_plan(plan, TRANSCRIPT), max_attempts=3)
        return result, client

    def test_malformed_json_is_reported_then_valid_one_returned(self):
        result, client = self._submit([
            _completion([_call("c1", "{not json")]),
            _completion([_call("c2", json.dumps(GOOD_PLAN))]),
        ])
        self.assertEqual(result, GOOD_PLAN)
        tool_message = client.requests[1]["messages"][-1]
        self.assertEqual((tool_message["role"], tool_message["tool_call_id"]), ("tool", "c1"))
        self.assertIn("not valid JSON", tool_message["content"])

    def test_assistant_tool_calls_are_echoed_before_tool_results(self):
        _, client = self._submit([
            _completion([_call("c1", "{}")]),
            _completion([_call("c2", json.dumps(GOOD_PLAN))]),
        ])
        assistant = client.requests[1]["messages"][-2]
        self.assertEqual(assistant["tool_calls"][0]["id"], "c1")

    def test_content_filter_raises(self):
        with self.assertRaisesRegex(ProviderError, "declined"):
            self._submit([_completion(None, finish_reason="content_filter")])

    def test_model_is_required(self):
        with self.assertRaisesRegex(ProviderError, "needs a model"):
            OpenAICompatibleProvider(model=None, client=object())


class TestProviderSelection(unittest.TestCase):
    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ProviderError, "unknown provider"):
            get_provider("gemini-direct")


if __name__ == "__main__":
    unittest.main()
