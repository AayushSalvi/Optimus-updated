import json
import logging
import os
import re
from typing import Any, Dict

import hydra
import shortuuid
from omegaconf import DictConfig, OmegaConf
from rich.progress import Progress, TaskID, TimeElapsedColumn

from optimus1.env import CustomEnvWrapper, env_make, register_custom_env
from optimus1.example import golden_sword, iron_sword, stone_sword, wooden_pickaxe
from optimus1.helper import Helper
from optimus1.memories import Memory


from optimus1.monitor import Monitors, StepMonitor, SuccessMonitor
from optimus1.util import (
    PlanList,
    PlanManager,
    ServerAPI,
    base64_to_img,
    get_evaluate_task,
    get_logger,
    pretty_result,
    render_gpt4_plan,
    render_reflection,
    save_obs,
)


MINUTE = 1200
visual_info = ""

EXAMPLE = golden_sword
REFLECTION_IMAGE_ROOT = ""


def set_pbar_total(pbar: Progress, task_id: TaskID, total: int):
    pbar.tasks[task_id].total = total


def get_info_from_plan(data):
    # Extract goal inference
    goal, visual_info, env = "", "", ""
    goal_match = re.search(r"<goal inference>:\s*(.*?)\s*(?=<)", data)
    if goal_match:
        goal = goal_match.group(1).strip()

    # Extract visual inference, including everything until the end of the string
    visual_match = re.search(
        r"<visual inference>(.*?)(?=<goal inference>|$)", data, re.DOTALL
    )
    if visual_match:
        visual_info = visual_match.group(1).strip()

    # Extract environment content specifically
    environment_match = re.search(r"environment:\s*(.*)", data)
    if environment_match:
        env = environment_match.group(1).strip()

    return goal, visual_info, env



# === Progress Ledger imports ===
from optimus1.progress_ledger import (
    init_ledger as _ledger_init,
    detect_key_nodes as _ledger_detect,
    compute_world_delta as _ledger_compute_delta,
    StepRecord as _LedgerStepRecord,
    make_call_llm as _ledger_make_call_llm,
)
_LEDGER_CALL_LLM = None
def _ledger_get_call_llm():
    global _LEDGER_CALL_LLM
    if _LEDGER_CALL_LLM is None:
        _LEDGER_CALL_LLM = _ledger_make_call_llm()
    return _LEDGER_CALL_LLM
# === End Progress Ledger imports ===


