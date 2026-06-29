import json
import logging
import os
import threading
from typing import Any, Dict, List

import shortuuid
from omegaconf import DictConfig
from thefuzz import process

from ..util.prompt import render_replan_example
from ..util.thread import MultiThreadServerAPI

from .graph import KnowledgeGraph

# === OUR MEMORY BANK ===
import os as _os
_MB_PATH = _os.path.join(_os.path.dirname(__file__), "v1", "memory_bank_v3.json")
_KG_DATA_PATH = _os.path.join(_os.path.dirname(__file__), "kg_data")
try:
    from .our_graph import MinecraftKnowledgeGraph as OurGraph
    _OUR_GRAPH = OurGraph(_KG_DATA_PATH) if _os.path.exists(_KG_DATA_PATH) else None
except Exception:
    _OUR_GRAPH = None
try:
    with open(_MB_PATH, 'r') as _f:
        _MEMORY_BANK = json.load(_f)
except Exception:
    _MEMORY_BANK = None
# === END OUR MEMORY BANK ===

REPLAN_EXAMPLE_FORMAT = """
<task>: {}
<error>: {}
<replan>:
{}
"""


PLAN_EXAMPLE_FORMAT = """
<task>: {}.
<visual info>
{}
<craft graph>:
{}
<task planning>
{}
"""


