from homelab_mcp.redact import Redactor


def test_builtin_patterns():
    r = Redactor()
    cases = {
        "key sk-ant-api03-abcdefghijklmnopqrstuvwxyz": "sk-ant-",
        "openai sk-proj1234567890abcdefghijkl": "sk-proj",
        "gh ghp_0123456789abcdefghijABCDEFGHIJ012345": "ghp_",
        "pat github_pat_11ABCDEFG0123456789_abcdefghijk": "github_pat_",
        "aws AKIAIOSFODNN7EXAMPLE": "AKIA",
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig_123": "eyJhbGci",
        "mail theo@example.com": "theo@example.com",
        "Authorization: Bearer abcdefghijkl123": "abcdefghijkl123",
        "DB_PASSWORD=hunter2": "hunter2",
        '{"api_key": "abc123xyz"}': "abc123xyz",
        "GITHUB_TOKEN=whatever": "whatever",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----": "MIIE",
    }
    for text, secret in cases.items():
        assert secret not in r.text(text), text


def test_harmless_text_unchanged():
    r = Redactor()
    s = "scored 42 postings in 3.2s, tokens_in=51234 cost_usd=0.06"
    assert r.text(s) == s


def test_key_name_kept_for_context():
    assert Redactor().text("DB_PASSWORD=hunter2") == "DB_PASSWORD=[REDACTED]"


def test_custom_patterns():
    r = Redactor([r"HOMELAB-\d{4}"])
    assert r.text("id HOMELAB-1234 here") == "id [REDACTED] here"


def test_nested_structures():
    r = Redactor()
    out = r.any({"a": ["x theo@example.com", {"b": "ok"}], "n": 3, "t": ("ghp_" + "a" * 36,)})
    assert out == {"a": ["x [REDACTED:email]", {"b": "ok"}], "n": 3,
                   "t": ["[REDACTED:github_token]"]}


def test_custom_pattern_applies_through_service(service, runner):
    runner.add(("logs",), "ticket HOMELAB-0042 opened\n")
    assert "HOMELAB-0042" not in service.job_logs("default", "j")["log"]


def test_names_starting_with_a_digit_are_not_secret_keys():
    # Real false positive from the PC1 demo: a company name in a job-board count.
    r = Redactor()
    line = "1Password: 41 open, 0 new, 0 changed, 0 closed"
    assert r.text(line) == line


def test_bare_secret_key_names_still_redacted():
    r = Redactor()
    for text in ["PASSWORD=hunter2", "token: abc123", "Secret=xyz", "password: 41",
                 "MY_API_KEY=k1", "credentials=a:b"]:
        assert "[REDACTED]" in r.text(text), text
