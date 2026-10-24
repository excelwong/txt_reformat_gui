#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TXT 排版工具 - GUI 版
可选「单个文件」或「目录（含子目录）」两种处理目标：
  - 目录模式：递归处理目标目录下所有 .txt 文件（.bak 备份文件自动跳过）
三种排版模式：
  - 拆分长单行：正文按句末标点逐句断行、压缩连续空行、章节重排
  - 去除多空行：仅去掉连续空行，不合并断行、不改其它内容
  - 全文重排：章节/序号前加空行、正文删空格/tab/回车、仅引号/书名号/中括号/大括号外的句末标点换行
"""

import os
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ===== 核心排版逻辑 =====

def split_paragraphs(body):
    """将连续文本切分为段落列表。"""
    body = body.strip()
    if not body:
        return []

    # 按全角空格拆分段落（原文用　作为段间分隔）
    raw_paras = re.split(r'\u3000+', body)
    raw_paras = [p.strip() for p in raw_paras if p.strip()]

    paragraphs = []
    for para in raw_paras:
        # 在每个段落内，把「」对话拆出来独立成段
        tokens = re.split(r'([「[^」]*」])', para)
        current_narration = ''
        for token in tokens:
            if not token:
                continue
            if token.startswith('「') and token.endswith('」'):
                if current_narration.strip():
                    paragraphs.append(current_narration.strip())
                    current_narration = ''
                if paragraphs and paragraphs[-1].startswith('「'):
                    paragraphs[-1] += token
                else:
                    paragraphs.append(token)
            else:
                current_narration += token
        if current_narration.strip():
            paragraphs.append(current_narration.strip())

    return [p for p in paragraphs if p.strip()]


def normalize_newlines(text):
    """统一换行符为 \\n（处理 \\r\\n 与裸 \\r）。"""
    return text.replace('\r\n', '\n').replace('\r', '\n')


def collapse_blank_lines(text):
    """把 2 个及以上的连续空行压缩为 1 个，去除多余的连续回车空行。

    空行指：仅含换行/空格/制表符的行。连续的空行往往是排版残留。
    """
    text = normalize_newlines(text)
    # 一个换行 + 若干「仅空白行」整段 -> 单个换行
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n', text)


# ===== 逐句拆行（split 模式用） =====

SPLIT_PUNCT = ('。', '！', '？', '；', '…')

# 成对括号/引号：开符号 -> 对应闭符号（栈匹配，支持嵌套）
BRACKET_PAIRS = {
    '“': '”',   # 弯双引号
    '‘': '’',   # 弯单引号
    '「': '」',   # 直角双引号
    '『': '』',   # 空心方头引号
    '《': '》',   # 书名号
    '【': '】',   # 中括号（方头）
    '[': ']',    # 中括号（半角）
    '{': '}',    # 大括号
}
# 与开符号一一对应的闭符号集合
BRACKET_CLOSE = ('”', '’', '」', '』', '》', '】', ']', '}')
# 开闭同形的直引号：栈顶是自身则视为闭合，否则视为新开
QUOTE_TOGGLE = ('"', "'")


def _iter_sentences(text, punct):
    """按句末标点拆句的核心：返回句子列表（标点保留在句尾）。

    punct: 视为句末标点的字符集合（调用方决定是否含分号、单个 …）。
    引号（“”‘’「」『』" "）、书名号（《》）、中括号（【】[]）、大括号（{}）内部的
    标点不拆——栈计数、支持嵌套；不成对的括号/引号按容错处理。
    所有闭符号（”、’、」、』、》、】、]、}，以及直引号闭合）之后强制换行；
    若闭符号后紧跟句末标点（如 他说：“你好”。 引号外的句号），标点留在同行。
    两个 … 连写（……）视为整体，栈空时断行；单个 … 仅当在 punct 中才断行。
    """
    sentences = []
    cur = []
    stack = []   # 未闭合的括号/引号栈

    def pick_follow_punct(pos):
        """闭符号断行前，拾取紧随的句末标点（含连写省略号），避免其单独成行。"""
        nonlocal cur
        while pos < n:
            nxt = text[pos]
            if nxt == '…' and pos + 1 < n and text[pos + 1] == '…':
                cur.append('……'); pos += 2; continue
            if nxt in punct:
                cur.append(nxt); pos += 1; continue
            break
        return pos

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # 成对开符号：入栈
        if ch in BRACKET_PAIRS:
            stack.append(BRACKET_PAIRS[ch])
            cur.append(ch); i += 1; continue
        # 成对闭符号：栈顶匹配才出栈（孤立的闭符号按普通字符容错处理）
        if ch in BRACKET_CLOSE:
            if stack and stack[-1] == ch:
                stack.pop()
            cur.append(ch); i += 1
            # 闭符号后强制换行（闭符号后紧随的句末标点留在同行）
            i = pick_follow_punct(i)
            sentences.append(''.join(cur))
            cur = []
            continue
        # 直引号开闭同形：栈顶是自身则出栈并断行，否则入栈（视为开）
        if ch in QUOTE_TOGGLE:
            if stack and stack[-1] == ch:
                stack.pop()
                cur.append(ch); i += 1
                i = pick_follow_punct(i)
                sentences.append(''.join(cur))
                cur = []
            else:
                stack.append(ch)
                cur.append(ch); i += 1
            continue
        # 省略号（两个 … 连写为 ……）：栈空时断行
        if ch == '…' and i + 1 < n and text[i + 1] == '…':
            cur.append('……')
            i += 2
            if not stack:
                sentences.append(''.join(cur))
                cur = []
            continue
        # 句末标点：不在任何括号/引号内才换行
        if ch in punct and not stack:
            cur.append(ch)
            sentences.append(''.join(cur))
            cur = []
            i += 1; continue
        cur.append(ch); i += 1
    if cur:
        sentences.append(''.join(cur))
    return sentences


def split_sentences(text):
    """将连续文本按句末标点（。！？；…）拆成单句列表，标点保留在句尾。

    引号（“”‘’「」『』" "）、书名号（《》）、中括号（【】[]）、大括号（{}）内部的
    句末标点不拆——栈计数、支持嵌套（如 “《甲》【注】”）；避免把对话、
    书名、注释等拆碎。不成对的括号按容错处理（不当成未闭合）。
    所有闭符号（”、’、」、』、》、】、]、} 及直引号闭合）之后强制换行。
    """
    return _iter_sentences(text, SPLIT_PUNCT)


# ===== 全文重排（reflow）核心逻辑 =====

SENT_END = ('。', '！', '？')

CHAPTER_RE = re.compile(r'^第[0-9零一二三四五六七八九十百千万两〇]+[章回节卷部篇集]')
NUM_RE = re.compile(r'^([0-9]+|[一二三四五六七八九十百千万〇]+)[.、)）]')
PAREN_RE = re.compile(r'^（[0-9一二三四五六七八九十百千万〇]+）')
CHAPTER_EN_RE = re.compile(r'^Chapter\s+[0-9]+', re.I)


def is_heading_line(line):
    """判断单行是否为「章节 / 序号」标题行。

    规则：行首匹配 第X章/回/节… 、序号(数字或汉字+。、)）、(数字) 、Chapter N；
    且长度不超过 50 字。允许行尾单个句末标点；若句末标点出现在句中（非结尾），
    则视为正文句子，不作为标题。并排除 "1.5倍" 这类小数开头的误判。
    """
    s = line.strip()
    if not s or len(s) > 50:
        return False
    # 句末标点若出现在中间（非结尾），基本是正文的句子，不作为标题
    for p in '。！？…':
        idx = s.find(p)
        if idx != -1 and idx != len(s) - 1:
            return False
    if CHAPTER_RE.match(s) or PAREN_RE.match(s) or CHAPTER_EN_RE.match(s):
        return True
    m = NUM_RE.match(s)
    if m:
        mm = m.group(0)
        # 排除 "1.5倍"：小数点后立即又是数字
        if mm.endswith('.') and len(s) > len(mm) and s[len(mm)].isdigit():
            return False
        return True
    return False


def reflow_body(text):
    """正文重排：删除所有空格/全角空格/tab/换行，在句号、感叹号、问号、
    省略号（……）及所有闭符号（”、’、」、』、》、】、]、}、直引号闭合）后换行。
    保护范围：引号（“”‘’「」『』" "）、书名号（《》）、中括号（【】[]）、
    大括号（{}），栈计数、支持嵌套；单个 … 不作为句末标点。
    """
    # 1) 删除空格、全角空格、tab、所有换行/回车（正文被压成连续字符流）
    text = (text.replace('\u3000', '')
                .replace(' ', '')
                .replace('\t', '')
                .replace('\r', '')
                .replace('\n', ''))

    # 2) 按句末标点拆句（与 split 共用括号保护逻辑）
    return '\n'.join(_iter_sentences(text, SENT_END))


def reflow_full_text(text):
    """全文重排：
    1) 章节/序号：前加一空行，后回车换行（标题独立成行，前后分隔）。
    2) 正文：删除所有空格/tab/回车，仅在引号/书名号/中括号/大括号外的句末标点处换行。
    返回 (排版后文本, 章节/序号数量)。
    """
    text = normalize_newlines(text)
    lines = text.split('\n')

    blocks = []          # ('heading', 标题文本) 或 ('body', 多行正文)
    body_buf = []
    heading_count = 0

    def flush_body():
        nonlocal body_buf
        if body_buf:
            blocks.append(('body', reflow_body(''.join(body_buf))))
            body_buf = []

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_body()          # 空行：先收尾正文，不保留原空行
            continue
        if is_heading_line(line):
            flush_body()
            blocks.append(('heading', line))
            heading_count += 1
        else:
            body_buf.append(line)

    flush_body()

    # 组装：标题前加一空行；标题后由 join('\n') 自然接换行；正文内部逐句换行
    paragraphs = []
    for kind, content in blocks:
        if kind == 'heading':
            if paragraphs:
                paragraphs.append('')     # 标题前空行
            paragraphs.append(content)    # 标题行
        else:
            paragraphs.append(content.rstrip('\n'))

    result = '\n'.join(paragraphs).rstrip() + '\n'
    return result, heading_count


def reformat_text(text, mode="split"):
    """对整篇文本进行排版，返回 (排版后文本, 章节数)
    
    mode:
      "split" = 拆分长单行（完整排版：压缩连续空行 + 正文按句末标点逐句断行 + 章节重排）
      "blank" = 去除多空行（仅压缩/去除连续空行，保留原有行结构与内容，不合并断行）
      "reflow" = 全文重排（章节/序号前加空行、正文删空格/tab/回车、仅括号/引号外句末标点换行）
    """
    if mode == "blank":
        # 去除多空行：只去掉连续的空行，不合并断行、不做任何排版变换
        result = collapse_blank_lines(text).rstrip() + "\n"
        return result, 0

    if mode == "reflow":
        # 全文重排
        return reflow_full_text(text)

    # split 模式（拆分长单行）：完整排版管线
    text = collapse_blank_lines(text)

    # 1. 按章节切分（支持"第X章"和"一、二、三..."两种格式）
    chapter_pattern = r'(第[一二三四五六七八九十百千零\d]+章\s*[：:]?\s*\S{0,30}|^[一二三四五六七八九十百千零\d]+、\s*\S{0,40})'
    parts = re.split(chapter_pattern, text, flags=re.MULTILINE)

    # chapters: (标题, 正文)；首个章节之前的内容作为"引言/书名"，原样保留到顶部，不再伪造"序"
    chapters = []
    preamble_parts = []
    i = 0
    while i < len(parts):
        part = parts[i].strip()
        if not part:
            i += 1
            continue
        is_chapter = (
            (re.match(r'^第[一二三四五六七八九十百千零\d]+章', part) and len(part) <= 40) or
            (re.match(r'^[一二三四五六七八九十百千零\d]+、', part) and len(part) <= 50)
        )
        if is_chapter:
            title = part.strip()
            body = parts[i + 1] if i + 1 < len(parts) else ''
            chapters.append((title, body))
            i += 2
        else:
            if chapters:
                chapters[-1] = (chapters[-1][0], chapters[-1][1] + part)
            else:
                preamble_parts.append(part)
            i += 1

    preamble = '\n'.join(preamble_parts)

    # 2. 组装输出：引言原样保留；章节标题独立成行、章节间留一个空行；
    #    正文按句末标点（。！？；……）逐句拆成单行，段落首句缩进两格全角空格。
    MAX_LINE_LEN = 200

    def hard_wrap(line, max_len=MAX_LINE_LEN):
        """兜底：单句本身超长时按次级标点（，、；：）拆，再无标点则硬切。"""
        if len(line) <= max_len:
            return [line]
        out = []
        remaining = line
        while len(remaining) > max_len:
            cut = -1
            # 先在 [max_len/2, max_len) 区间找次级标点，找不到再放宽到前两倍长度
            hi = min(max_len, len(remaining))
            for pos in range(hi - 1, max_len // 2 - 1, -1):
                if remaining[pos] in '，,、；：':
                    cut = pos + 1
                    break
            if cut == -1:
                hi = min(max_len * 2, len(remaining))
                for pos in range(hi - 1, max_len - 1, -1):
                    if remaining[pos] in '，,、；：':
                        cut = pos + 1
                        break
            if cut == -1:
                # 完全没有次级标点，硬切
                cut = max_len
            out.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            out.append(remaining)
        return out

    out_lines = []
    if preamble:
        # 引言/书名区逐行处理：书名、作者等短信息行原样保留；
        # 较长的行按句末标点逐句拆行（无章节标记的全文也能拆成单行）
        for raw in preamble.split('\n'):
            line = raw.strip()
            if not line:
                continue
            if len(line) <= 30 and not any(p in line for p in SPLIT_PUNCT):
                out_lines.append(line)
            else:
                for j, s in enumerate(split_sentences(line)):
                    prefix = '\u3000\u3000' if j == 0 else ''
                    out_lines.append(prefix + s)
        out_lines.append('')

    for idx, (title, body) in enumerate(chapters):
        if idx > 0 or preamble:
            out_lines.append('')    # 与上一块（引言/上一章）之间留一个空行
        if title:
            out_lines.append(title.strip())
        paragraphs = split_paragraphs(body)
        for p in paragraphs:
            sentences = split_sentences(p)
            for j, s in enumerate(sentences):
                prefix = '\u3000\u3000' if j == 0 else ''
                for line in hard_wrap(prefix + s):
                    out_lines.append(line)

    result = '\n'.join(out_lines)
    # 末尾再统一压缩一次：避免组装时空行叠加产生连续空行，同时保留单空行作为段落/章节间距
    result = collapse_blank_lines(result).rstrip() + '\n'
    return result, len(chapters)


def find_txt_files(directory):
    """递归查找目录下所有 .txt 文件"""
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for fn in sorted(filenames):
            if fn.lower().endswith('.txt') and not fn.endswith('.bak'):
                files.append(os.path.join(root, fn))
    return files


def detect_encoding(filepath):
    """检测文件编码，返回 (text, encoding)"""
    with open(filepath, 'rb') as f:
        raw = f.read()
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8'), 'utf-8-sig'
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode('gb18030', errors='replace'), 'gb18030'


# ===== GUI =====

class ReformatApp:
    def __init__(self, root):
        self.root = root
        root.title("TXT 排版工具")
        root.geometry("560x420")
        root.resizable(True, True)

        # 处理目标区：文件 / 目录 二选一
        frame_file = ttk.LabelFrame(root, text="处理目标", padding=10)
        frame_file.pack(fill='x', padx=15, pady=(15, 5))

        self.var_target = tk.StringVar(value="file")
        f_t = ttk.Frame(frame_file)
        f_t.pack(fill='x', pady=(0, 6))
        ttk.Radiobutton(f_t, text="单个文件", value="file", variable=self.var_target,
                        command=self._on_target_change).pack(side='left')
        ttk.Radiobutton(f_t, text="目录（含子目录下的所有 txt）", value="dir", variable=self.var_target,
                        command=self._on_target_change).pack(side='left', padx=(12, 0))

        f_path = ttk.Frame(frame_file)
        f_path.pack(fill='x')
        self.var_path = tk.StringVar(value="未选择文件")
        lbl = ttk.Entry(f_path, textvariable=self.var_path, state='readonly')
        lbl.pack(side='left', fill='x', expand=True)
        self.btn_browse = ttk.Button(f_path, text="浏览文件...", command=self.on_browse)
        self.btn_browse.pack(side='right', padx=(8, 0))
        self.btn_run = ttk.Button(f_path, text="开始排版", command=self.on_run)
        self.btn_run.pack(side='right')

        # 选项区
        frame_opt = ttk.LabelFrame(root, text="选项", padding=10)
        frame_opt.pack(fill='x', padx=15, pady=5)

        self.var_mode = tk.StringVar(value="split")
        ttk.Radiobutton(frame_opt, text="拆分长单行（正文按标点逐句断行、压缩连续空行）", value="split", variable=self.var_mode).pack(anchor='w')
        ttk.Radiobutton(frame_opt, text="去除多空行（仅去掉连续空行，不合并断行、不改其它内容）", value="blank", variable=self.var_mode).pack(anchor='w')
        ttk.Radiobutton(frame_opt, text="全文重排（章节前空行、正文删空格/tab/回车、仅括号/引号外句末标点换行）", value="reflow", variable=self.var_mode).pack(anchor='w')

        self.var_backup = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame_opt, text="保留原文件备份（.bak）", variable=self.var_backup).pack(anchor='w', pady=(5, 0))

        # 进度条 + 状态
        frame_prog = ttk.Frame(root, padding=(15, 5))
        frame_prog.pack(fill='x')
        self.progress = ttk.Progressbar(frame_prog, mode='determinate', maximum=100)
        self.progress.pack(fill='x')
        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.var_status).pack(anchor='w', padx=20)

        # 日志区
        frame_log = ttk.LabelFrame(root, text="日志", padding=5)
        frame_log.pack(fill='both', expand=True, padx=15, pady=(5, 10))

        self.txt_log = tk.Text(frame_log, height=12, font=('Consolas', 9), state='disabled')
        scrollbar = ttk.Scrollbar(frame_log, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scrollbar.set)
        self.txt_log.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

    def log(self, msg):
        self.txt_log.configure(state='normal')
        self.txt_log.insert('end', msg + '\n')
        self.txt_log.see('end')
        self.txt_log.configure(state='disabled')
        self.root.update_idletasks()

    def on_browse(self):
        if self.var_target.get() == "dir":
            path = filedialog.askdirectory(title="选择目录（含子目录下的 .txt 将全部处理）")
        else:
            path = filedialog.askopenfilename(
                title="选择 TXT 文件",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
            )
        if path:
            self.var_path.set(path)

    def _on_target_change(self):
        if self.var_target.get() == "dir":
            self.var_path.set("未选择目录")
            self.btn_browse.configure(text="浏览目录...")
        else:
            self.var_path.set("未选择文件")
            self.btn_browse.configure(text="浏览文件...")

    def on_run(self):
        path = self.var_path.get()
        target = self.var_target.get()
        if target == "dir":
            if not os.path.isdir(path):
                messagebox.showwarning("提示", "请先选择一个有效的目录")
                return
        else:
            if not os.path.isfile(path):
                messagebox.showwarning("提示", "请先选择一个有效的 TXT 文件")
                return

        self.btn_run.configure(state='disabled')
        self.progress.configure(value=0)
        mode = self.var_mode.get()
        threading.Thread(target=self._do_reformat, args=(path, mode, target), daemon=True).start()

    def _process_one_file(self, filepath, mode, unit):
        """处理单个文件：读 → 排版 → 备份 → 写回，并在日志中记录结果。"""
        text, enc = detect_encoding(filepath)
        result, ch_count = reformat_text(text, mode=mode)
        bn = os.path.basename(filepath)
        if self.var_backup.get():
            bak = filepath + '.bak'
            with open(bak, 'wb') as f:
                with open(filepath, 'rb') as rf:
                    f.write(rf.read())
            self.root.after(0, lambda b=bak: self.log(f"已备份 → {os.path.basename(b)}"))
        with open(filepath, 'w', encoding=enc) as f:
            f.write(result)
        self.root.after(0, lambda b=bn, c=ch_count: self.log(f"✓ {b} ({c}{unit})"))

    def _do_reformat(self, path, mode, target):
        unit = "章" if mode != "reflow" else "处章节/序号"
        try:
            if target == "dir":
                files = find_txt_files(path)
                if not files:
                    self.root.after(0, lambda: messagebox.showwarning("提示", "目录下没有找到 .txt 文件"))
                    return
                total = len(files)
                ok = 0
                for i, fp in enumerate(files):
                    try:
                        self._process_one_file(fp, mode, unit)
                        ok += 1
                    except Exception as e:
                        self.root.after(0, lambda m=f"{os.path.basename(fp)}：{e}": self.log(f"✗ {m}"))
                    self.root.after(0, lambda v=int((i + 1) / total * 100): self.progress.configure(value=v))
                self.root.after(0, lambda: self.log(f"完成：成功 {ok} / 共 {total} 个文件"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "完成", f"排版完成！\n成功 {ok} / 共 {total} 个文件\n目录：{path}"))
            else:
                self._process_one_file(path, mode, unit)
                self.root.after(0, lambda: self.progress.configure(value=100))
                self.root.after(0, lambda: messagebox.showinfo(
                    "完成", f"排版成功！\n{os.path.basename(path)}\n（模式：{mode}）"))

        except Exception as e:
            self.root.after(0, lambda: self.log(f"✗ 错误：{e}"))
            self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
        finally:
            self.root.after(0, lambda: self.btn_run.configure(state='normal'))


def main():
    root = tk.Tk()
    app = ReformatApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
