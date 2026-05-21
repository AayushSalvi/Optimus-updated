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

        while current_plan is not None:
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
                done, info = helper.step(task, goal)  # type: ignore
                steps = helper.get_task_steps(task)

                env.can_open_inventory = False
                env.can_change_hotbar = False

                monitors.update(f"{task}_{progress}", done, steps)
                if done:
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
                    plan_manager.insert_plan(new_planning, is_replan=True)

                    set_pbar_total(pbar, all_task, len(plan_manager.all))

                    logger.warning(f"[yellow]Replanning...\n{new_planning}[/yellow]")
                    # save replan
                    env.save_video(task, "failed", True)
                    memory_bank.save_replan(task, info, new_planning)
            else:
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
                    obs, reward, game_over, info = env.step(action, goal)
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

        if len(plan_manager.remain_plans) == 0 and not game_over:
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

            logger.info(f"[yellow]Plan: {planning}[yellow]")
            # return

            current_monitos = Monitors([SuccessMonitor(), StepMonitor()])
            # try:
            status, steps, current_planning = agent_do(
                cfg, env, logger, current_monitos, planning, obs, memory_bank, ledger=ledger
            )
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
