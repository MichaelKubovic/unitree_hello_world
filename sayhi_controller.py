#!/usr/bin/env python3
import argparse
import random
import struct
import threading
import time

from unitree_sdk2py.a2.audio.audio_client import AudioClient
from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

from list_gestures import ERRORS, R1ArmActionClient
from sayhi import load_robot_pcm


BUTTON_BITS = {
    "R1": 0,
    "L1": 1,
    "START": 2,
    "SELECT": 3,
    "R2": 4,
    "L2": 5,
    "F1": 6,
    "F3": 7,
    "A": 8,
    "B": 9,
    "X": 10,
    "Y": 11,
    "UP": 12,
    "RIGHT": 13,
    "DOWN": 14,
    "LEFT": 15,
}

KISS_GESTURE_ID = 11
RANDOM_GESTURE_IDS = [12, 13, 15, 17, 18, 20, 21, 22, 23, 25, 26, 27]

CLIPS = {
    "F1+A": {
        "path": "1_Vitajte_Mark_B-16k-mono.wav",
        "gesture": KISS_GESTURE_ID,
    },
    "F1+B": {
        "path": "2_Vyzeras_Mark_B-16k-mono.wav",
        "gesture": KISS_GESTURE_ID,
    },
    "F1+X": {
        "path": "3_Urcite_Mark_B-16k-mono.wav",
        "gesture": "random",
    },
}


class SayHiController:
    def __init__(self, audio, arm, clips, app_name, gestures_enabled):
        self.audio = audio
        self.arm = arm
        self.clips = clips
        self.app_name = app_name
        self.gestures_enabled = gestures_enabled
        self.last_combo = None
        self.current_combo = None
        self.current_clip = None
        self.play_lock = threading.Lock()
        self.stop_event = threading.Event()

    def low_state_handler(self, msg):
        combo = self._pressed_combo(msg.wireless_remote)
        if combo is not None and combo != self.last_combo:
            self._toggle_playback(combo)
        self.last_combo = combo

    def _pressed_combo(self, wireless_remote):
        keys = struct.unpack_from("<H", bytes(wireless_remote), 2)[0]
        if not self._is_pressed(keys, "F1"):
            return None

        for combo, button in (("F1+A", "A"), ("F1+B", "B"), ("F1+X", "X")):
            if self._is_pressed(keys, button):
                return combo

        return None

    def _is_pressed(self, keys, button):
        return bool(keys & (1 << BUTTON_BITS[button]))

    def _toggle_playback(self, combo):
        if self.current_combo is not None:
            print(f"{combo} pressed: stopping {self.current_combo}.")
            self.stop_event.set()
            self.audio.PlayStop(self.app_name)
            return

        self.current_combo = combo
        self.current_clip = self.clips[combo]
        self.stop_event.clear()
        thread = threading.Thread(target=self._play_once, daemon=True)
        thread.start()

    def _play_once(self):
        with self.play_lock:
            print(f"{self.current_combo} pressed: playing clip.")
            try:
                self._start_gesture()
                self._stream_pcm_realtime()
            finally:
                self.audio.PlayStop(self.app_name)
                self.current_combo = None
                self.current_clip = None

    def _start_gesture(self):
        if not self.gestures_enabled:
            return

        gesture_id = self.current_clip["gesture"]
        if gesture_id == "random":
            gesture_id = random.choice(RANDOM_GESTURE_IDS)

        if gesture_id is None:
            return

        thread = threading.Thread(target=self._run_gesture, args=(gesture_id,), daemon=True)
        thread.start()

    def _run_gesture(self, gesture_id):
        print(f"Starting gesture {gesture_id}.")
        code = self.arm.ExecuteAction(gesture_id)
        if code != 0:
            print(f"Gesture {gesture_id} failed: {code} - {ERRORS.get(code, 'Unknown error')}")

    def _stream_pcm_realtime(self):
        bytes_per_second = 32000
        chunk_size = int(bytes_per_second * 0.20)
        stream_id = str(int(time.time() * 1000))
        offset = 0
        start = time.monotonic()

        pcm = self.current_clip["pcm"]
        while offset < len(pcm) and not self.stop_event.is_set():
            chunk = pcm[offset : offset + chunk_size]
            ret_code, _ = self.audio.PlayStream(self.app_name, stream_id, chunk)
            if ret_code != 0:
                raise RuntimeError(f"PlayStream failed at byte {offset} with code {ret_code}")

            offset += len(chunk)
            delay = start + (offset / bytes_per_second) - time.monotonic()
            if delay > 0:
                self.stop_event.wait(delay)


def main():
    parser = argparse.ArgumentParser(description="Play prepared WAV clips from F1 controller combos.")
    parser.add_argument(
        "network_interface",
        nargs="?",
        default="en6",
        help="DDS network interface connected to the robot, default: en6",
    )
    parser.add_argument(
        "--topic",
        default="rt/lowstate",
        help="LowState topic to subscribe to, default: rt/lowstate",
    )
    parser.add_argument(
        "--app-name",
        default="sayhi-controller",
        help="Audio stream app name, default: sayhi-controller",
    )
    parser.add_argument(
        "--no-gesture",
        action="store_true",
        help="Disable the gesture while keeping audio playback enabled.",
    )
    args = parser.parse_args()

    clips = {}
    for combo, config in CLIPS.items():
        path = config["path"]
        pcm = load_robot_pcm(path)
        clips[combo] = {
            "pcm": pcm,
            "gesture": config["gesture"],
        }
        print(f"Loaded {combo}: {path} ({len(pcm) / 32000:.2f}s), gesture: {config['gesture']}")

    ChannelFactoryInitialize(0, args.network_interface)

    audio = AudioClient()
    audio.SetTimeout(10.0)
    audio.Init()

    code, volume = audio.GetVolume()
    if code != 0:
        raise RuntimeError(f"Could not communicate with audio service, GetVolume code={code}")
    print(f"Robot speaker volume: {volume}")

    arm = R1ArmActionClient()
    arm.SetTimeout(30.0)
    arm.Init()

    if args.no_gesture:
        print("Gestures disabled.")
    else:
        print(f"Random gesture pool for F1+X: {RANDOM_GESTURE_IDS}")

    controller = SayHiController(audio, arm, clips, args.app_name, not args.no_gesture)
    subscriber = ChannelSubscriber(args.topic, LowState_)
    subscriber.Init(controller.low_state_handler, 10)

    print(f"Listening on {args.topic}. Press F1+A, F1+B, or F1+X. Repeat while playing to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        audio.PlayStop(args.app_name)
        print("Stopped.")


if __name__ == "__main__":
    main()
