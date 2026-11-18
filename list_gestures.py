#!/usr/bin/env python3
import argparse
import json

from unitree_sdk2py.core.channel import ChannelFactoryInitialize

try:
    from app.r1_arm_actions import R1ArmActionClient
except ImportError:
    from unitree_sdk2py.rpc.client import Client

    ARM_ACTION_SERVICE_NAME = "arm"
    ARM_ACTION_API_VERSION = "1.0.0.0"
    ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION = 7106
    ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST = 7107
    ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION = 7108
    ROBOT_API_ID_ARM_ACTION_STOP_CUSTOM_ACTION = 7113

    class R1ArmActionClient(Client):
        def __init__(self):
            super().__init__(ARM_ACTION_SERVICE_NAME, False)

        def Init(self):
            self._SetApiVerson(ARM_ACTION_API_VERSION)
            self._RegistApi(ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION, 0)
            self._RegistApi(ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST, 0)
            self._RegistApi(ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION, 0)
            self._RegistApi(ROBOT_API_ID_ARM_ACTION_STOP_CUSTOM_ACTION, 0)

        def ExecuteAction(self, action_id):
            parameter = json.dumps({"action_id": action_id})
            code, _ = self._Call(ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION, parameter)
            return code

        def ExecuteCustomAction(self, action_name):
            parameter = json.dumps({"action_name": action_name})
            code, _ = self._Call(ROBOT_API_ID_ARM_ACTION_EXECUTE_CUSTOM_ACTION, parameter)
            return code

        def StopCustomAction(self):
            code, _ = self._Call(ROBOT_API_ID_ARM_ACTION_STOP_CUSTOM_ACTION, "")
            return code

        def GetActionList(self):
            code, data = self._Call(ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST, "")
            if code != 0:
                return code, None
            return code, json.loads(data)


ROBOT_INTERFACE = "en6"
RELEASE_ARM_ID = 99

ERRORS = {
    7399: "Internal error on the server side.",
    7400: "The rt/arm_sdk topic is occupied, or another action is running.",
    7401: "The arm is holding a pose. Send release action 99 or repeat the same action.",
    7402: "Invalid action id. Use --list to check supported actions.",
    7403: "Failed to load the action file, or the custom action does not exist.",
    7404: "The action cannot be triggered in the current FSM state.",
    7405: "A custom action with the same name already exists.",
    7406: "Battery too low.",
    7407: "Some motor is in an error state.",
}


def normalize_action_list(result):
    if isinstance(result, tuple):
        code, actions = result
        if code != 0:
            raise RuntimeError(f"GetActionList failed: {code} - {ERRORS.get(code, 'Unknown error')}")
    else:
        actions = result

    if isinstance(actions, str):
        actions = json.loads(actions)

    presets = actions[0] if actions else []
    custom = actions[1] if len(actions) > 1 else []
    return presets, custom


def print_actions(presets, custom):
    print("Preset R1 gestures:")
    for action in presets:
        print(f"  {action['id']:>3}  {action['name']}")

    if custom:
        print("\nCustom R1 gestures:")
        for action in custom:
            time_text = f" ({action['time']}s)" if "time" in action else ""
            print(f"  {action['name']}{time_text}")


def find_preset_by_name(presets, name):
    wanted = name.strip().lower()
    for action in presets:
        if action["name"].lower() == wanted:
            return action
    return None


def call_checked(label, code):
    if code != 0:
        raise RuntimeError(f"{label} failed: {code} - {ERRORS.get(code, 'Unknown error')}")


def execute_preset(arm, action_id):
    call_checked(f"Execute action {action_id}", arm.ExecuteAction(action_id))
    if action_id != RELEASE_ARM_ID:
        print(f"Action {action_id} finished. Use --id {RELEASE_ARM_ID} if the arm is holding the pose.")


def execute_custom(arm, action_name):
    if not hasattr(arm, "ExecuteCustomAction"):
        raise RuntimeError("This R1 arm client does not expose ExecuteCustomAction.")
    call_checked(f"Execute custom action {action_name}", arm.ExecuteCustomAction(action_name))


def run_interactive(arm, presets, custom):
    print_actions(presets, custom)
    print("\nEnter an id, preset name, custom name, 'list', 'release', 'stop', or 'q'.")

    while True:
        choice = input("> ").strip()
        if choice in {"q", "quit", "exit"}:
            return
        if choice == "list":
            print_actions(presets, custom)
            continue
        if choice == "release":
            execute_preset(arm, RELEASE_ARM_ID)
            continue
        if choice == "stop":
            if not hasattr(arm, "StopCustomAction"):
                print("StopCustomAction is not available with this client.")
                continue
            call_checked("Stop custom action", arm.StopCustomAction())
            continue

        try:
            execute_preset(arm, int(choice))
            continue
        except ValueError:
            pass

        preset = find_preset_by_name(presets, choice)
        if preset:
            execute_preset(arm, preset["id"])
            continue

        if any(action["name"] == choice for action in custom):
            execute_custom(arm, choice)
            continue

        print("No matching gesture.")


def main():
    parser = argparse.ArgumentParser(description="List and run available R1 gestures.")
    parser.add_argument(
        "network_interface",
        nargs="?",
        default=ROBOT_INTERFACE,
        help=f"DDS network interface connected to the robot, default: {ROBOT_INTERFACE}",
    )
    command = parser.add_mutually_exclusive_group()
    command.add_argument("--list", action="store_true", help="List available gestures and exit.")
    command.add_argument("--id", type=int, help="Run a preset gesture by id.")
    command.add_argument("--name", help="Run a preset gesture by name, or a custom gesture by exact name.")
    command.add_argument("--stop", action="store_true", help="Stop the current custom gesture.")
    parser.add_argument("--yes", action="store_true", help="Do not ask for safety confirmation.")
    args = parser.parse_args()

    if not args.list and not args.yes:
        print("WARNING: Make sure the robot has clear space before moving its arms.")
        input("Press Enter to continue...")

    ChannelFactoryInitialize(0, args.network_interface)

    arm = R1ArmActionClient()
    arm.SetTimeout(30.0)
    arm.Init()

    if args.stop:
        if not hasattr(arm, "StopCustomAction"):
            raise RuntimeError("This R1 arm client does not expose StopCustomAction.")
        call_checked("Stop custom action", arm.StopCustomAction())
        return

    presets, custom = normalize_action_list(arm.GetActionList())

    if args.list:
        print_actions(presets, custom)
    elif args.id is not None:
        execute_preset(arm, args.id)
    elif args.name:
        preset = find_preset_by_name(presets, args.name)
        if preset:
            execute_preset(arm, preset["id"])
        else:
            execute_custom(arm, args.name)
    else:
        run_interactive(arm, presets, custom)


if __name__ == "__main__":
    main()