class Memory:
    plan_dir_path: str
    reflection_dir_path: str
    replan_dir_path: str
    experience_dir_path: str | None = None

    root_path: str

    crafting_graph: KnowledgeGraph

    current_environment: str = ""

    all_reflection_memory: List[str]

    _lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        cfg: DictConfig,
        logger: logging.Logger | None = None,
        life_long_learning: bool = False,
    ) -> None:
        self.cfg = cfg
        self.version = self.cfg["version"]

        self.logger = logger

        self.root_path = self.cfg["memory"]["path"]

        os.makedirs(self.root_path, exist_ok=True)

        self.plan_dir_path = os.path.join(
            self.root_path, self.cfg["memory"]["plan"]["path"]
        )
        os.makedirs(self.plan_dir_path, exist_ok=True)
        self.reflection_dir_path = os.path.join(
            self.root_path, self.cfg["memory"]["reflection"]["path"]
        )
        os.makedirs(self.reflection_dir_path, exist_ok=True)
        os.makedirs(os.path.join(self.reflection_dir_path, "img"), exist_ok=True)

        self.replan_dir_path = os.path.join(
            self.root_path, self.cfg["memory"]["replan"]["path"]
        )
        os.makedirs(self.replan_dir_path, exist_ok=True)

        self.life_long_learning = life_long_learning

        self.all_reflection_memory = [
            file
            for file in os.listdir(self.reflection_dir_path)
            if file.endswith(".json")
        ]

        self.crafting_graph = KnowledgeGraph(
            life_long_learning=life_long_learning,
        )

    def save_plan(
        self,
        task: str,
        visual_info: str,
        goal: str,
        status: str,
        planning: List[Dict[str, Any]],
        steps: int | float,
        video_file: MultiThreadServerAPI | None = None,
        environment: str = "none",
        failure_metadata: dict | None = None,
    ):
        thread = MultiThreadServerAPI(
            self._save_plan,
            args=(
                task,
                visual_info,
                goal,
                status,
                planning,
                steps,
                video_file,
                environment,
                failure_metadata,
            ),
        )
        thread.start()
        return thread

    def _save_plan(
        self,
        task: str,
        visual_info: str,
        goal: str,
        status: str,
        planning: List[Dict[str, Any]],
        steps: int | float,
        video_file: MultiThreadServerAPI | None = None,
        environment: str = "none",
        failure_metadata: dict | None = None,
    ):
        assert status in [
            "success",
            "failed",
        ], "status should be one of success, failed"
        file_name = self.cfg["memory"]["plan"]["file"].replace(
            "<task>", task.replace(" ", "_")
        )

        memory_path = self.plan_dir_path.replace("<status>", status)
        os.makedirs(memory_path, exist_ok=True)

        memory_file = os.path.join(memory_path, file_name)

        if self.logger:
            self.logger.info(
                f"[hot_pink]store plan of {task} to {memory_file} :smile:[/hot_pink]"
            )
        with self._lock:
            if os.path.exists(memory_file):
                with open(memory_file, "r") as fp:
                    memory = json.load(fp)
            else:
                memory = {"plan": []}
        vf = ""
        if video_file is not None:
            video_file.join()
            vf = video_file.get_result()
        with self._lock, open(memory_file, "w") as fp:
            entry = {
                "id": shortuuid.uuid(),
                "environment": environment,
                "visual_info": visual_info,
                "goal": goal,
                "video": vf,
                "planning": planning,
                "status": status,
                "steps": steps,
            }
            if failure_metadata is not None and status == "failed":
                entry["failure_metadata"] = failure_metadata
            from datetime import datetime as _dt
            entry["saved_at"] = _dt.utcnow().isoformat(timespec="seconds") + "Z"
            memory["plan"].append(entry)
            json.dump(memory, fp, indent=2)

    def save_reflection(
        self, task: str, env_name: str, reflection_type: str, img_old: str, img_new: str
    ):
        assert reflection_type in [
            "done",
            "continue",
            "replan",
        ], "reflection type should be one of done, continue, replan"

        file_name = self.cfg["memory"]["reflection"]["file"].replace(
            "<task>", task.replace(" ", "_")
        )

        dir = self.reflection_dir_path
        img_dir = os.path.join(dir, self.cfg["memory"]["reflection"]["img_path"])

        os.makedirs(dir, exist_ok=True)
        os.makedirs(img_dir, exist_ok=True)

        memory_file = os.path.join(dir, file_name)
        with self._lock:
            if self.logger:
                self.logger.info(
                    f"[hot_pink]store reflection of {task}:{reflection_type} to {memory_file} :smile:[/hot_pink]"
                )

            if os.path.exists(memory_file):
                with open(memory_file, "r") as fp:
                    memory = json.load(fp)
            else:
                memory = {}

            if env_name not in memory:
                memory[env_name] = {"done": [], "continue": [], "replan": []}

            memory[env_name][reflection_type].append([img_old, img_new])

            with open(memory_file, "w") as fp:
                json.dump(memory, fp, indent=2)

    def save_replan(
        self, task: str, error_info: str, new_planning: List[Dict[str, Any]]
    ):
        file_name = self.cfg["memory"]["replan"]["file"].replace(
            "<task>", task.replace(" ", "_")
        )

        dir = self.replan_dir_path
        os.makedirs(dir, exist_ok=True)

        memory_file = os.path.join(dir, file_name)
        with self._lock:
            if self.logger:
                self.logger.info(
                    f"store replan of {task} because of {error_info} to {memory_file} :smile:"
                )

            if os.path.exists(memory_file):
                with open(memory_file, "r") as fp:
                    memory = json.load(fp)
            else:
                memory = {}

            if error_info not in memory:
                memory[error_info] = []

            memory[error_info].append(new_planning)

            with open(memory_file, "w") as fp:
                json.dump(memory, fp, indent=2)

    def retrieve_plan(self, task: str):
        """Combined retrieval: memory_bank (canonical) + AMEP (recent trajectory).

        Memory_bank provides the structurally correct plan from the JARVIS-1
        knowledge base. AMEP provides the closest past trajectory's visual
        context. When both hit, memory_bank's plan structure wins (it's
        authoritative); AMEP contributes visual_info. When only one hits, we
        use whichever is available.
        """
        task_key = task.replace(" ", "_").lower()
        has_done = False

        # ---------- AMEP retrieval (visual_info + fallback plan) ----------
        amep_visual_info = "None"
        amep_plan = None
        amep_goal = ""
        try:
            from optimus1.amep import retrieve_for_task
            amep_env = getattr(self, "current_environment", "") or ""
            amep_result = retrieve_for_task(
                task=task,
                environment=amep_env,
                initial_inventory={},
                scorer_kind="rule",
                k_success=3,
            )
            if amep_result.has_any() and amep_result.successes:
                best = amep_result.best_success()
                amep_plan = best.record.planning
                amep_visual_info = best.record.visual_info or "None"
                amep_goal = best.record.goal or (
                    amep_plan[-1].get("goal", [""])[0] if amep_plan else ""
                )
                print(
                    f"[AMEP] task={task!r}: retrieved {best.record.steps}-step "
                    f"past success (score={best.score:.2f})"
                )
        except FileNotFoundError:
            pass
        except Exception as _e:
            print(f"[AMEP] retriever failed ({type(_e).__name__}: {_e})")

        # ---------- Memory bank lookup (canonical plan, authoritative) ----------
        mb_plan = None
        mb_task_key = task_key
        if _MEMORY_BANK is not None:
            mb_entry = _MEMORY_BANK.get(task_key)
            if mb_entry is None:
                for prefix in ["craft_a_", "craft_an_", "craft_", "smelt_a_",
                               "smelt_", "mine_", "chop_a_", "chop_",
                               "dig_down_to_mine_", "dig_down_and_mine_a_"]:
                    if task_key.startswith(prefix):
                        candidate = task_key[len(prefix):]
                        if candidate in _MEMORY_BANK:
                            mb_entry = _MEMORY_BANK[candidate]
                            mb_task_key = candidate
                            break
            if mb_entry is None:
                best = process.extractOne(task_key, list(_MEMORY_BANK.keys()))
                if best and best[1] > 60:
                    mb_entry = _MEMORY_BANK[best[0]]
                    mb_task_key = best[0]
            if mb_entry and mb_entry.get("plans"):
                mb_plan = mb_entry["plans"][0]["steps"]

        # ---------- Combine and render ----------
        # Priority: memory_bank for plan structure (canonical), AMEP for visual.
        if mb_plan:
            has_done = True
            render_plan = {}
            for idx, p in enumerate(mb_plan):
                goal_dict = p.get("goal", {})
                if goal_dict:
                    goal_name = list(goal_dict.keys())[0]
                    goal_qty = list(goal_dict.values())[0]
                else:
                    goal_name = p.get("text", "")
                    goal_qty = 1
                task_verb = p.get("type", "craft")
                task_text = p.get("text", goal_name)
                render_plan[f"step {idx+1}"] = {
                    "task": f"{task_verb} {task_text}",
                    "goal": [goal_name, goal_qty],
                }
            visual_info = amep_visual_info  # may be "None" if AMEP missed
            examples = PLAN_EXAMPLE_FORMAT.format(
                mb_task_key.replace("_", " "),
                visual_info,
                self.retrieve_graph(mb_task_key),
                json.dumps(render_plan),
            )
            print(
                f"[MEMORY] task={task!r}: memory_bank canonical plan "
                f"({len(mb_plan)} steps)"
                + (f" + AMEP visual context" if amep_visual_info != "None" else "")
            )
            return examples, True

        # Memory bank missed; fall back to AMEP plan if it has one
        if amep_plan:
            has_done = True
            render_plan = {}
            for idx, p in enumerate(amep_plan):
                render_plan[f"step {idx+1}"] = p
            examples = PLAN_EXAMPLE_FORMAT.format(
                task_key.replace("_", " "),
                amep_visual_info,
                self.retrieve_graph(amep_goal),
                json.dumps(render_plan),
            )
            print(f"[AMEP-only] task={task!r}: memory_bank missed, "
                  f"using AMEP retrieval ({len(amep_plan)} steps)")
            return examples, True

        # Both missed
        print(f"[NO-RETRIEVAL] task={task!r}: no memory_bank or AMEP match")
        return "", has_done

    def retrieve_reflection(self, task: str):
        import random

        from thefuzz import process

        def get_best_match_recipe(target: str, choices):
            res = process.extractOne(target, choices)
            return res[0] if res is not None else None

        def add_dir(path_lst):
            return [os.path.join(self.reflection_dir_path, "img", p) for p in path_lst]

        similar_task = get_best_match_recipe(
            task.replace(" ", "_") + ".json", self.all_reflection_memory
        )
        if similar_task is None:
            return None, None, None
        with open(os.path.join(self.reflection_dir_path, similar_task), "r") as fi:
            similar_task_reflct = json.load(fi)
        envs = list(similar_task_reflct.keys())
        similar_envs = get_best_match_recipe(self.current_environment, envs)
        reflection = similar_task_reflct[similar_envs]
        done, cont, replan = (
            reflection["done"],
            reflection["continue"],
            reflection["replan"],
        )
        if len(done) > 0:
            done = random.choice(done)
        if len(cont) > 0:
            cont = random.choice(cont)
        if len(replan) > 0:
            replan = random.choice(replan)
        return add_dir(done), add_dir(cont), add_dir(replan)

    def retrieve_replan(self, task: str, error_info: str, number: int = 1) -> str:
        task = task.replace(" ", "_")

        if os.path.exists(self.replan_dir_path) is False:
            return ""

        examples = []
        for replan_exper in os.listdir(self.replan_dir_path):
            if task in replan_exper:
                with open(os.path.join(self.replan_dir_path, replan_exper), "r") as fi:
                    data = json.load(fi)
                if error_info in data:
                    result = data[error_info][0]
                    examples.append(
                        REPLAN_EXAMPLE_FORMAT.format(
                            task, error_info, render_replan_example(result)
                        )
                    )
                if len(examples) == number:
                    break
        return "\n".join(examples).strip()

    def retrieve_graph(self, item: str, number: int = 1) -> str:
        # Raw materials - no crafting needed
        raw_items = {"iron_ore", "logs", "cobblestone", "redstone", "sand", "coal_ore",
                     "diamond", "gold_ore", "log", "oak_log", "birch_log", "jungle_log",
                     "acacia_log", "white_wool", "wool", "leather", "string", "chicken",
                     "beef", "porkchop", "mutton", "apple", "sugar_cane"}
        if item in raw_items:
            return "Just mine/collect it!"

        # === TRY OUR GRAPH FIRST ===
        if _OUR_GRAPH is not None:
            try:
                result = _OUR_GRAPH.compile_for_planner(item.replace(" ", "_"), number)
                if result:
                    print(f"[OUR GRAPH] {item}")
                    return result
            except Exception as e:
                print(f"[OUR GRAPH] Error for {item}: {e}")
        # === END OUR GRAPH ===

        # Fallback to original graph
        try:
            item = item.replace("logs", "log")
            return self.crafting_graph.compile(item.replace(" ", "_"), number)
        except Exception as e:
            return f"craft {number} {item}: recipe not found"
