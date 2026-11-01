"""The privacy rule: classification, the policy, and the job-start check."""

from pathlib import Path

import httpx
import pytest
import yaml

from bugbite.config import ConfigError, ModelConfig, Pricing, load_app_config, load_models_config
from bugbite.errors import ALL_PRIVACY_CODES, PRIVATE_CODE_BLOCKED, AdapterError, InputError, PrivacyError
from bugbite.github import GitHubClient, IssueData, JobContext, RepoInfo, fetch_job_context, parse_job_input
from bugbite.privacy import (
    Sensitivity,
    allowed_model_names,
    check_job_privacy,
    classify,
    classify_context,
    may_receive,
)

ROOT = Path(__file__).resolve().parent.parent
MODELS = load_models_config(ROOT / "config" / "models.yaml")


def model(allow, name="m"):
    return ModelConfig(name, "claude", "http://x", "m", 1000, True, Pricing.free(), 0, allow)


def context(full_name="octo/hello", private=False):
    repo = RepoInfo(full_name, private, "Python", "main", False, False, f"https://github.com/{full_name}")
    issue = IssueData(1, "t", "b", (), "open", "u", "https://github.com/x", False)
    return JobContext(repo, issue, (), False)


# -- classification ---------------------------------------------------------------------------------


def test_a_public_repo_is_public_and_a_private_one_is_private():
    assert classify("octo/hello", False) is Sensitivity.PUBLIC
    assert classify("octo/hello", True) is Sensitivity.PRIVATE


@pytest.mark.parametrize("unknown", [None, 0, 1, "false", "public", [], "no"])
def test_anything_other_than_an_explicit_public_is_private(unknown):
    assert classify("octo/hello", unknown) is Sensitivity.PRIVATE  # fail closed


@pytest.mark.parametrize("private", [True, False, None])
def test_a_repo_on_the_sandbox_list_is_sandbox_whatever_its_visibility(private):
    assert classify("octo/hello", private, ["octo/hello"]) is Sensitivity.SANDBOX


@pytest.mark.parametrize("listed, name", [("OCTO/Hello", "octo/hello"), ("octo/hello", "Octo/HELLO"), ("  octo/hello  ", "octo/hello"), ("octo/hello", "  octo/hello ")])
def test_sandbox_matching_ignores_case_and_surrounding_spaces(listed, name):
    assert classify(name, True, [listed]) is Sensitivity.SANDBOX


@pytest.mark.parametrize("name", ["octo/hello-world", "octo/hello2", "octo/hell", "other/hello", "octo-other/hello", "hello", "octo/hello/extra", "xocto/hello", ""])
def test_sandbox_matching_is_exact_on_the_whole_name(name):
    assert classify(name, True, ["octo/hello"]) is Sensitivity.PRIVATE


def test_the_sandbox_list_may_be_empty_or_absent():
    assert classify("octo/hello", True, []) is Sensitivity.PRIVATE
    assert classify("octo/hello", True) is Sensitivity.PRIVATE
    assert classify("octo/hello", True, ()) is Sensitivity.PRIVATE


@pytest.mark.parametrize("name", [None, 5, ["octo/hello"]])
def test_a_missing_or_odd_name_cannot_match_the_sandbox_list(name):
    assert classify(name, True, ["octo/hello"]) is Sensitivity.PRIVATE


def test_classification_of_a_fetched_job_uses_the_name_github_returned():
    # the API's canonical spelling is what counts, not what anyone typed
    assert classify_context(context("Octo/Hello", True), ["octo/hello"]) is Sensitivity.SANDBOX
    assert classify_context(context("octo/hello", True), []) is Sensitivity.PRIVATE
    assert classify_context(context("octo/hello", False), []) is Sensitivity.PUBLIC


