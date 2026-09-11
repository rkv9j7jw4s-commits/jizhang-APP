# -*- coding: utf-8 -*-
"""
贪吃蛇小游戏 · 科幻霓虹版
纯 Python 标准库(tkinter + winsound)实现,无需安装任何第三方库。
音效为 PSP 芯片音乐风,由方波实时合成(启动时写入临时文件播放),不依赖外部音频文件。

运行方式:
    python snake.py

操作说明:
    方向键 / WASD    控制移动
    空格             暂停 / 继续
    Enter / R       游戏结束后重新开始
"""

import atexit
import io
import os
import random
import shutil
import struct
import tempfile
import tkinter as tk
import wave

try:
    import winsound  # Windows 自带,用于播放音效
    _HAS_SOUND = True
except ImportError:
    _HAS_SOUND = False

# ---------------- 游戏参数 ----------------
CELL = 20                 # 每个格子的像素边长
GRID_W, GRID_H = 25, 25   # 网格宽高(格子数)
WIDTH, HEIGHT = CELL * GRID_W, CELL * GRID_H

BASE_SPEED = 120          # 初始移动间隔(毫秒),越小越快
MIN_SPEED = 55            # 最快速度对应的间隔
SPEED_STEP = 4            # 每吃一个食物,移动间隔缩短的毫秒数

VICTORY_TEXT = "你赢了!蛇填满了整个棋盘!"

# 配色(赛博霓虹风)
BG_COLOR = "#050814"      # 深空底色
BORDER_COLOR = "#0d3b54"  # 窗口边框
GRID_COLOR = "#123a52"    # 网格线
GRID_ACCENT = "#1f6f8f"   # 每 5 格加亮的网格线
NEBULA_COLOR = "#10123a"  # 星云
STAR_COLOR = "#9fd8ff"    # 星星
SCANLINE_COLOR = "#000000"

SNAKE_COLOR = "#00ff9f"   # 蛇身霓虹绿(光晕)
SNAKE_CORE = "#c8ffe9"    # 蛇身核心
HEAD_COLOR = "#00e5ff"    # 蛇头霓虹青(光晕)
HEAD_CORE = "#d4f9ff"     # 蛇头核心
FOOD_COLOR = "#ff2d95"    # 食物霓虹粉(光环)
FOOD_CORE = "#ffd1e8"     # 食物核心

TEXT_COLOR = "#00e5ff"    # 主文字青
WARN_COLOR = "#ff5db1"    # 结束文字粉
RECORD_COLOR = "#ffe66d"  # 新纪录黄

FONT = "Microsoft YaHei"

# 按键 -> 方向(keysym 统一转小写后匹配)
DIRS = {
    "up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
    "w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0),
}

SAMPLE_RATE = 22050


# ---------------- 音效(PSP 芯片音乐风,方波合成) ----------------

