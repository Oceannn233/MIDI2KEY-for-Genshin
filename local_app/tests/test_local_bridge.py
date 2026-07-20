import unittest
from pathlib import Path
from types import SimpleNamespace

from lyre_bridge_server import MidiPortManager
from lyre_core import LyreEngine, MapperConfig, map_note_group


class FakeKeyboard:
    def __init__(self):
        self.pressed = []
        self.released = []

    def press(self, key):
        self.pressed.append(key)

    def release(self, key):
        self.released.append(key)


class FakePort:
    def __init__(self):
        self.closed = False
        self.messages = []

    def poll(self):
        return self.messages.pop(0) if self.messages else None

    def close(self):
        self.closed = True


class FakeMido:
    def __init__(self, fail=False):
        self.fail = fail
        self.port = FakePort()

    def get_input_names(self):
        return ["Roland Digital Piano 0"]

    def open_input(self, _name):
        if self.fail:
            raise RuntimeError("MidiInWinMM::openPort: error creating Windows MM MIDI input port.")
        return self.port


class LocalBridgeTests(unittest.TestCase):
    def test_db_major_triad_is_lossless(self):
        result = map_note_group([61, 65, 68], MapperConfig(source_tonic=1))
        self.assertEqual([result.assignments[note] for note in [61, 65, 68]], [60, 64, 67])

    def test_output_is_opt_in_and_releases_on_note_off(self):
        keyboard = FakeKeyboard()
        engine = LyreEngine(MapperConfig(source_tonic=1), keyboard)
        for note in [61, 65, 68]:
            engine.queue_note_on(note)
        engine.flush_pending(force=True)
        self.assertEqual(keyboard.pressed, [])

        engine.set_output_enabled(True)
        for note in [61, 65, 68]:
            engine.queue_note_on(note)
        engine.flush_pending(force=True)
        self.assertEqual(keyboard.pressed, ["a", "d", "g"])
        for note in [61, 65, 68]:
            engine.note_off(note)
        self.assertEqual(keyboard.released[-3:], ["a", "d", "g"])

    def test_parameter_change_panics_before_reconfiguring(self):
        keyboard = FakeKeyboard()
        engine = LyreEngine(MapperConfig(source_tonic=1), keyboard)
        engine.set_output_enabled(True)
        engine.queue_note_on(61)
        engine.flush_pending(force=True)
        engine.update_config(MapperConfig(source_tonic=2))
        self.assertIn("a", keyboard.released)
        self.assertEqual(engine.active_mapping, {})

    def test_port_ownership_error_is_reported_without_crashing_server(self):
        engine = LyreEngine(MapperConfig(), FakeKeyboard())
        manager = MidiPortManager(FakeMido(fail=True), engine)
        manager.open("Roland Digital Piano 0")
        self.assertFalse(manager.connected)
        self.assertIn("占用", manager.error)
        self.assertIn("MidiInWinMM", manager.technical_error)

    def test_port_can_be_retried_after_owner_releases_it(self):
        engine = LyreEngine(MapperConfig(), FakeKeyboard())
        fake_mido = FakeMido(fail=True)
        manager = MidiPortManager(fake_mido, engine)
        manager.open("Roland Digital Piano 0")
        fake_mido.fail = False
        manager.open("Roland Digital Piano 0")
        self.assertTrue(manager.connected)
        self.assertIsNone(manager.error)

    def test_browser_never_opens_web_midi(self):
        javascript = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("requestMIDIAccess", javascript)


if __name__ == "__main__":
    unittest.main()

