#!/usr/bin/env python3
"""WE 后处理：we_output.json → world_state.json + world_events.json。"""

import argparse, json, os, sys, re

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--chapter", default="")
    args = parser.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    directory = ''
    previous = {}
    if args.chapter:
        if not re.fullmatch(r'\d{1,6}', args.chapter) or int(args.chapter) < 1:
            raise ValueError('章节号无效')
        directory = f'story/{int(args.chapter):04d}'
        old = f'{directory}/planned_world_state.json'
        if os.path.isfile(old):
            with open(old,encoding='utf-8-sig') as handle:previous=json.load(handle)
    chosen=previous.get('world_time_key')
    generated=data.get('world_time_key')
    for value in (chosen,generated):
        if value is not None and type(value) is not int:raise ValueError('世界时间序号须为整数或省略')
    if chosen is not None and generated is not None and chosen!=generated:
        raise ValueError('世界演进结果与已明确的场景时间冲突，未覆盖原时间锚点')
    time_key=chosen if chosen is not None else generated

    state = {
        "world_time": data.get("world_time", ""),
        "time_advanced_days": data.get("time_advanced_days", 0),
        "forces": data.get("forces", []),
        "undercurrents": data.get("undercurrents", []),
    }
    events = {
        "world_time": data.get("world_time", ""),
        "time_advanced_days": data.get("time_advanced_days", 0),
        "on_camera_events": data.get("on_camera_events", []),
        "off_camera_events": data.get("off_camera_events", []),
        "undercurrent_progress": data.get("undercurrent_progress", []),
        "power_shift": data.get("power_shift", ""),
    }
    if time_key is not None:
        state['world_time_key']=time_key
        events['world_time_key']=time_key

    os.makedirs("cache/we", exist_ok=True)
    json.dump(state, open("cache/we/world_state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(events, open("cache/we/world_events.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if args.chapter:
        os.makedirs(directory, exist_ok=True)
        with open(f'{directory}/planned_world_state.json', 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
    print(f"[OK] world_state.json + world_events.json → cache/we/")


if __name__ == "__main__":
    main()
