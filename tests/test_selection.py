import threading, time
from unittest.mock import patch, call
import pytest
from app.selection import (
    MARKER_PREFIX, _is_marker, _clip_get, _clip_set,
    _clipboard_seq, _ensure_not_marker_on_clipboard,
    _send_ctrl_c, _wait_mods_up, get_selected_text,
    sanitize_selection, _CLIP_LOCK, _restore_verdict,
)

class TestSanitize:
    def test_normal(self): assert sanitize_selection("Hello") == "Hello"
    def test_ws(self): assert sanitize_selection("  hi  ") == "hi"
    def test_nulls(self): assert sanitize_selection(chr(0)+"hi"+chr(0)) == "hi"
    def test_none(self): assert sanitize_selection(None) == ""
    def test_empty(self): assert sanitize_selection("") == ""
    def test_ws_only(self): assert sanitize_selection("   ") == ""
    def test_marker(self): assert sanitize_selection(MARKER_PREFIX+"ab__") == ""
    def test_marker_pad(self): assert sanitize_selection("  "+MARKER_PREFIX+"a__  ") == ""
    def test_marker_partial(self): assert sanitize_selection(MARKER_PREFIX+"abc") == ""
    def test_marker_first(self): assert sanitize_selection(MARKER_PREFIX+"1__\nshort") == ""
    def test_marker_long(self): assert len(sanitize_selection(MARKER_PREFIX+"a\n"+"x"*200)) > 100
    def test_100k(self): assert len(sanitize_selection("A"*100000)) == 100000
    def test_500k(self): assert len(sanitize_selection("B"*500000)) == 500000
    def test_tabs(self): assert sanitize_selection("a\tb") == "a\tb"
    def test_crlf(self): assert sanitize_selection("a\r\nb") == "a\r\nb"

class TestIsMarker:
    @pytest.mark.parametrize("v", [None, "", "   ", "Hello"])
    def test_not(self, v): assert _is_marker(v) is False
    def test_pure(self): assert _is_marker(MARKER_PREFIX+"ab__") is True
    def test_padded(self): assert _is_marker("  "+MARKER_PREFIX+"a__  ") is True
    def test_partial(self): assert _is_marker(MARKER_PREFIX+"abc") is True
    def test_long(self): assert _is_marker(MARKER_PREFIX+"a real text") is False

class TestClipRetry:
    @patch("app.selection.pyperclip")
    def test_get_ok(self, pc): pc.paste.return_value="hi"; assert _clip_get()=="hi"
    @patch("app.selection.pyperclip")
    def test_get_retry(self, pc): pc.paste.side_effect=[Exception("x")]*5+["ok"]; assert _clip_get()=="ok"
    @patch("app.selection.pyperclip")
    def test_get_fail(self, pc): pc.paste.side_effect=Exception("x"); assert _clip_get()==""; assert pc.paste.call_count==8
    @patch("app.selection.pyperclip")
    def test_get_none(self, pc): pc.paste.return_value=None; assert _clip_get()==""
    @patch("app.selection.pyperclip")
    def test_set_ok(self, pc): assert _clip_set("t") is True
    @patch("app.selection.pyperclip")
    def test_set_retry(self, pc): pc.copy.side_effect=[Exception]*3+[None]; assert _clip_set("t") is True
    @patch("app.selection.pyperclip")
    def test_set_fail(self, pc): pc.copy.side_effect=Exception; assert _clip_set("t") is False
    @patch("app.selection.pyperclip")
    def test_set_none(self, pc): _clip_set(None); pc.copy.assert_called_with("")

class TestSeq:
    @patch("app.selection.sys")
    def test_non_win(self, s): s.platform="linux"; assert _clipboard_seq()==0

class TestCtrlC:
    @patch("keyboard.send")
    @patch("app.selection.sys")
    def test_ok(self, s, ks): s.platform="linux"; assert _send_ctrl_c() is True; ks.assert_called_once_with("ctrl+c")
    @patch("keyboard.send", side_effect=Exception)
    @patch("app.selection.sys")
    def test_fail(self, s, ks): s.platform="linux"; assert _send_ctrl_c() is False