# -- the policy ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "allow, sensitivity, expected",
    [
        (True, Sensitivity.PUBLIC, True), (True, Sensitivity.SANDBOX, True), (True, Sensitivity.PRIVATE, True),
        (False, Sensitivity.PUBLIC, True), (False, Sensitivity.SANDBOX, True), (False, Sensitivity.PRIVATE, False),
    ],
)  # fmt: skip
def test_the_policy_table(allow, sensitivity, expected):
    assert may_receive(model(allow), sensitivity) is expected


@pytest.mark.parametrize("bad", [None, "private", "public", 1, True])
def test_the_policy_refuses_to_guess_what_a_sensitivity_is(bad):
    with pytest.raises(TypeError):
        may_receive(model(False), bad)


def test_allowed_model_names():
    assert allowed_model_names(MODELS) == ["local-free"]
    assert allowed_model_names({}) == []


# -- the job-start check --------------------------------------------------------------------------------------


def test_allowed_combinations_return_the_sensitivity():
    assert check_job_privacy(model(False), context(private=False)) is Sensitivity.PUBLIC
    assert check_job_privacy(model(True), context(private=True)) is Sensitivity.PRIVATE
    assert check_job_privacy(model(False), context(private=True), sandbox_repos=["octo/hello"]) is Sensitivity.SANDBOX


def test_a_blocked_job_raises_a_clear_error_before_any_work():
    with pytest.raises(PrivacyError) as info:
        check_job_privacy(MODELS["groq-free"], context("octo/secret", True), models=MODELS)
    message = info.value.message
    assert info.value.code == PRIVATE_CODE_BLOCKED
    assert "groq-free" in message and "octo/secret" in message
    assert "local-free" in message  # the models that would be allowed
    assert "config/models.yaml" in message and "data terms" in message  # how the owner can change the policy


def test_the_message_says_so_when_no_model_may_receive_private_code():
    only_closed = {"a": model(False, "a"), "b": model(False, "b")}
    with pytest.raises(PrivacyError, match="No configured model is allowed to receive private code"):
        check_job_privacy(only_closed["a"], context(private=True), models=only_closed)
    with pytest.raises(PrivacyError, match="No configured model"):
        check_job_privacy(only_closed["a"], context(private=True))  # no model list given


def test_unknown_visibility_is_refused_like_a_private_repo():
    unknown = context()
    unknown = JobContext(RepoInfo("octo/hello", None, "Python", "main", False, False, "u"), unknown.issue, (), False)  # type: ignore[arg-type]
    with pytest.raises(PrivacyError, match="visibility is unknown"):
        check_job_privacy(model(False), unknown)


def test_the_refusal_never_contains_issue_text_or_comments():
    secret_context = context("octo/secret", True)
    secret_context = JobContext(
        secret_context.repo, IssueData(1, "TOPSECRET-TITLE", "TOPSECRET-BODY", ("bug",), "open", "u", "x", False), (), False
    )
    with pytest.raises(PrivacyError) as info:
        check_job_privacy(model(False), secret_context, models=MODELS)
    assert "TOPSECRET" not in info.value.message


def test_there_is_no_way_to_bypass_the_check_by_argument():
    import inspect

    parameters = set(inspect.signature(check_job_privacy).parameters)
    assert parameters == {"model", "context", "sandbox_repos", "models"}  # nothing like force/override/skip


def test_the_shipped_policy():
    assert [n for n, m in MODELS.items() if m.allow_private_code] == ["local-free"]
    assert MODELS["haiku"].allow_private_code is False and MODELS["groq-free"].allow_private_code is False


# -- the error family -------------------------------------------------------------------------------------------------


def test_privacy_error_is_its_own_family():
    assert not issubclass(PrivacyError, (InputError, AdapterError))
    assert ALL_PRIVACY_CODES == {"private_code_blocked"}
    error = PrivacyError(PRIVATE_CODE_BLOCKED, "blocked")
    assert (error.code, error.message, str(error)) == (PRIVATE_CODE_BLOCKED, "blocked", "blocked")


def test_privacy_error_validates_its_arguments():
    with pytest.raises(ValueError):
        PrivacyError("made_up", "x")
    with pytest.raises(ValueError):
        PrivacyError(PRIVATE_CODE_BLOCKED, "")
    with pytest.raises(ValueError):
        PrivacyError("rate_limited", "x")  # an adapter code, not a privacy one


