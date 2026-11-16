#!/usr/bin/env python3
"""Conductor Studio のキーマップ JSON を moNa2 用の ZMK キーマップに変換する。

    python3 tools/conductor_to_zmk.py conductor/conductor-keymap2.json

config/mona2.keymap の
    /* ===== BEGIN GENERATED: conductor_to_zmk.py ===== */
    /* ===== END GENERATED: conductor_to_zmk.py ===== */
で挟まれた部分（コンボとレイヤー）だけを書き換える。ほかの部分（behavior の定義など）は
手で書いたものがそのまま残る。標準ライブラリだけで動く。

■ キー位置の対応（Conductor 40 キー → moNa2 42 キー）

    moNa2 の番号          0-4 | 5-9           上段 5+5
                        10-14 | 15 16-20      中段 5 + (右の内側 15) + 5
                        21-25 26 | 27 28-32   下段 5 + (左の内側 26) + (右の内側 27) + 5
                        33-38 | 39 40 .. 41   親指 6 | 2 + 右下隅 41

    Conductor L00-L24 / R00-R24 → 同じ並びのまま
    Conductor L30-L35           → 33-38（左の親指段 6 キー）
    Conductor R30, R31          → 39, 40（右の親指 2 キー）
    Conductor R33               → 41（右下隅。どちらも小指の列の一番下）
    Conductor R32               → 27（moNa2 にはトラックボールの位置で同じ場所のキーがないので、右の内側下）
    moNa2 だけにある 15, 26     → base は &none、それ以外のレイヤーは &trans
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEYMAP = REPO / "config" / "mona2.keymap"
BEGIN = "/* ===== BEGIN GENERATED: conductor_to_zmk.py ===== */"
END = "/* ===== END GENERATED: conductor_to_zmk.py ===== */"

KEY_COUNT = 42

# Conductor の位置名 → moNa2 のキー番号
POS: dict[str, int] = {}
for i in range(5):
    POS[f"L0{i}"] = i
    POS[f"R0{i}"] = 5 + i
    POS[f"L1{i}"] = 10 + i
    POS[f"R1{i}"] = 16 + i
    POS[f"L2{i}"] = 21 + i
    POS[f"R2{i}"] = 28 + i
for i in range(6):
    POS[f"L3{i}"] = 33 + i
POS.update({"R30": 39, "R31": 40, "R32": 27, "R33": 41})
MONA2_ONLY = (15, 26)

# hold-tap の種類ごとに使う自作 behavior（定義は keymap の behaviors にある）
#   mod-tap         → mt_home（Conductor と同じ tap-preferred / 160ms）
#   layer-tap       → lt_thumb（balanced / 200ms）。L 長押しのマウスレイヤーだけ lt_mouse
MOUSE_LAYER = 4

# 変換できない（Conductor 独自ファームの機能）もの
UNSUPPORTED_KEYCODES = {"SCRL_INV"}

# 各行の並び（keymap の見た目用。数字は moNa2 のキー番号）
ROWS = [
    list(range(0, 5)) + [None, None] + list(range(5, 10)),
    list(range(10, 15)) + [None, 15] + list(range(16, 21)),
    list(range(21, 26)) + [26, 27] + list(range(28, 33)),
    list(range(33, 39)) + [39, 40] + [None, None, None, 41],
]

notes: list[str] = []


def zmk_binding(b: dict, where: str) -> str:
    t = b["type"]
    code = b.get("keyCode", "")
    if t == "transparent":
        return "&trans"
    if t == "none":
        return "&none"
    if t == "basic":
        if code in UNSUPPORTED_KEYCODES:
            notes.append(f"{where}: {code}（Conductor 独自）→ &none")
            return "&none"
        if code.startswith("mkp "):
            return "&" + code
        if code.startswith(("BT_SEL", "BT_CLR")):
            return "&bt " + code
        if code == "BOOTLOADER":
            return "&bootloader"
        return "&kp " + code
    if t == "mod-tap":
        return f"&mt_home {b['holdAction']} {b['tapAction']}"
    if t == "layer-tap":
        m = re.fullmatch(r"LT\((\d+),\s*(\w+)\)", code)
        assert m, f"{where}: 読めない layer-tap {code}"
        layer, tap = int(m.group(1)), m.group(2)
        beh = "lt_mouse" if layer == MOUSE_LAYER else "lt_thumb"
        return f"&{beh} {layer} {tap}"
    m = re.fullmatch(r"(MO|TO|TG)\((\d+)\)", code)
    if m:
        beh = {"MO": "mo", "TO": "to", "TG": "tog"}[m.group(1)]
        return f"&{beh} {m.group(2)}"
    notes.append(f"{where}: 未対応の種類 {t} {code} → &none")
    return "&none"


def node_name(name: str, index: int) -> str:
    n = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    return n if n and not n[0].isdigit() else f"layer_{index}"


def render_layer(layer: dict) -> str:
    idx = layer["id"]
    keys = ["&none" if idx == 0 else "&trans"] * KEY_COUNT
    for pos, b in layer["bindings"].items():
        keys[POS[pos]] = zmk_binding(b, f"layer {idx} {pos}")
    width = max(len(k) for k in keys) + 2
    lines = []
    for row in ROWS:
        cells = [(" " * width if p is None else keys[p].ljust(width)) for p in row]
        lines.append("".join(cells).rstrip())
    sensors = "<&rsr_default>, <&inc_dec_kp C_VOL_DN C_VOL_UP>" if idx == 0 else "<&rsr_default>"
    body = "\n".join(lines)
    return (
        f"        {node_name(layer['name'], idx)} {{\n"
        f"            display-name = \"{layer['name']}\";\n"
        f"            bindings = <\n{body}\n            >;\n"
        f"            sensor-bindings = {sensors};\n"
        f"        }};\n"
    )


def render_combos(combos: list[dict]) -> str:
    out = []
    slot = 0
    for c in combos:
        b = c["binding"]
        if b["type"] == "custom":
            notes.append(f"コンボ「{c['name']}」: {b['behaviorName']}（Conductor 独自）→ 入れない")
            continue
        if b["keyCode"] == "BT_SEL 5":
            notes.append(f"コンボ「{c['name']}」: BT_SEL 5（6 台目のプロファイル。ZMK の既定は 5 台まで）→ 入れない")
            continue
        positions = " ".join(str(POS[p]) for p in c["keyPositions"])
        lines = [
            f"        combo_{slot} {{",
            f"            slot = <{slot}>;",
            f"            display-name = \"{c['name']}\";",
            f"            key-positions = <{positions}>;",
            f"            bindings = <{zmk_binding(b, 'combo ' + c['name'])}>;",
        ]
        if c.get("timeoutMs") and c["timeoutMs"] != 50:
            lines.append(f"            timeout-ms = <{c['timeoutMs']}>;")
        # 4294967295 は Conductor で「未設定」の意味
        idle = c.get("requirePriorIdleMs", 0)
        if idle and idle < 4294967295:
            lines.append(f"            require-prior-idle-ms = <{idle}>;")
        if c.get("layers"):
            lines.append(f"            layers = <{' '.join(map(str, c['layers']))}>;")
        if c.get("slowRelease"):
            lines.append("            slow-release;")
        lines.append("        };")
        out.append("\n".join(lines))
        slot += 1
    return "\n\n".join(out)


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "conductor" / "conductor-keymap2.json")
    data = json.loads(src.read_text(encoding="utf-8"))
    layers = sorted(data["layers"], key=lambda l: l["id"])
    assert [l["id"] for l in layers] == list(range(len(layers))), "レイヤー番号が連番ではありません"

    generated = (
        f"{BEGIN}\n"
        f"/* 元データ: {src.name}（{data.get('name')} / updatedAt {data.get('updatedAt')}）。手で直さず、JSON を更新して再生成する */\n"
        "/ {\n"
        "    runtime_combo_defaults {\n"
        "        compatible = \"cormoran,runtime-combo-defaults\";\n\n"
        f"{render_combos(data.get('combos', []))}\n"
        "    };\n\n"
        "    keymap {\n"
        "        compatible = \"zmk,keymap\";\n\n"
        + "\n".join(render_layer(l) for l in layers)
        + "    };\n};\n"
        f"{END}"
    )

    text = KEYMAP.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        print(f"{KEYMAP} に生成マーカーがありません", file=sys.stderr)
        return 1
    KEYMAP.write_text(pattern.sub(lambda _: generated, text), encoding="utf-8")

    print(f"{KEYMAP.relative_to(REPO)} を更新: レイヤー {len(layers)} 枚")
    for n in notes:
        print("  NOTE:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