class TestModsUp:
    @patch("app.selection.sys")
    def test_non_win(self, s): s.platform="linux"; assert _wait_mods_up(0.1) is True
    @patch("app.selection.sys")
    @patch("app.selection._mods_down_win", return_value=False)
    def test_no_mods(self, m, s): s.platform="win32"; assert _wait_mods_up(2) is True
    @patch("app.selection.sys")
    @patch("app.selection._mods_down_win")
    def test_release(self, m, s): s.platform="win32"; m.side_effect=[True,True,False]; assert _wait_mods_up(2) is True
    @patch("app.selection.sys")
    @patch("app.selection._mods_down_win", return_value=True)
    def test_stuck(self, m, s): s.platform="win32"; assert _wait_mods_up(0.1) is False

class TestEnsureNot:
    @patch("app.selection._clip_set")
    @patch("app.selection._clip_get")
    def test_clears(self, g, s): g.return_value=MARKER_PREFIX+"x__"; _ensure_not_marker_on_clipboard("p"); s.assert_called_once_with("p")
    @patch("app.selection._clip_set")
    @patch("app.selection._clip_get")
    def test_prev_m(self, g, s): g.return_value=MARKER_PREFIX+"x__"; _ensure_not_marker_on_clipboard(MARKER_PREFIX+"o__"); s.assert_called_once_with("")
    @patch("app.selection._clip_set")
    @patch("app.selection._clip_get")
    def test_noop(self, g, s): g.return_value="real"; _ensure_not_marker_on_clipboard("p"); s.assert_not_called()

def _run(sq, cv, restore=True, settle=0.25, fb=False, send=True):
    with (
        patch("app.selection._clipboard_seq") as seq,
        patch("app.selection._wait_mods_up", return_value=True),
        patch("app.selection._send_ctrl_c", return_value=send),
        patch("app.selection._clip_get") as cg,
        patch("app.selection._clip_set") as cs,
    ):
        seq.side_effect=list(sq); cg.side_effect=list(cv)
        return get_selected_text(restore_clipboard=restore, settle_s=settle, clipboard_fallback=fb), cs

class TestGST:
    def test_happy(self):
        r, cs = _run([10,11,11,11], ["old","sel","sel","sel"]); assert r=="sel"; cs.assert_called_with("old")
    def test_no_change(self): assert _run([10]*20, ["old"]*20)[0] == ""
    def test_fallback(self): assert _run([10]*20, ["prev"]*20, fb=True)[0] == "prev"
    def test_cc_fail(self): assert _run([10], ["old"]*4, send=False)[0] == ""
    def test_cc_fail_fb(self): assert _run([10], ["prev"]*4, send=False, fb=True)[0] == "prev"
    def test_no_restore(self):
        r, cs = _run([10,11,11,11], ["old","new","new","new"], restore=False)
        assert r=="new"
        for c in cs.call_args_list: assert c != call("old")
    def test_marker_prev(self):
        r, cs = _run([10,11,11,11], [MARKER_PREFIX+"x__","sel","sel","sel"]); assert r=="sel"; cs.assert_called_with("")
    def test_marker_sel(self):
        m=MARKER_PREFIX+"l__"; assert _run([10,11,11,11], ["old",m,m,m])[0] == ""
    def test_empty(self): assert _run([10,11,11,11], ["old","","",""])[0] == ""

class TestLarge:
    def test_500k(self):
        big="X"*500000; r,_=_run([10,11,11,11],["old",big,big,big]); assert r==big
    def test_growing(self):
        r,_=_run([10]+[11]*20,["old","A"*10000,"A"*50000]+["A"*100000]*4, settle=1.0); assert len(r)==100000
    def test_huge(self):
        r,_=_run([10]+[11]*20,["old","B"*60000]+["B"*60001]*4, settle=1.5); assert len(r)>=60000

class TestRestoreVerdict:
    """The clipboard goes back only when it is still ours to give back."""

    def _v(self, prev="old", before=10, after=11, cur=11, copied=False, marker=False):
        with (
            patch("app.selection._clipboard_seq", return_value=cur),
            patch("app.selection.copy_guard.copied_since", return_value=copied),
        ):
            return _restore_verdict(prev, before, after, 0.0, prev_marker=marker)

    def test_happy(self): assert self._v()[0] is True
    def test_user_copied(self):
        ok, why = self._v(copied=True); assert ok is False; assert "user copied" in why
    def test_untouched(self):
        ok, why = self._v(before=10, after=0, cur=10); assert ok is False; assert "untouched" in why
    def test_someone_else_wrote(self):
        ok, why = self._v(after=11, cur=12); assert ok is False; assert "another app" in why
    def test_empty_prev(self):
        ok, why = self._v(prev=""); assert ok is False; assert "empty" in why
    def test_empty_prev_marker(self): assert self._v(prev="", marker=True)[0] is True
    def test_no_seq_platform(self): assert self._v(before=0, after=0, cur=0)[0] is True


