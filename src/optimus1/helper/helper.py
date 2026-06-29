import logging

from rich.progress import Progress, TaskID

from .jarvis_craft_helper import *
from .jarvis_equip_helper import *
from .jarvis_smelt_helper import *


class Helper:
    def __init__(self, env):
        self.env = env  # [PRELOAD-SKIP] store env for inventory pre-check
        self.craft_helper = CraftHelper(env)
        self.equip_helper = EquipHelper(env)
        self.smelt_helper = SmeltHelper(env)

    def reset(self, task: str, pbar: Progress, task_id: TaskID, logger: logging.Logger):
        if "equip" in task:
            return self.equip_helper.set_arguments(task, pbar, task_id, logger)
        elif "craft" in task:
            return self.craft_helper.set_arguments(task, pbar, task_id, logger)
        elif "smelt" in task:
            return self.smelt_helper.set_arguments(task, pbar, task_id, logger)
        elif "replan" in task:
            return self.replan_helper.set_arguments(task, pbar, task_id, logger)

    def get_task_steps(self, task: str):
        if "equip" in task:
            return self.equip_helper.steps
        elif "craft" in task:
            return self.craft_helper.steps
        elif "smelt" in task:
            return self.smelt_helper.steps
        elif "replan" in task:
            return self.replan_helper.steps
        else:
            return -1

    def step(self, task: str, goal: tuple):
        # [PRELOAD-SKIP] If goal already satisfied in current inventory, return done.
        try:
            item, count = goal[0], goal[1]
            env_type = type(self.env).__name__
            has_sm = hasattr(self.env, "status_mod")
            inv = None
            if has_sm:
                inv = getattr(self.env.status_mod, "inventory", None)
            inv_type = type(inv).__name__
            inv_keys = list(inv.keys())[:8] if isinstance(inv, dict) else "n/a"
            inv_count = inv.get(item, 0) if isinstance(inv, dict) else "n/a"
            print(f"[PRELOAD-CHECK] task={task!r} goal=({item},{count}) "
                  f"env={env_type} status_mod={has_sm} inv_type={inv_type} "
                  f"inv_has_{item}={inv_count} inv_keys_sample={inv_keys}")
            if isinstance(inv, dict) and inv.get(item, 0) >= count:
                print(f"[PRELOAD-SKIP] {task}: have {inv.get(item,0)} {item} >= {count}; skipping dispatch")
                return True, {"preload_skip": True}
        except Exception as _e:
            print(f"[PRELOAD-CHECK-ERR] {type(_e).__name__}: {_e}")
        if "equip" in task:
            return self.equip_helper.equip_item(goal[0])
        elif "craft" in task:
            return self.craft_helper.crafting(goal[0], goal[1])
        elif "smelt" in task:
            return self.smelt_helper.smelting(goal[0], goal[1])
        elif "replan" in task:
            if goal[0] == "tower":
                return self.replan_helper.build_tower()
            elif goal[0] == "land":
                return self.replan_helper.go_to_land()
        else:
            return False, "not support"
