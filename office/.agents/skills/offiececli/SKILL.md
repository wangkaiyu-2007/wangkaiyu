---
name: officecli
description: 使用本地 officecli-win-x64.exe 读取、创建和修改 Word(.docx)、Excel(.xlsx)、PowerPoint(.pptx)
  文档，支持查询、DOM 编辑、批量操作与原始 XML。
---

# officecli

## 何时使用

当用户需要创建、读取、检查或修改 Word、Excel、PowerPoint 文档时使用本 Skill。适用于生成报告、整理表格、制作演示文稿、批量替换文本、校验文档结构等任务。

## 可执行文件

本 Skill 目录内已附带 `officecli-win-x64.exe`，无需安装 Office。

- 优先通过 `runCli` 调用，`command` 使用相对项目根目录的路径：
  `.agents\skills\officecli\officecli-win-x64.exe`
- `args` 必须是字符串数组，每个参数单独一项，不要拼接成一条 Shell 命令。
- 如果当前工作目录不是项目根目录，改用该文件的绝对路径。
- 示例：

```text
runCli(
  command=".agents\\skills\\officecli\\officecli-win-x64.exe",
  args=["view", "report.docx", "stats"]
)
```

## 工作分层

优先使用高层能力，无法满足时再降级：

1. **L1 读取**：`create`、`view`、`get`、`query`、`validate`
2. **L2 DOM 编辑**：`set`、`add`、`remove`、`move`、`swap`、`batch`
3. **L3 原始 XML**：`raw`、`raw-set`、`add-part`

需要机器可读结果时加 `--json`。

## 先查帮助，不要猜属性名

不确定属性名、取值格式或命令语法时，先运行帮助：

```text
officecli help
officecli help docx
officecli help docx paragraph
officecli help docx set paragraph
officecli help xlsx cell --json
```

格式别名：`word`→`docx`，`excel`→`xlsx`，`ppt`/`powerpoint`→`pptx`。
动词：`add`、`set`、`get`、`query`、`remove`。

## 快速开始

### Word

```text
officecli create report.docx
officecli add report.docx /body --type paragraph --prop text="Executive Summary" --prop style=Heading1
officecli add report.docx /body --type paragraph --prop text="Revenue increased by 25% year-over-year."
```

### Excel

```text
officecli create data.xlsx
officecli set data.xlsx /Sheet1/A1 --prop value="Name" --prop bold=true
officecli set data.xlsx /Sheet1/A2 --prop value="Alice"
```

### PowerPoint

```text
officecli create slides.pptx
officecli add slides.pptx / --type slide --prop title="Q4 Report" --prop background=1A1A2E
officecli add slides.pptx '/slide[1]' --type shape --prop text="Revenue grew 25%" --prop x=2cm --prop y=5cm --prop font=Arial --prop size=24 --prop color=FFFFFF
```

## 读取与检查

```text
officecli view <file> outline|stats|issues|text|annotated|html
officecli get <file> <path> --depth N --json
officecli query <file> <selector>
officecli validate <file>
```

常用 `view` 模式：

- `outline`：文档结构
- `stats`：页数、字数、形状数等统计
- `issues`：格式、内容、结构问题
- `text`：纯文本
- `annotated`：带格式标注的文本
- `html`：静态 HTML 快照
- `screenshot` / `svg` / `pdf`：截图、SVG、PDF（部分需要插件）

路径使用 1-based 索引，例如 `/body/p[3]`、`/slide[1]`、`/Sheet1/A1`。优先使用稳定 ID 路径（如 `/slide[1]/shape[@id=550950021]`），避免插入或删除后位置变化。

CSS 风格查询示例：

```text
officecli query report.docx 'paragraph[style=Normal] > run[font!=Arial]'
officecli query slides.pptx 'shape[fill=FF0000]'
officecli query data.xlsx 'Sheet1!row[Salary>5000]'
```

## 修改文档

### set：修改属性

```text
officecli set <file> <path> --prop key=value [--prop key=value ...]
```

任意 XML 属性都可以通过 `--prop` 设置。常用值格式：

- 颜色：`FF0000`、`#FF0000`、`red`、`rgb(255,0,0)`、`accent1`
- 间距：`12pt`、`0.5cm`、`1.5x`、`150%`
- 尺寸：`914400`、`2.54cm`、`1in`、`72pt`、`96px`
- 字体别名：`font.color=red`、`font.bold=true`、`font.size=14pt`

### 查找与替换

```text
officecli set doc.docx / --find draft --replace final
officecli set doc.docx '/body/p[1]' --find weather --prop bold=true --prop color=red
officecli set doc.docx '/body/p[1]' --find '\d+%' --prop regex=true --prop color=red
```

`/` 表示全文范围。默认区分大小写，正则大小写不敏感可写 `--prop 'find=(?i)error' --prop regex=true`。

### add：新增元素

```text
officecli add <file> <parent> --type <type> --prop key=value
officecli add <file> <parent> --type <type> --after <path> --prop key=value
officecli add <file> <parent> --type <type> --before <path> --prop key=value
officecli add <file> <parent> --from <path>
```

`--after`、`--before`、`--index` 互斥；不指定位置时追加到末尾。

### remove / move / swap

```text
officecli remove <file> '/body/p[4]'
officecli move <file> <path> --to <parent> --index N
officecli swap <file> <path1> <path2>
```

### batch：一次执行多个操作

```text
echo '[{"command":"set","path":"/Sheet1/A1","props":{"value":"Name","bold":"true"}}]' | officecli batch data.xlsx --json
officecli batch data.xlsx --commands '[{"op":"set","path":"/Sheet1/A1","props":{"value":"Done"}}]' --json
officecli batch data.xlsx --input updates.json --best-effort --json
```

batch 默认原子执行：任一操作失败则整体回滚；需要保留成功项时加 `--best-effort`。

## 原始 XML（最后手段）

```text
officecli raw <file> <part>
officecli raw-set <file> <part> --xpath "..." --action replace --xml '<w:p>...</w:p>'
officecli add-part <file> <parent>
```

`raw-set` 的 action 支持：`append`、`prepend`、`insertbefore`、`insertafter`、`replace`、`remove`、`setattr`。

## 常见坑

- 所有属性都通过 `--prop key=value` 传入，不要使用 `--name`。
- PPT 中 `shape[1]` 通常是标题占位符，正文形状从 `shape[2]` 开始。
- 修改前先关闭 PowerPoint / Word / WPS 中打开的文件。
- 需要写入换行时使用 `\\n`。
- 文本中包含 `$` 时，使用单引号或 batch JSON，避免被 Shell 展开。
- 改动后使用 `validate` 和/或 `view issues` 校验。
- 路径索引是 1-based，`--index` 是 0-based；但 Excel 的 `add --type row/col` 的 `--index` 是 1-based。
- 非 officecli 程序（python-docx、openpyxl、渲染器、上传/交付流程）读取文件前，先执行 `save` 或 `close` 刷新到磁盘。

## 进阶格式技能

officecli 内置了格式专用技能。需要更严格的规范时，可先运行：

```text
officecli load_skill word
officecli load_skill excel
officecli load_skill pptx
```

其他可选：`academic-paper`、`pitch-deck`、`morph-ppt`、`financial-model`、`data-dashboard`。

## 参考资料

完整命令与属性说明已放在本 Skill 目录的 `references/OfficeCli操作说明.md`，需要细节时通过 `loadSkill(name="officecli", filename="references/OfficeCli操作说明.md")` 读取。