class TestUserCopyWins:
    """The reported bug: Ctrl+C during a capture must survive."""

    def test_capture_does_not_wipe_user_copy(self):
        with patch("app.selection.copy_guard.copied_since") as cs_since:
            # False for the fast-path check, True by the time we would restore
            cs_since.side_effect = [False, True]
            r, cs = _run([10, 11, 11, 11], ["old", "mine", "mine", "mine"])
        assert r == "mine"
        cs.assert_not_called()

    def test_fresh_user_copy_skips_injection(self):
        with (
            patch("app.selection.copy_guard.copied_since", return_value=True),
            patch("app.selection.copy_guard.recent", return_value=True),
            patch("app.selection._send_ctrl_c") as send,
            patch("app.selection._clip_get", return_value="what the user copied"),
            patch("app.selection._clip_set") as cs,
        ):
            got = get_selected_text(restore_clipboard=True, settle_s=0.25, since=0.0)
        assert got == "what the user copied"
        send.assert_not_called()
        cs.assert_not_called()

    def test_stuck_ctrl_never_injects(self):
        with (
            patch("app.selection._wait_mods_up", return_value=False),
            patch("app.selection._send_ctrl_c") as send,
            patch("app.selection._clip_get", return_value="x"),
            patch("app.selection._clip_set") as cs,
        ):
            assert get_selected_text(restore_clipboard=True, settle_s=0.25) == ""
        send.assert_not_called()
        cs.assert_not_called()

    def test_stuck_ctrl_falls_back_to_clipboard(self):
        with (
            patch("app.selection._wait_mods_up", return_value=False),
            patch("app.selection._send_ctrl_c") as send,
            patch("app.selection._clip_get", return_value="prev"),
            patch("app.selection._clip_set"),
        ):
            got = get_selected_text(restore_clipboard=True, settle_s=0.25, clipboard_fallback=True)
        assert got == "prev"
        send.assert_not_called()

    def test_nothing_copied_no_pointless_write(self):
        """Ctrl+C produced no change — writing anything would kill rich formats."""
        r, cs = _run([10] * 20, ["old"] * 20)
        assert r == ""
        cs.assert_not_called()


class TestRace:
    def test_lock_timeout(self):
        _CLIP_LOCK.acquire()
        try:
            with (
                patch("app.selection._clipboard_seq", return_value=10),
                patch("app.selection._wait_mods_up", return_value=True),
                patch("app.selection._send_ctrl_c", return_value=True),
                patch("app.selection._clip_get", return_value="x"),
                patch("app.selection._clip_set"),
            ): assert get_selected_text(restore_clipboard=True, settle_s=0.25) == ""
        finally: _CLIP_LOCK.release()
    def test_sequential(self):
        for lb in ("t0","t1","t2"): assert _run([10,11,11,11],["old",lb,lb,lb])[0]==lb
    def test_exc_frees(self):
        with (
            patch("app.selection._wait_mods_up", return_value=True),
            patch("app.selection._send_ctrl_c", return_value=True),
            patch("app.selection._clip_get", side_effect=Exception("boom")),
            patch("app.selection._clip_set"),
        ): get_selected_text(restore_clipboard=True, settle_s=0.25)
        acquired = _CLIP_LOCK.acquire(timeout=0.5)
        assert acquired
        _CLIP_LOCK.release()
    def test_restore_on_exc(self):
        with (
            patch("app.selection._clipboard_seq") as seq,
            patch("app.selection._wait_mods_up", return_value=True),
            patch("app.selection._send_ctrl_c", return_value=True),
            patch("app.selection._clip_get") as cg,
            patch("app.selection._clip_set") as cs,
        ):
            seq.side_effect = [10, 11]
            cg.side_effect = ["important", Exception("denied")]
            get_selected_text(restore_clipboard=True, settle_s=0.25)
            cs.assert_called()
