"""pacta.cli.run_verify bağımsız-doğrulama CLI dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: sabit yerleşik adreslerle yerel doğrulama.
"""
import json
import sys

import pytest

from pacta.cli import run_verify


@pytest.fixture
def json_output():
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_verify(json_output=True)
    return rc, json.loads(buf.getvalue())


# -- dönüş değeri ---------------------------------------------------------------------------

def test_returns_int():
    assert isinstance(run_verify(), int)


def test_json_returns_zero(json_output):
    rc, _ = json_output
    assert rc == 0


def test_text_returns_zero():
    assert run_verify(json_output=False) == 0


# -- JSON şema ---------------------------------------------------------------------------

def test_json_top_level_keys(json_output):
    _, d = json_output
    for k in ("verdict", "passed", "total", "checks"):
        assert k in d


def test_json_verdict_pass(json_output):
    _, d = json_output
    assert d["verdict"] == "PASS"


def test_json_all_passed(json_output):
    _, d = json_output
    assert d["passed"] == d["total"]


def test_json_total_matches_checks(json_output):
    _, d = json_output
    assert d["total"] == len(d["checks"])


# -- checks ---------------------------------------------------------------------------

def test_checks_have_names(json_output):
    _, d = json_output
    assert all(c["check"] for c in d["checks"])


def test_checks_have_result(json_output):
    _, d = json_output
    assert all("result" in c for c in d["checks"])


def test_checks_have_detail(json_output):
    _, d = json_output
    assert all("detail" in c for c in d["checks"])


CHECK_NAMES = {
    "dvp_happy_path",
    "refund_on_failed_verification",
    "schelling_arbitration_slashing",
    "idempotency_no_double_lock",
    "role_gate_stranger_rejected",
    "fsm_terminal_state_guard",
    "solvency_invariant",
}


def test_expected_checks_present(json_output):
    _, d = json_output
    names = {c["check"] for c in d["checks"]}
    assert names == CHECK_NAMES


@pytest.mark.parametrize("name", sorted(CHECK_NAMES))
def test_each_check_passes(json_output, name):
    _, d = json_output
    check = next(c for c in d["checks"] if c["check"] == name)
    assert check["result"] == "PASS"


@pytest.mark.parametrize("name", sorted(CHECK_NAMES))
def test_each_check_has_detail(json_output, name):
    _, d = json_output
    check = next(c for c in d["checks"] if c["check"] == name)
    assert check["detail"] != ""


# -- metin modu ---------------------------------------------------------------------------

def test_text_mode_prints_verdict(capsys):
    run_verify(json_output=False)
    out = capsys.readouterr().out
    assert "PASS" in out or "FAIL" in out


def test_text_mode_prints_checks(capsys):
    run_verify(json_output=False)
    out = capsys.readouterr().out
    assert "dvp_happy_path" in out


def test_text_mode_not_json(capsys):
    run_verify(json_output=False)
    out = capsys.readouterr().out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# -- DvP happy path detayı ---------------------------------------------------------------------------

def test_dvp_detail_settled(json_output):
    _, d = json_output
    check = next(c for c in d["checks"] if c["check"] == "dvp_happy_path")
    assert "SETTLED" in check["detail"]


def test_refund_detail_present(json_output):
    _, d = json_output
    check = next(c for c in d["checks"]
                 if c["check"] == "refund_on_failed_verification")
    assert "detail" in check


def test_role_gate_detail_stranger(json_output):
    _, d = json_output
    check = next(c for c in d["checks"]
                 if c["check"] == "role_gate_stranger_rejected")
    assert "STRANGER" in check["detail"].upper() or "stranger" in check["detail"]


def test_solvency_detail(json_output):
    _, d = json_output
    check = next(c for c in d["checks"] if c["check"] == "solvency_invariant")
    assert "solv" in check["detail"].lower()


def test_idempotency_detail(json_output):
    _, d = json_output
    check = next(c for c in d["checks"]
                 if c["check"] == "idempotency_no_double_lock")
    assert "same" in check["detail"].lower() or "lock" in check["detail"].lower()


def test_fsm_detail_terminal(json_output):
    _, d = json_output
    check = next(c for c in d["checks"] if c["check"] == "fsm_terminal_state_guard")
    assert "terminal" in check["detail"].lower()


# -- tekrar çalıştırma (idempotent) ---------------------------------------------------------------------------

def test_repeatable():
    rc1 = run_verify()
    rc2 = run_verify()
    assert rc1 == rc2 == 0


def test_json_repeatable():
    import io
    import contextlib

    def _run():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_verify(json_output=True)
        return json.loads(buf.getvalue())

    d1, d2 = _run(), _run()
    assert d1["verdict"] == d2["verdict"]
    assert d1["passed"] == d2["passed"]


# -- CLI girişi (subprocess) ---------------------------------------------------------------------------

def test_cli_entry_json(monkeypatch):
    """main() --json argumani JSON basar."""
    import contextlib
    import io
    monkeypatch.setattr(sys, "argv", ["pacta", "verify", "--json"])
    from pacta.cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            main()
        except SystemExit as e:
            assert e.code in (0, None)
    json.loads(buf.getvalue())


def test_cli_entry_text(monkeypatch):
    """main() text modu PASS basar."""
    import contextlib
    import io
    monkeypatch.setattr(sys, "argv", ["pacta", "verify"])
    from pacta.cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            main()
        except SystemExit as e:
            assert e.code in (0, None)
    out = buf.getvalue()
    assert "PASS" in out or "FAIL" in out