# -- sandbox_repos in the config -------------------------------------------------------------------------------------


APP = {"default_model": "haiku", "max_steps": 10, "max_cost_usd": 0.1, "max_wall_clock_s": 60, "total_budget_usd": 5}


def load_app(tmp_path, **extra):
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump({**APP, **extra}))
    return load_app_config(path)


def test_the_list_defaults_to_empty_and_the_shipped_file_has_it_empty(tmp_path):
    assert load_app(tmp_path).sandbox_repos == ()
    assert load_app_config(ROOT / "config" / "app.yaml").sandbox_repos == ()
    assert "sandbox_repos: []" in (ROOT / "config" / "app.yaml").read_text()


def test_entries_are_normalised_and_de_duplicated(tmp_path):
    cfg = load_app(tmp_path, sandbox_repos=["Octo/Hello", " octo/hello ", "other/Demo.py", "OCTO/HELLO"])
    assert cfg.sandbox_repos == ("octo/hello", "other/demo.py")


def test_null_means_empty(tmp_path):
    assert load_app(tmp_path, sandbox_repos=None).sandbox_repos == ()


@pytest.mark.parametrize("bad", ["octo/hello", {"octo": "hello"}, 5, True])
def test_the_list_must_be_a_list(tmp_path, bad):
    with pytest.raises(ConfigError, match="sandbox_repos"):
        load_app(tmp_path, sandbox_repos=bad)


@pytest.mark.parametrize("entry", ["hello", "octo/", "/hello", "octo/hello/extra", "", "  ", "oc to/hello", "octo/he llo", "octo/..", "-octo/hello", "octo-/hello", 5, None, ["a/b"], "https://github.com/octo/hello"])
def test_bad_entries_are_rejected_naming_the_entry(tmp_path, entry):
    with pytest.raises(ConfigError, match="sandbox_repos entry"):
        load_app(tmp_path, sandbox_repos=["ok/fine", entry])


# -- end to end through the GitHub client ---------------------------------------------------------------------------------


def served_job(private):
    def handler(request):
        path = request.url.path
        if path == "/repos/octo/secret":
            return httpx.Response(200, json={"full_name": "octo/secret", "private": private, "language": "Python", "default_branch": "main", "html_url": "https://github.com/octo/secret"})
        if path == "/repos/octo/secret/issues/7":
            return httpx.Response(200, json={"number": 7, "title": "Crash", "body": "SECRET BODY", "labels": [], "state": "open", "user": {"login": "u"}, "html_url": "https://github.com/octo/secret/issues/7"})
        return httpx.Response(200, json=[])

    client = GitHubClient("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))
    job = parse_job_input("https://github.com/octo/secret/issues/7", "https://github.com/octo/secret")
    return fetch_job_context(client, job)


def test_a_private_repo_is_refused_for_closed_models_and_accepted_for_the_local_one():
    fetched = served_job(private=True)
    assert classify_context(fetched) is Sensitivity.PRIVATE
    for name in ("groq-free", "haiku"):
        with pytest.raises(PrivacyError) as info:
            check_job_privacy(MODELS[name], fetched, models=MODELS)
        assert "octo/secret" in info.value.message and "SECRET BODY" not in info.value.message
    assert check_job_privacy(MODELS["local-free"], fetched, models=MODELS) is Sensitivity.PRIVATE


def test_a_private_repo_on_the_sandbox_list_is_accepted_for_every_model():
    fetched = served_job(private=True)
    for name in MODELS:
        assert check_job_privacy(MODELS[name], fetched, ["octo/secret"], MODELS) is Sensitivity.SANDBOX


def test_a_public_repo_is_accepted_for_every_model():
    fetched = served_job(private=False)
    for name in MODELS:
        assert check_job_privacy(MODELS[name], fetched, models=MODELS) is Sensitivity.PUBLIC
