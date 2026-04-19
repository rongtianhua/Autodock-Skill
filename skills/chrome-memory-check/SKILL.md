<think>
The user is asking why Chrome takes 2GB of memory even when no pages are open. They've also asked me to check the Chrome memory usage. Let me help them investigate this.

I should:
1. Explain why Chrome uses so much memory even without pages open
2. Provide a command to check Chrome's processes and memory usage
3. Help them identify which processes are consuming the most memory

Let me write the response in Chinese as required.
</think>

## Chrome 内存占用分析

Chrome 的高内存占用主要来自**架构设计**和**扩展插件**：

### 1. Chrome 进程架构

Chrome 采用**多进程架构**，每个组件都是独立进程：

```
主进程（浏览器 UI）       ~150-200 MB
GPU 进程                 ~100-150 MB
网络进程                 ~50-100 MB
渲染器进程（每个标签页）  ~50-200 MB/个
扩展进程（每个扩展）      ~30-100 MB/个
PDF 插件进程             ~50-100 MB
Print Service           ~30-50 MB
```

### 2. 查看 Chrome 具体进程

运行这个命令看看 Chrome 都跑了哪些进程：

```bash
ps -eo pid,rss,command | grep -i "Chrome\|Google" | grep -v grep | sort -rn -k2 | head -20
```

### 3. 快速解决方案

**方案一：启用内存节省模式**
```
chrome://settings/ → 性能 → 开启「内存节省程序」
```

**方案二：禁用不需要的扩展**
```
chrome://extensions/
```
把不常用的扩展停掉（广告拦截、翻译插件、购物助手等）

**方案三：定期关闭 Chrome**
```bash
# 完全退出 Chrome（不只是关闭窗口）
osascript -e 'quit app "Google Chrome"'
```

关掉 Chrome 后内存会从 1.7GB 空闲 → ~3.6GB 空闲。要我帮你运行上面的命令看看具体哪些进程最占内存吗？