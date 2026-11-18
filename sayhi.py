#!/usr/bin/env python3
import argparse
import time
import wave
from pathlib import Path

from unitree_sdk2py.a2.audio.audio_client import AudioClient
from unitree_sdk2py.core.channel import ChannelFactoryInitialize


DEFAULT_WAV = Path(__file__).with_name("privitanie-willow-SK-povodny-text-16k-mono.wav")
ROBOT_SAMPLE_RATE = 16_000
ROBOT_CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
CHUNK_SECONDS = 0.20


def load_robot_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != ROBOT_CHANNELS:
            raise ValueError(f"{path} must be mono")
        if wav.getsampwidth() != SAMPLE_WIDTH_BYTES:
            raise ValueError(f"{path} must be 16-bit PCM")
        if wav.getframerate() != ROBOT_SAMPLE_RATE:
            raise ValueError(f"{path} must be {ROBOT_SAMPLE_RATE} Hz")

        return wav.readframes(wav.getnframes())


def stream_pcm_realtime(audio: AudioClient, pcm: bytes, app_name: str) -> None:
    bytes_per_second = ROBOT_SAMPLE_RATE * ROBOT_CHANNELS * SAMPLE_WIDTH_BYTES
    chunk_size = int(bytes_per_second * CHUNK_SECONDS)
    chunk_size -= chunk_size % SAMPLE_WIDTH_BYTES
    stream_id = str(int(time.time() * 1000))

    offset = 0
    start = time.monotonic()

    while offset < len(pcm):
        chunk = pcm[offset : offset + chunk_size]
        ret_code, _ = audio.PlayStream(app_name, stream_id, chunk)
        if ret_code != 0:
            raise RuntimeError(f"PlayStream failed at byte {offset} with code {ret_code}")

        offset += len(chunk)
        audio_seconds_sent = offset / bytes_per_second
        sleep_until = start + audio_seconds_sent
        delay = sleep_until - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play the prepared greeting WAV through the robot speaker.")
    parser.add_argument(
        "network_interface",
        nargs="?",
        default="en6",
        help="DDS network interface connected to the robot, default: en6",
    )
    parser.add_argument(
        "--wav",
        type=Path,
        default=DEFAULT_WAV,
        help=f"Prepared 16 kHz mono WAV file to play, default: {DEFAULT_WAV.name}",
    )
    parser.add_argument(
        "--app-name",
        default="sayhi",
        help="Audio stream app name, default: sayhi",
    )
    args = parser.parse_args()

    pcm = load_robot_pcm(args.wav)
    duration = len(pcm) / (ROBOT_SAMPLE_RATE * ROBOT_CHANNELS * SAMPLE_WIDTH_BYTES)
    print(f"Streaming {args.wav.name} ({duration:.2f}s)")

    ChannelFactoryInitialize(0, args.network_interface)
    audio = AudioClient()
    audio.SetTimeout(10.0)
    audio.Init()

    code, volume = audio.GetVolume()
    if code != 0:
        raise RuntimeError(f"Could not communicate with audio service, GetVolume code={code}")
    print(f"Robot speaker volume: {volume}")

    try:
        stream_pcm_realtime(audio, pcm, args.app_name)
    finally:
        audio.PlayStop(args.app_name)


if __name__ == "__main__":
    main()