def agent_do(
    cfg: DictConfig,
    env: CustomEnvWrapper,
    logger: logging.Logger,
    monitors: Monitors,
    planning: PlanList,
    reset_obs: Dict[str, Any],
    memory_bank: Memory,
    ledger=None,
):
    helper = Helper(env)
    obs = reset_obs

    final_goal = planning[-1]

    with Progress(
        *Progress.get_default_columns(),
        TimeElapsedColumn(),
        "{task.completed} of {task.total}",
        expand=True,
    ) as pbar:
        num_step = pbar.add_task("[cyan]Running...", total=env.timeout)
        all_task = pbar.add_task("[purple]Task: {}...", total=len(planning))

        progress = 0
        game_over = False

        plan_manager = PlanManager(planning)
        current_plan = plan_manager.next_plan
        # [SPATIAL MEMORY] persistent store of where resources are found (Component 1)
        from optimus1.spatial_memory import SpatialMemory
        spatial = SpatialMemory()
        try:
            spatial.set_episode(str(final_goal))
        except Exception:
            spatial.set_episode("unknown")
        # [STAGNATION GUARD] detect wander stalls during gathering (Component 3)
        from optimus1.stagnation_guard import StagnationGuard
        stagnation = StagnationGuard()

        _replan_count = 0
        _REPLAN_CAP = 6
        _craft_step_total = 0
        _CRAFT_STEP_CAP = 14000
        while current_plan is not None:
            # [REPLAN-CAP] Bound the replan loop. A helper that false-reports a
            # missing material (e.g. an equipped/placed crafting_table the
            # label-reader can't see) otherwise triggers unbounded
            # replan -> re-gather -> re-craft cycles until budget death.
            if _replan_count > _REPLAN_CAP:
                logger.warning(f"[red][REPLAN-CAP] exceeded {_REPLAN_CAP} replans; ending episode as failed[/red]")
                status = "failed"
                break
            # [LEDGER] snapshot inventory + position before this sub-task
            _ledger_pre_inv = dict(env.status_mod.inventory) if (ledger is not None and hasattr(env, "status_mod")) else {}
            _ledger_pre_loc = dict(env.status_mod.location_stats) if (ledger is not None and hasattr(env, "status_mod")) else {}
            _ledger_pre_equip = env.status_mod.equipment if (ledger is not None and hasattr(env, "status_mod")) else "none"
            task, goal = current_plan["task"], current_plan["goal"]
            if goal[0] == "log":
                goal[0] = "logs"
            pbar.tasks[all_task].description = f"[purple]Task: {task}..."
            pbar.tasks[num_step].description = f"[cyan]Running... {final_goal}"

            temp_task = task
            if "punch" in task:
                task = task.replace("punch", "chop")
            op = task.split(" ")[0]

            if "create" in task:
                op = "craft"

            logger.info(f"[yellow]Current Task: {task}, Goal: {goal}[/yellow]")

            if op in ["craft", "smelt", "equip"] or "smelt" in task:
                if not env.can_change_hotbar:
                    env.can_change_hotbar = True
                if not env.can_open_inventory:
                    env.can_open_inventory = True
                helper.reset(task, pbar, num_step, logger)
                try:
                    done, info = helper.step(task, goal)  # type: ignore
                except RuntimeError as _craft_err:
                    # [CRAFT-CRASH WRAPPER] env terminated mid-craft (budget overflow
                    # or env death). Mark sub-task failed; do NOT crash the whole sweep.
                    _errs = str(_craft_err)
                    # Dead-env errors are terminal: the episode is over, retrying just
                    # spins on a corpse. Re-raise so the outer loop ends the run cleanly.
                    if "done=True" in _errs or "bytes-like object" in _errs:
                        logger.warning(f"[red]helper.step: env is dead ({_errs}); terminating episode[/red]")
                        raise
                    # Otherwise a recoverable craft miss: mark failed, let loop replan.
                    logger.warning(f"[red]helper.step crashed: {_errs}; treating as failed sub-task[/red]")
                    done, info = False, f"craft_crash: {_errs}"
                steps = helper.get_task_steps(task)

                env.can_open_inventory = False
                env.can_change_hotbar = False

                monitors.update(f"{task}_{progress}", done, steps)
                if not done:
                    # [CRAFT-STEP-CAP] Bound a single sub-task by STEP count, not
                    # attempt count. Multi-cell crafts (furnace=8 cobblestone) can
                    # legitimately need thousands of steps and many internal retries
                    # before landing (measured: successful furnace ~7.5k steps). An
                    # attempt-count cap killed these prematurely. Only bail when a
                    # single sub-task exceeds the step ceiling (truly stuck).
                    _craft_step_total += steps
                    logger.warning(f"[red][CRAFT-STEP-CAP] {task} failed; sub-task steps={_craft_step_total}/{_CRAFT_STEP_CAP}[/red]")
                    if _craft_step_total > _CRAFT_STEP_CAP:
                        logger.warning(f"[red][CRAFT-STEP-CAP] exceeded on {task}; ending episode as failed[/red]")
                        status = "failed"
                        break
                if done:
                    _craft_step_total = 0
                    logger.info(f"[green]{task} Success[/green]!")
                    progress += 1
                    pbar.update(all_task, advance=1)
                    # [LEDGER] update on craft/smelt/equip success
                    if ledger is not None:
                        try:
                            _post_inv = dict(env.status_mod.inventory)
                            _post_loc = dict(env.status_mod.location_stats)
                            _post_equip = env.status_mod.equipment
                            _delta = _ledger_compute_delta(
                                inv_before=_ledger_pre_inv,
                                inv_after=_post_inv,
                                loc_before=_ledger_pre_loc,
                                loc_after=_post_loc,
                                equipped_before=_ledger_pre_equip,
                                equipped_after=_post_equip,
                            )
                            _states = {o.id: ledger.outcome_cache.get_state(o.id) for o in ledger.required_outcomes}
                            _kns = _ledger_detect(
                                step_idx=env.num_steps,
                                required_outcomes=ledger.required_outcomes,
                                current_outcome_states=_states,
                                world_delta=_delta,
                                actor_action_summary=f"completed sub-task: {task}",
                                call_llm=_ledger_get_call_llm(),
                            )
                            _step_rec = _LedgerStepRecord(
                                step_idx=env.num_steps,
                                inventory=_post_inv,
                                actor_action_summary=f"completed sub-task: {task}",
                                key_nodes=_kns,
                            )
                            ledger.apply_step_keynodes(_step_rec)
                            logger.info(f"[cyan][LEDGER] After {task!r}: pending={ledger.pending()}, all_done={ledger.all_done()}[/cyan]")
                        except Exception as _e:
                            logger.warning(f"[LEDGER] update failed: {_e}")

                else:
                    assert (
                        info is not None
                    ), "info should not be None! Because equip/craft/smelt failed!"

                    if "time" in info.lower():
                        game_over = True
                        break
                    logger.warning(
                        f"[red]:warning: {task} failed... Beacuse {info}[/red]"
                    )

                    examples = memory_bank.retrieve_replan(task, info)
                    logger.info(f"Examples: {examples}")
                    # craft graph info: missing material: {'planks': 1, 'crafting_table': 1}
                    try:
                        materials = json.loads(info[18:])
                    except Exception:
                        continue
                    cg = []
                    for item, num in materials.items():
                        cg.append(memory_bank.retrieve_graph(item, num))
                    graph_summary = "\n".join(cg)
                    logger.info(f"Craft Graph: {graph_summary}")
                    # [LEDGER] inject working-memory state into replan prompt
                    if ledger is not None:
                        try:
                            graph_summary = (graph_summary or "") + "\n\n" + ledger.to_prompt_block()
                        except Exception as _e:
                            logger.warning(f"[LEDGER] inject into replan failed: {_e}")
                    replan = ServerAPI.get_plan(
                        cfg["server"], obs, task, info, examples, graph_summary
                    )

                    new_planning = render_gpt4_plan(replan, is_replan=True)
                    if new_planning[-1]["task"] != task:
                        new_planning.append(current_plan)
                    _replan_count += 1
                    plan_manager.insert_plan(new_planning, is_replan=True)

                    set_pbar_total(pbar, all_task, len(plan_manager.all))

                    logger.warning(f"[yellow]Replanning...\n{new_planning}[/yellow]")
                    # save replan
                    env.save_video(task, "failed", True)
                    memory_bank.save_replan(task, info, new_planning)
            else:
                # [STAGNATION GUARD] reset window for this gather sub-task
                try:
                    _tgt = goal[0]
                    _tgt_now = env.status_mod.inventory.get(_tgt, 0) if hasattr(env, "status_mod") else 0
                    stagnation.reset_for_task(_tgt, _tgt_now)
                except Exception:
                    pass
                while True:
                    if "explore" in env.cache and env.cache["explore"] > 0:
                        task = f"explore to find {goal[0]}"
                        env.cache["explore"] -= 1
                    else:
                        task = temp_task
                    env._only_once = True
                    # ============ 2. do action =====================
                    action = ServerAPI.get_action(
                        cfg["server"], obs, task, step=env.num_steps
                    )
                    try:
                        obs, reward, game_over, info = env.step(action, goal)
                    except RuntimeError as _env_err:
                        # [CRASH WRAPPER] MineRL raises "Attempted to step an
                        # environment server with done=True" when the env dies
                        # mid-task. Treat as terminal failure so the run records
                        # a status instead of crashing to NO_OUTPUT.
                        logger.warning(f"[red]Env terminated mid-step ({_env_err}); ending episode as failed.[/red]")
                        game_over = True
                        break
                    # [SPATIAL MEMORY] record any resource obtained this step at current (x,y,z)
                    try:
                        if hasattr(env, "status_mod"):
                            _rec = spatial.record_from_status(env.status_mod, step=env.num_steps)
                            if _rec:
                                logger.info(f"[blue][SPATIAL] recorded {_rec} @ {env.status_mod.get_position()}[/blue]")
                    except Exception as _se:
                        pass
                    # [STAGNATION GUARD] if wandering in place without progress, trigger explore
                    try:
                        if hasattr(env, "status_mod"):
                            _tgt = goal[0]
                            _tgt_now = env.status_mod.inventory.get(_tgt, 0)
                            _pos = env.status_mod.get_position()
                            if stagnation.update(env.num_steps, _pos, _tgt_now):
                                env.cache["explore"] = env.cache.get("explore", 0) + 200
                                logger.warning(f"[red][STAGNATION] stuck on {_tgt} @ {_pos}; triggering explore (200 steps)[/red]")
                    except Exception:
                        pass
                    pbar.update(num_step, advance=1)
                    monitors.update(f"{task}_{progress}", env.current_task_finish)

                    if env.api_thread is not None and not env.api_thread_is_alive():
                        logger.info("[yellow]Reflection finish.[/yellow]")
                        # reflection finish
                        result = env.api_thread_get_result()

                        # assert result is not None, "Reflection result is None!"
                        env.api_thread = None
                        if result is not None:
                            logger.info(result[0])
                            try:
                                env_name, situation, replan_type = render_reflection(
                                    result[0]
                                )
                            except Exception:
                                continue
                            old_obs = result[1]

                            # img get & save
                            img_file_format = f"{task}_{env_name}_{situation}_<new>_{shortuuid.uuid()}.jpg"
                            img_new = img_file_format.replace("<new>", "new")
                            img_old = img_file_format.replace("<new>", "old")
                            base64_to_img(
                                old_obs, os.path.join(REFLECTION_IMAGE_ROOT, img_old)
                            )
                            save_obs(
                                env.cache.pop("obs"),
                                os.path.join(REFLECTION_IMAGE_ROOT, img_new),
                            )

                            # save reflection to memory
                            memory_bank.save_reflection(
                                task, env_name, situation, img_old, img_new
                            )

                            logger.info(f"[red]Reflection status: {situation}")
                            match situation:
                                case "done" | "continue":
                                    # =========== continue current task =================
                                    pass

                    if game_over:
                        logger.warning("[red]:warning: Timeout![/red]")
                        break
                    # current task success
                    if env.current_task_finish:
                        logger.info(f"[green]{task} Success :smile: [/green]!")
                        progress += 1
                        pbar.update(all_task, advance=1)
                        steps = monitors.get_steps(task)

                        if env.api_thread is not None and env.api_thread_is_alive():
                            # env.api_thread.join()
                            env.api_thread = None
                        break

                    if env.num_steps % MINUTE == 0:
                        logger.warning(f"Current Step: {env.num_steps}")

                        if env.api_thread is not None and env.api_thread_is_alive():
                            env.api_thread = None

                        logger.warning(f"[yellow]Start Reflection: {task}...[/yellow]")
                        done, cont, replan = memory_bank.retrieve_reflection(task)

                        thread = ServerAPI.get_reflection(
                            cfg["server"], obs, done, cont, replan, task, env.num_steps
                        )
                        env.api_thread = thread
                        env.cache["obs"] = obs["pov"]
            if game_over:
                break
            current_plan = plan_manager.next_plan

        # [SPATIAL MEMORY] persist the resource-location store after this task
        try:
            spatial.save()
            logger.info(f"[blue][SPATIAL] saved store: {spatial.summary()}[/blue]")
        except Exception:
            pass
        if len(plan_manager.remain_plans) == 0 and not game_over:
            # [LABELING FIX] Plan exhaustion != goal satisfaction. Gate the
            # success label on the progress ledger's verified-outcome check.
            # Without this, a plan that ends early (e.g. iron task stopping at
            # wooden_axe) is falsely logged as success.
            if ledger is not None and not ledger.all_done():
                logger.info(f"[red]Plan exhausted but goal NOT satisfied. Pending: {ledger.pending()}[/red]")
                status = "failed"
            else:
                logger.info("[green]All tasks are completed![/green]")
                status = "success"
        else:
            logger.info(
                f"[red]Some tasks are not completed![/red] {plan_manager.remain_plans}"
            )
            status = "failed"

    return (status, pbar.tasks[num_step].completed, plan_manager.all)