def _synth(segments, volume=0.4):
    """把 [(频率Hz, 时长ms), ...] 合成为一段带衰减的方波 WAV 数据"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for freq, ms in segments:
            n = int(SAMPLE_RATE * ms / 1000)
            for i in range(n):
                square = 1.0 if (i * freq / SAMPLE_RATE) % 1.0 < 0.5 else -1.0
                env = 1.0 - i / n      # 线性衰减,短促的电子音
                frames += struct.pack("<h", int(square * env * volume * 32767))
        w.writeframes(bytes(frames))
    return buf.getvalue()


class Sound:
    """游戏音效,启动时合成 WAV 写入临时文件,异步播放(游戏退出时自动清理)"""

    def __init__(self):
        self._paths = {}
        if not _HAS_SOUND:
            return
        # 注:Python 3.14 的 winsound 不支持 SND_MEMORY 异步播放,
        # 所以必须先落盘成文件,再用 SND_FILENAME 播放
        sounds = {
            "eat":    _synth([(880, 45), (1319, 70)]),                          # 吃食物:上升双音
            "turn":   _synth([(523, 20)], volume=0.12),                         # 转向:轻响
            "pause":  _synth([(392, 55)]),                                      # 暂停
            "resume": _synth([(523, 55)]),                                      # 继续
            "over":   _synth([(494, 110), (392, 110), (311, 110), (196, 240)]), # 游戏结束:下行
            "win":    _synth([(523, 90), (659, 90), (784, 90), (1047, 200)]),   # 通关:上行
            "record": _synth([(1047, 80), (1319, 80), (1568, 150)]),            # 新纪录
            "start":  _synth([(392, 70), (523, 70), (659, 110)]),               # 开局
        }
        try:
            self._dir = tempfile.mkdtemp(prefix="snake_sounds_")
            for name, data in sounds.items():
                path = os.path.join(self._dir, f"{name}.wav")
                with open(path, "wb") as f:
                    f.write(data)
                self._paths[name] = path
            atexit.register(shutil.rmtree, self._dir, ignore_errors=True)
        except OSError:
            self._paths = {}

    def play(self, name):
        path = self._paths.get(name)
        if path:
            try:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except RuntimeError:
                pass


class SnakeGame:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("贪吃蛇 · NEON SNAKE")
        self.root.resizable(False, False)
        self.root.eval("tk::PlaceWindow . center")  # 窗口居中

        # 霓虹边框 + 画布
        frame = tk.Frame(self.root, bg=BORDER_COLOR, padx=3, pady=3)
        frame.pack()
        self.canvas = tk.Canvas(frame, width=WIDTH, height=HEIGHT,
                                bg=BG_COLOR, highlightthickness=0)
        self.canvas.pack()

        self.score_var = tk.StringVar()
        tk.Label(self.root, textvariable=self.score_var, font=(FONT, 12, "bold"),
                 fg=TEXT_COLOR, bg=BG_COLOR, pady=8).pack(fill="x")
        tk.Label(self.root, text="方向键 / WASD 移动 · 空格 暂停 · Enter 重开",
                 font=(FONT, 9), fg="#3a7d99", bg=BG_COLOR).pack(fill="x")

        self.sound = Sound()
        self._draw_background()
        self.root.bind("<KeyPress>", self.on_key)

        self.best_score = 0
        self.reset()
        self.root.after(BASE_SPEED, self.tick)  # 启动游戏主循环
        self.root.mainloop()

    # ---------------- 游戏逻辑 ----------------

    def reset(self):
        """回到初始状态(最高分保留)"""
        cx, cy = GRID_W // 2, GRID_H // 2
        self.snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]  # 蛇头在最前
        self.direction = (1, 0)      # 初始向右移动
        self.pending = []            # 缓存的转向指令(每步最多执行一个)
        self.score = 0
        self.speed = BASE_SPEED
        self.paused = False
        self.game_over = False
        self.frame = 0
        self.food = self.spawn_food()
        self.canvas.delete("over", "pause")
        self.sound.play("start")
        self.draw()

    def spawn_food(self):
        """在空白格随机生成一个食物;棋盘满了则返回 None"""
        empty = [(x, y)
                 for x in range(GRID_W)
                 for y in range(GRID_H)
                 if (x, y) not in self.snake]
        return random.choice(empty) if empty else None

    def step(self):
        """执行一步移动;游戏结束时返回原因文字,否则返回 None"""
        if self.pending:
            self.direction = self.pending.pop(0)

        hx, hy = self.snake[0]
        dx, dy = self.direction
        new_head = (hx + dx, hy + dy)

        # 1. 撞墙
        if not (0 <= new_head[0] < GRID_W and 0 <= new_head[1] < GRID_H):
            return "撞墙了!"

        will_eat = new_head == self.food
        # 2. 咬到自己(没吃到食物时尾巴会挪开,不算撞)
        body = self.snake if will_eat else self.snake[:-1]
        if new_head in body:
            return "咬到自己了!"

        self.snake.insert(0, new_head)
        if will_eat:
            self.score += 1
            self.speed = max(MIN_SPEED, self.speed - SPEED_STEP)
            self.food = self.spawn_food()
            self.sound.play("eat")
            if self.food is None:  # 蛇填满整个棋盘
                return VICTORY_TEXT
        else:
            self.snake.pop()
        return None

    def tick(self):
        """游戏主循环:每隔 speed 毫秒执行一次"""
        if not self.paused and not self.game_over:
            self.frame += 1
            reason = self.step()
            if reason:
                self.game_over = True
                self.sound.play("win" if reason == VICTORY_TEXT else "over")
                self._draw_over(reason)
            else:
                self.draw()
        self.root.after(self.speed, self.tick)

    # ---------------- 事件处理 ----------------

    def on_key(self, event):
        key = event.keysym.lower()

        # 游戏结束后:Enter / R 重开
        if key in ("return", "r") and self.game_over:
            self.reset()
            return

        # 空格:暂停 / 继续
        if key == "space" and not self.game_over:
            self.paused = not self.paused
            self.sound.play("pause" if self.paused else "resume")
            self._draw_pause_hint()
            return

        new_dir = DIRS.get(key)
        if new_dir is None or self.game_over:
            return
        # 以已排队的最后一个方向为基准,禁止 180 度掉头(也避免按住按键刷屏)
        last = self.pending[-1] if self.pending else self.direction
        if new_dir != last \
                and (new_dir[0] + last[0], new_dir[1] + last[1]) != (0, 0) \
                and len(self.pending) < 3:
            self.pending.append(new_dir)
            self.sound.play("turn")

    # ---------------- 绘制 ----------------

    def _draw_background(self):
        """画科幻风静态背景:星云、星星、网格线、扫描线(只画一次)"""
        rng = random.Random(42)  # 固定种子,每次启动的星空一致

        # 星云
        for _ in range(6):
            nx, ny = rng.randint(0, WIDTH), rng.randint(0, HEIGHT)
            r = rng.randint(60, 120)
            self.canvas.create_oval(nx - r, ny - r, nx + r, ny + r,
                                    fill=NEBULA_COLOR, outline="",
                                    stipple="gray25", tags="bg")
        # 星星
        for _ in range(80):
            sx, sy = rng.randint(2, WIDTH - 2), rng.randint(2, HEIGHT - 2)
            size = rng.choice((1, 1, 2))
            color = rng.choice((STAR_COLOR, "#7fdbff", "#ffffff"))
            self.canvas.create_rectangle(sx, sy, sx + size, sy + size,
                                         fill=color, outline="", tags="bg")
        # 网格线,每 5 格一条亮线
        for i in range(1, GRID_W):
            color = GRID_ACCENT if i % 5 == 0 else GRID_COLOR
            self.canvas.create_line(i * CELL, 0, i * CELL, HEIGHT, fill=color, tags="bg")
        for j in range(1, GRID_H):
            color = GRID_ACCENT if j % 5 == 0 else GRID_COLOR
            self.canvas.create_line(0, j * CELL, WIDTH, j * CELL, fill=color, tags="bg")
        # 扫描线(CRT 质感)
        for y in range(0, HEIGHT, 3):
            self.canvas.create_line(0, y, WIDTH, y, fill=SCANLINE_COLOR,
                                    stipple="gray50", tags="bg")

    def draw(self):
        """重绘蛇、食物和得分"""
        self.canvas.delete("snake", "food")
        self._draw_snake()
        self._draw_food()
        self.score_var.set(f"SCORE {self.score}   BEST {self.best_score}   LEN {len(self.snake)}")

    def _draw_snake(self):
        for i, (x, y) in enumerate(self.snake):
            glow, core = (HEAD_COLOR, HEAD_CORE) if i == 0 else (SNAKE_COLOR, SNAKE_CORE)
            x0, y0 = x * CELL, y * CELL
            # 两层半透明光晕 + 实心核心,模拟霓虹发光
            self.canvas.create_rectangle(x0, y0, x0 + CELL, y0 + CELL,
                                         fill=glow, outline="", stipple="gray25", tags="snake")
            self.canvas.create_rectangle(x0 + 2, y0 + 2, x0 + CELL - 2, y0 + CELL - 2,
                                         fill=glow, outline="", stipple="gray50", tags="snake")
            self.canvas.create_rectangle(x0 + 4, y0 + 4, x0 + CELL - 4, y0 + CELL - 4,
                                         fill=core, outline="", tags="snake")
        # 蛇头眼睛(朝向移动方向)
        hx, hy = self.snake[0]
        dx, dy = self.direction
        cx = hx * CELL + CELL / 2
        cy = hy * CELL + CELL / 2
        px, py = -dy, dx          # 与移动方向垂直的偏移轴
        for s in (-1, 1):
            ex = cx + px * 4 * s + dx * 3
            ey = cy + py * 4 * s + dy * 3
            self.canvas.create_oval(ex - 1.5, ey - 1.5, ex + 1.5, ey + 1.5,
                                    fill=BG_COLOR, outline="", tags="snake")

    def _draw_food(self):
        if not self.food:
            return
        fx, fy = self.food
        cx = fx * CELL + CELL // 2
        cy = fy * CELL + CELL // 2
        r = 3 + (self.frame // 3) % 4      # 呼吸式脉冲
        # 外圈脉冲光环 + 能量核心
        self.canvas.create_oval(cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5,
                                fill=FOOD_COLOR, outline="", stipple="gray25", tags="food")
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                fill=FOOD_CORE, outline=FOOD_COLOR, width=1, tags="food")

    def _draw_pause_hint(self):
        self.canvas.delete("pause")
        if self.paused:
            self.canvas.create_text(WIDTH // 2, HEIGHT // 2 - 10, text="已暂停",
                                    fill=TEXT_COLOR, font=(FONT, 22, "bold"), tags="pause")
            self.canvas.create_text(WIDTH // 2, HEIGHT // 2 + 16, text="PAUSED",
                                    fill="#3a7d99", font=(FONT, 11), tags="pause")

    def _draw_over(self, reason):
        """游戏结束画面"""
        victory = reason == VICTORY_TEXT
        new_record = self.score > self.best_score
        if new_record:
            self.best_score = self.score
        self.draw()
        color = RECORD_COLOR if victory else WARN_COLOR
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 - 24, text=reason,
                                fill=color, font=(FONT, 20, "bold"), tags="over")
        self.canvas.create_text(WIDTH // 2, HEIGHT // 2 + 18, text="按 Enter 或 R 重新开始",
                                fill=TEXT_COLOR, font=(FONT, 13), tags="over")
        if new_record and self.score > 0:
            self.canvas.create_text(WIDTH // 2, HEIGHT // 2 + 44, text="★ 新纪录!",
                                    fill=RECORD_COLOR, font=(FONT, 14, "bold"), tags="over")
            self.root.after(600, lambda: self.sound.play("record"))


if __name__ == "__main__":
    SnakeGame()