@hydra.main(version_base=None, config_path="conf", config_name="evaluate")
def main(cfg: DictConfig):
    global REFLECTION_IMAGE_ROOT
    register_custom_env(cfg)

    logger = get_logger(__name__)
    logger.info(OmegaConf.to_yaml(cfg))
    REFLECTION_IMAGE_ROOT = f"src/optimus1/memories/{cfg['version']}/reflection/img"

    env = env_make(cfg["env"]["name"], cfg, logger)

    memory_bank = Memory(cfg, logger)

    if cfg["task"]["interactive"] and cfg["type"] != "headless":
        raise NotImplementedError("Not implemented yet!")

    evaluate_tasks = get_evaluate_task(cfg)
    logger.info(f"Evaluate Tasks: {evaluate_tasks}")

    times = cfg["env"]["times"]
    for task in evaluate_tasks:
        monitors = []

        for _ in range(times):
            t = ServerAPI.reset(cfg["server"])
            logger.info("[red]env & server reset...[/red] ")
            obs = env.reset()
            t.join()


            # [LEDGER] initialize per-episode progress ledger
            ledger = None
            try:
                _init_inv = dict(env.status_mod.inventory) if hasattr(env, "status_mod") else {}
                _init_loc = env.status_mod.location_stats if hasattr(env, "status_mod") else {}
                def _xyz(loc):
                    if not loc:
                        return (0.0, 64.0, 0.0)
                    def _v(k):
                        v = loc.get(k, 0.0)
                        return float(v.item() if hasattr(v, "item") else v)
                    return (_v("xpos"), _v("ypos"), _v("zpos"))
                _init_pos = _xyz(_init_loc)
                _init_equip = env.status_mod.equipment if hasattr(env, "status_mod") else "none"
                ledger = _ledger_init(
                    instruction=task,
                    initial_inventory=_init_inv,
                    initial_position=_init_pos,
                    initial_dimension="overworld",
                    initial_equipped=_init_equip,
                    call_llm=_ledger_get_call_llm(),
                )
                logger.info(f"[cyan][LEDGER] Initialized for task={task!r}: outcomes={[o.id for o in ledger.required_outcomes]}[/cyan]")
            except Exception as _e:
                logger.warning(f"[LEDGER] init failed: {_e}")
                ledger = None
            while True:
                try:
                    retrieval_info = ServerAPI.get_retrieval(cfg["server"], obs, task)
                    goal, visual_info, environment = get_info_from_plan(retrieval_info)
                    # goal, visual_info, environment = "diamond", "full", "forest"
                    print(goal, visual_info, environment)

                    memory_bank.current_environment = environment
                    example, has_done = memory_bank.retrieve_plan(task)
                    print(example, has_done)

                    if example is None:
                        example = EXAMPLE
                    # example = EXAMPLE
                    logger.info(example + str(has_done))
                    graph = memory_bank.retrieve_graph(goal)
                    logger.info(f"Graph: {graph}")

                    if not has_done:
                        # [LEDGER] inject ledger block into initial planner's graph context
                        _graph_with_ledger = graph
                        if ledger is not None:
                            try:
                                _graph_with_ledger = (graph or "") + "\n\n" + ledger.to_prompt_block()
                            except Exception as _e:
                                logger.warning(f"[LEDGER] inject into initial plan failed: {_e}")
                        planning = ServerAPI.get_plan(
                            cfg["server"], obs, task, None, example, _graph_with_ledger, visual_info
                        )
                    else:
                        planning = example
                    planning = render_gpt4_plan(planning)
                    break
                except Exception as e:
                    planning = example
                    planning = render_gpt4_plan(planning)
                    break

            assert planning is not None, "Planning is None!"
            # [CRAFT-TEST] when materials are preloaded (stone_crafttest config),
            # skip gather/intermediate steps; go straight to the final craft.
            try:
                _preload = cfg["env"].get("initial_inventory", []) if hasattr(cfg["env"], "get") else cfg["env"]["initial_inventory"]
                _preloaded_types = {str(it.get("type", "")) for it in _preload} if _preload else set()
                if "wooden_pickaxe" in _preloaded_types and "cobblestone" in _preloaded_types and "stick" in _preloaded_types and len(_preloaded_types) <= 6:
                    planning = [{"task": "craft stone_pickaxe", "goal": ["stone_pickaxe", 1]}]
                    logger.info(f"[yellow][CRAFT-TEST] preloaded inventory detected {_preloaded_types}; overriding plan to single craft step[/yellow]")
            except Exception as _e:
                logger.warning(f"[CRAFT-TEST] override skipped: {_e}")


            # [PLAN-PRUNE] Drop steps already satisfied by current inventory.
            # Canonical plans (from memory_bank_v3 / AMEP) assume empty inventory,
            # so iron+ tiers generate 11-step chains that include preloaded
            # intermediates. Pruning shortens these to 3-5 step plans the craft
            # helper can execute reliably. The final target step is always kept.
            try:
                _inv = {}
                if isinstance(obs, dict) and isinstance(obs.get("inventory"), dict):
                    _inv = obs["inventory"]
                elif hasattr(env, "status_mod") and isinstance(getattr(env.status_mod, "inventory", None), dict):
                    _inv = env.status_mod.inventory
                if isinstance(_inv, dict) and isinstance(planning, list) and len(planning) > 1:
                    _orig = len(planning)
                    _pruned = []
                    for _i, _step in enumerate(planning):
                        _g = _step.get("goal", [None, 0])
                        _g_item, _g_count = _g[0], _g[1]
                        _is_last = (_i == len(planning) - 1)
                        if _is_last or _inv.get(_g_item, 0) < _g_count:
                            _pruned.append(_step)
                        else:
                            logger.info(f"[PLAN-PRUNE] dropped {_step.get('task','?')!r} (have {_inv.get(_g_item,0)} {_g_item} >= {_g_count})")
                    # [PRUNE-CASCADE] Drop orphaned mine-ore steps whose only
                    # consumer (the smelt step) was pruned above. Ores feed smelts
                    # exclusively in these chains; if no surviving step outputs the
                    # corresponding ingot, the mine step is dead weight and would
                    # strand the agent on an impossible gather (spatial blindness).
                    _SMELT_OF = {"iron_ore": "iron_ingot", "gold_ore": "gold_ingot"}
                    _survive_items = set()
                    for _s in _pruned:
                        _sg = _s.get("goal", [None, 0])
                        if _sg and _sg[0]:
                            _survive_items.add(_sg[0])
                    _cascaded = []
                    for _i2, _s in enumerate(_pruned):
                        _sg = _s.get("goal", [None, 0])
                        _item = _sg[0] if _sg else None
                        _is_last2 = (_i2 == len(_pruned) - 1)
                        if (not _is_last2) and _item in _SMELT_OF and _SMELT_OF[_item] not in _survive_items:
                            logger.info(f"[PRUNE-CASCADE] dropped orphaned {_s.get('task','?')!r} (consumer smelt of {_SMELT_OF[_item]} already pruned)")
                        else:
                            _cascaded.append(_s)
                    _pruned = _cascaded
                    if len(_pruned) < _orig:
                        logger.info(f"[PLAN-PRUNE] {_orig} -> {len(_pruned)} steps")
                    planning = _pruned
            except Exception as _pe:
                logger.warning(f"[PLAN-PRUNE] skipped: {_pe}")
            logger.info(f"[yellow]Plan: {planning}[yellow]")
            # return

            current_monitos = Monitors([SuccessMonitor(), StepMonitor()])
            try:
                status, steps, current_planning = agent_do(
                    cfg, env, logger, current_monitos, planning, obs, memory_bank, ledger=ledger
                )
            except RuntimeError as _dead_err:
                if "done=True" not in str(_dead_err):
                    raise
                logger.warning(f"[red][DEAD-ENV] episode over mid-helper: {_dead_err}; marking run failed[/red]")
                status = "failed"
                steps = cfg.env.max_minutes * 60 * 20
                current_planning = planning
            video_file = env.save_video(task, status)

            # [AMEP] Capture failure metadata when status == "failed"
            #   Pulls from the ledger (pending outcomes) and current_monitos (which
            #   sub-task failed and at what step count).
            _amep_failure_metadata = None
            if status == "failed":
                try:
                    _summary = current_monitos.get_metric() if current_monitos else {}
                    # Find the last sub-task with SuccessMonitor=0 (or last entry if all succeeded)
                    _failed_subtask = ""
                    _failed_at_step = int(steps) if steps else 0
                    if isinstance(_summary, dict):
                        for sub_name, sub_metrics in _summary.items():
                            if isinstance(sub_metrics, dict) and sub_metrics.get("SuccessMonitor") == 0:
                                _failed_subtask = sub_name
                                _step_val = sub_metrics.get("StepMonitor", 0)
                                if isinstance(_step_val, (int, float)):
                                    _failed_at_step = int(_step_val)
                    _pending_outcomes = []
                    if ledger is not None:
                        try:
                            _pending_outcomes = list(ledger.pending())
                        except Exception:
                            pass
                    _amep_failure_metadata = {
                        "failed_subtask": _failed_subtask,
                        "failed_at_step": _failed_at_step,
                        "pending_outcomes": _pending_outcomes,
                        "last_error": "",  # could populate from a logged warning later
                        "sub_task_summary": _summary if isinstance(_summary, dict) else {},
                    }
                    logger.info(
                        f"[AMEP] Captured failure metadata: failed at {_failed_subtask!r} "
                        f"(step {_failed_at_step}); pending outcomes: {_pending_outcomes}"
                    )
                except Exception as _e:
                    logger.warning(f"[AMEP] failure metadata capture failed: {_e}")

            # * save planning
            t = memory_bank.save_plan(
                task,
                visual_info,
                goal,
                status,
                current_planning,
                steps,
                video_file,
                environment=environment,
                failure_metadata=_amep_failure_metadata,
            )
            # except Exception as e:
            #     logger.critical(f"Error: {e}")
            #     # filename format: videos/v1/{task}/{status}/{time}.mp4
            #     video_file = env.save_video(task, "failed")
            # video_file.join()
            monitors.append(current_monitos)

            logger.info(f"Summary: {current_monitos.get_metric()}")

            pretty_result(
                task, current_monitos.get_metric(), 1, steps=current_monitos.all_steps()
            )
            t.join()
        env.close()
        all_steps = 0
        for monitor in monitors:
            logger.info(monitor.get_metric())
            all_steps += monitor.all_steps()
        logger.info(f" All Steps: {all_steps}")
    exit(0)


if __name__ == "__main__":
    main()
